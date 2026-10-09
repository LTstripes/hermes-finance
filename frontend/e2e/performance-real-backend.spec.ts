import { type APIRequestContext, expect, test } from "@playwright/test";

// Public supported writes only; the existing G04 server owns a fresh synthetic DB.
// No request interception, provider access or inference of historical evidence.
test("Checkpoint A: preparation/readback → XIRR → observed PRE/POST → TWRR", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(60_000);
  const api = "http://127.0.0.1:8000/api";
  const start = "2040-01-31";
  const end = "2040-02-29";
  const money = (amount: string) => ({ amount, currency: "RUB" });
  async function write(path: string, data: unknown, method = "POST", status = 201) {
    const response = await request.fetch(`${api}${path}`, { method, data });
    expect(response.status(), await response.text()).toBe(status);
    return response.json();
  }
  async function read(path: string, params: Record<string, string | number>) {
    const response = await request.get(`${api}${path}`, { params });
    expect(response.status(), await response.text()).toBe(200);
    return response.json();
  }
  const opening = await write("/months", { year: 2040, month: 1, snapshot_date: start });
  const closing = await write("/months", { year: 2040, month: 2, snapshot_date: end });
  const account = await write("/accounts", {
    name: "Synthetic Performance Journey",
    account_type: "brokerage",
  });
  const instrument = await write("/instruments", {
    name: "Synthetic Performance Instrument",
    instrument_type: "bond",
  });
  const params = { start_date: start, end_date: end, scope: "account", account_id: account.id };
  const history = await read("/performance/membership", params);
  await write(
    "/performance/membership",
    {
      ...params,
      form_token: history.form_token,
      replaced_ids: [],
      replacements: [{ effective_from: start, effective_to: end, include_in_returns: true }],
      attested: true,
    },
    "POST",
    200,
  );
  for (const month of [opening, closing]) {
    await write("/positions", {
      reporting_month_id: month.id,
      account_id: account.id,
      instrument_id: instrument.id,
      quantity: "1",
      average_cost_per_unit: money("1000.00"),
      market_price_per_unit: money(month.id === opening.id ? "1000.00" : "1200.00"),
      price_date: month.snapshot_date,
    });
    await write("/cash-balances", {
      reporting_month_id: month.id,
      account_id: account.id,
      name: "Synthetic cash",
      amount: money("0.00"),
    });
    // Canonical valuation requires explicit coverage of every asset component.
    await write("/deposits", {
      reporting_month_id: month.id,
      account_id: account.id,
      name: "Synthetic confirmed zero deposit",
      deposit_type: "deposit",
      balance: money("0.00"),
      annual_rate: "0.00",
    });
  }
  const flow = await write("/external-flows", {
    reporting_month_id: closing.id,
    account_id: account.id,
    event_date: "2040-02-15",
    boundary_amount: money("100.00"),
    direction: "contribution",
    kind: "external_contribution",
    scope_membership: "stable_in_scope",
    source: "synthetic_confirmed_source",
  });
  const initial = await read("/performance/readiness", params);
  expect(initial.xirr.availability).not.toBe("available");
  expect(initial.twrr.availability).not.toBe("available");
  expect(initial.diagnostics.length).toBeGreaterThan(1);

  const url = `/v2/capital/performance?start=${start}&end=${end}&scope=account&account_id=${account.id}&view=accounts&prepare_account=${account.id}&prepare_reason=cash_history#performance-preparation`;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(url);
  await expect(page.getByTestId("performance-detail-xirr-reason")).toBeVisible();
  for (const name of ["Денежная история", "Неденежная история"]) {
    const field = page.getByRole("group", { name, exact: true });
    await field.getByLabel("История сверена полностью за весь указанный период").check();
    await field.getByRole("checkbox").last().check();
    const button = field.getByRole("button", { name: `Сохранить: ${name.toLowerCase()}` });
    await button.focus();
    const saved = page.waitForResponse(
      (r) => r.url().includes("boundary-coverages") && r.request().method() === "POST",
    );
    await page.keyboard.press("Enter");
    expect((await saved).status()).toBe(201);
    await expect(page.getByText(/Запись подтверждена\. Данные перечитаны/)).toBeVisible();
  }
  const preparation = await read("/performance/preparation", params);
  expect(preparation.cash_coverages[0].coverage_state).toBe("complete");
  expect(preparation.in_kind_coverages[0].coverage_state).toBe("complete");
  expect(preparation.flows[0].id).toBe(flow.id);
  for (const month of [opening, closing]) await write(`/months/${month.id}/close`, {}, "POST", 200);
  const xirrOnly = await read("/performance/readiness", params);
  expect(xirrOnly.xirr.availability, JSON.stringify(xirrOnly.xirr.reason_codes)).toBe("available");
  expect(xirrOnly.xirr.value).not.toBeNull();
  expect(xirrOnly.twrr.availability).not.toBe("available");
  const closed = await read("/performance/valuation-captures", params);
  expect(closed.targets[0].capture_capability).toBe("requires_reopen");
  const rejected = await request.patch(`${api}/external-flows/${flow.id}`, {
    data: { boundary_amount: money("125.00") },
  });
  expect(rejected.status()).toBe(409);
  expect((await read("/performance/preparation", params)).flows[0].boundary_amount).toEqual(
    money("100.00"),
  );
  await write(`/months/${closing.id}/reopen`, {}, "POST", 200);
  await page.reload();
  // Independent, explicitly observed synthetic source values, not derived in the test.
  for (const [relation, amount] of [
    ["pre_external_flow", "1100.00"],
    ["post_external_flow", "1200.00"],
  ]) {
    await page.getByLabel("Сторона наблюдения").selectOption(relation);
    await page.getByLabel("Сумма наблюдения").fill(amount);
    await page.getByLabel("Источник наблюдения", { exact: true }).fill("synthetic_observed_source");
    await page.getByLabel(/Я ввёл.*подтверждённую фактически/).check();
    const saved = page.waitForResponse(
      (r) => r.url().includes("valuation-captures") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Сохранить наблюдение", exact: true }).click();
    const response = await saved;
    expect(response.status(), await response.text()).toBe(200);
    const body = await response.json();
    expect(body.captured.relation).toBe(relation);
    const sides = body.targets[0][relation];
    expect(sides[0].bound).toBe(true);
    expect(sides[0].total_value).toEqual(money(amount));
    await expect(page.getByText(/Запись подтверждена: значение сохранено/)).toBeVisible();
  }
  await write(`/months/${closing.id}/close`, {}, "POST", 200);
  const final = await read("/performance/readiness", params);
  expect(final.xirr.availability).toBe("available");
  expect(final.twrr.availability).toBe("available");
  expect(final.twrr.value).not.toBeNull();
  await page.reload();
  await expect(page.getByTestId("performance-detail-xirr")).toContainText("%");
  await expect(page.getByTestId("performance-detail-twrr")).toContainText("%");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.screenshot({
    path: testInfo.outputPath("performance-1440-both-available.png"),
    fullPage: true,
  });
  await page.goto("/v2/capital");
  await page.goBack();
  await expect(page).toHaveURL(`http://127.0.0.1:5173${url}`);
  await expect(page.getByTestId("performance-detail-twrr")).toContainText("%");

  // Material correction revokes cash and PRE/POST authority; stale capture cannot revive it.
  await write(`/months/${closing.id}/reopen`, {}, "POST", 200);
  await write(`/external-flows/${flow.id}`, { boundary_amount: money("125.00") }, "PATCH", 200);
  const changed = await read("/performance/valuation-captures", params);
  expect(changed.readiness.twrr.availability).not.toBe("available");
  const target = changed.targets[0];
  await write(`/external-flows/${flow.id}`, { boundary_amount: money("150.00") }, "PATCH", 200);
  await rejectStaleCapture(request, `${api}/performance/valuation-captures`, {
    ...params,
    form_token: target.form_token,
    external_flow_id: flow.id,
    relation: "pre_external_flow",
    expected_material_signature: target.material_signature,
    total_value: "1100.00",
    performance_currency: "RUB",
    coverage: "complete",
    quality: "exact",
    provenance_kind: "synthetic_observed_source",
    attested: true,
  });
  expect((await read("/performance/preparation", params)).cash_coverages[0].coverage_state).toBe(
    "unknown",
  );
  await write(`/months/${closing.id}/close`, {}, "POST", 200);
  const invalidated = await read("/performance/readiness", params);
  expect(invalidated.xirr.availability).not.toBe("available");
  expect(invalidated.twrr.availability).not.toBe("available");
  await page.reload();
  await expect(page.getByTestId("performance-detail-xirr-reason")).toBeVisible();
  await expect(page.getByTestId("performance-detail-twrr-reason")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("performance-1440-fail-closed.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

async function rejectStaleCapture(request: APIRequestContext, url: string, data: unknown) {
  const response = await request.post(url, { data });
  expect(response.status(), await response.text()).toBe(409);
}
