import { expect, type Page, test } from "@playwright/test";

async function selectWithManual(page: Page, manualId: number, decision = "count_manual") {
  await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
  await expect(page.getByText(/Возможный ручной дубль/)).toBeVisible();
  await page.getByRole("button", { name: "Развернуть всё" }).click();
  await page.getByLabel("Решение для дубля 1").selectOption(decision);
  await page.getByLabel("Ручная запись для дубля 1").selectOption(String(manualId));
  await page.getByRole("button", { name: "Выбрать доступные" }).click();
}

async function confirmBulk(page: Page, groups: number) {
  await page.getByRole("button", { name: "Применить выбранные", exact: true }).click();
  await page.getByRole("button", { name: `Подтвердить выбор (${groups} групп)` }).click();
}

test("individual Apply confirms through the real API and reload never submits", async ({
  page,
  request,
}) => {
  const created = await request.post("/api/months", {
    data: { year: 2037, month: 5, snapshot_date: "2037-05-12" },
  });
  expect(created.ok()).toBe(true);
  const month = await created.json();
  const position = await request.post("/api/positions", {
    data: {
      reporting_month_id: month.id,
      account_id: 1,
      instrument_id: 1,
      quantity: "2.000000",
      average_cost_per_unit: { amount: "100.00", currency: "RUB" },
      market_price_per_unit: { amount: "101.00", currency: "RUB" },
      price_date: "2037-05-12",
    },
  });
  expect(position.ok()).toBe(true);
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/payout-apply")) posts.push(request.url());
  });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(`/v2/data/payouts?month=${month.id}`);
  await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
  expect(posts).toEqual([]);
  await page.getByRole("button", { name: "Проверить выплаты T-Invest" }).click();
  await expect(page.getByText("Новая", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Применить выбранные \(1\)/ }).click();
  expect(posts).toEqual([]);
  await page.getByRole("button", { name: "Применить (1)", exact: true }).click();
  await expect(page.getByText(/Применено выплат: 1/)).toBeVisible();
  expect(posts).toHaveLength(1);
  const calendar = await (
    await request.get(`/api/payouts/calendar?month_id=${month.id}&forecast_version=v1`)
  ).json();
  const providers = calendar
    .flatMap(
      (entry: { items: { source_kind: string; amount: { amount: string } }[] }) => entry.items,
    )
    .filter((entry: { source_kind: string }) => entry.source_kind === "provider");
  expect(providers).toHaveLength(1);
  expect(providers[0].amount.amount).toBe("50.00");
  expect(await (await request.get(`/api/investment-flows?month_id=${month.id}`)).json()).toEqual(
    [],
  );
  await page.reload();
  await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
  expect(posts).toHaveLength(1);
  await expect(page.getByRole("button", { name: /Применить выбранные \(1\)/ })).toHaveCount(0);
});

for (const [monthId, decision] of [
  [6, "count_provider"],
  [7, "keep_both"],
] as const) {
  test(`real authoritative reconciliation ${decision}`, async ({ page, request }) => {
    await page.goto(`/v2/data/payouts?month=${monthId}`);
    await selectWithManual(page, monthId, decision);
    await confirmBulk(page, 2);
    await expect(page.getByText(/Подтверждено: 2 из 2/)).toBeVisible();
    const calendar = await (
      await request.get(`/api/payouts/calendar?month_id=${monthId}&forecast_version=v1`)
    ).json();
    const rows = calendar.flatMap((month: { items: unknown[] }) => month.items);
    expect(
      rows.filter((row: { source_kind: string }) => row.source_kind === "manual"),
    ).toHaveLength(decision === "keep_both" ? 1 : 0);
    const manual = await (
      await request.get(`/api/expected-flows?month_id=${monthId}&forecast_version=v1`)
    ).json();
    expect(manual[0].expected_net_amount.amount).toBe("999.00");
    expect(manual[0].is_confirmed).toBe(false);
  });
}

test("linked manual revision confirms before the next group using real receipts and calendars", async ({
  page,
  request,
}) => {
  await page.route("**/api/months/3/payout-batch-preview", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    // Review the linked instrument first to prove continuation after its revision.
    body.items.reverse();
    await route.fulfill({ response, json: body });
  });
  const receipts: { items: { reconciliation_id: number | null }[] }[] = [];
  page.on("response", async (response) => {
    if (response.url().endsWith("/payout-apply")) receipts.push(await response.json());
  });
  await page.goto("/v2/data/payouts?month=3");
  await selectWithManual(page, 3);
  await confirmBulk(page, 2);
  await expect(page.getByText(/Подтверждено: 2 из 2/)).toBeVisible();
  await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
  await expect(page.getByText(/Изменена: проверь детали/).first()).toBeVisible();
  await page.getByRole("button", { name: "Выбрать доступные" }).click();
  await expect(page.getByText("Выбрано событий: 2")).toBeVisible();
  await confirmBulk(page, 2);
  await expect(page.getByText(/Подтверждено: 2 из 2/)).toBeVisible();
  expect(receipts).toHaveLength(4);
  expect(receipts[2].items[0].reconciliation_id).toBe(receipts[0].items[0].reconciliation_id);
  expect(receipts[2].items[0].reconciliation_id).not.toBeNull();
  const calendar = await (
    await request.get("/api/payouts/calendar?month_id=3&forecast_version=v1")
  ).json();
  expect(
    calendar
      .flatMap((month: { items: { expected_date: string }[] }) => month.items)
      .some((row: { expected_date: string }) => row.expected_date === "2032-06-16"),
  ).toBe(true);
  expect(await (await request.get("/api/investment-flows?month_id=3")).json()).toEqual([]);
});

test("real provider failure keeps earlier confirmation and stops the frozen bulk", async ({
  page,
  request,
}) => {
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/payout-apply")) posts.push(request.url());
  });
  await page.goto("/v2/data/payouts?month=4");
  await selectWithManual(page, 4);
  await confirmBulk(page, 2);
  await expect(page.getByText(/REJECTED_NO_WRITE/)).toBeVisible();
  await expect(page.getByText(/Подтверждено: 1 из 2/)).toBeVisible();
  expect(posts).toHaveLength(2);
  const calendar = await (
    await request.get("/api/payouts/calendar?month_id=4&forecast_version=v1")
  ).json();
  expect(
    calendar
      .flatMap((month: { items: { source_kind: string }[] }) => month.items)
      .filter((row: { source_kind: string }) => row.source_kind === "provider"),
  ).toHaveLength(1);
  await page.reload();
  await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
  expect(posts).toHaveLength(2);
});

test("committed response loss never retries; reload needs fresh preview and explicit reconfirmation", async ({
  page,
}) => {
  let first = true;
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/payout-apply")) posts.push(request.url());
  });
  await page.route("**/api/months/5/payout-apply", async (route) => {
    if (first) {
      first = false;
      await route.fetch(); // Real SQLite commit, then lose only the browser reply.
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto("/v2/data/payouts?month=5");
  await selectWithManual(page, 5);
  await confirmBulk(page, 2);
  await expect(page.getByText(/UNKNOWN/)).toBeVisible();
  await expect(page.getByText(/NOT_SENT/)).toBeVisible();
  expect(posts).toHaveLength(1);
  await page.reload();
  await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
  expect(posts).toHaveLength(1);
  await selectWithManual(page, 5);
  await expect(page.getByText(/ALREADY_PRESENT/).first()).toBeVisible();
  expect(posts).toHaveLength(1);
  await confirmBulk(page, 1);
  await expect(page.getByText(/Подтверждено: 1 из 1/)).toBeVisible();
  expect(posts).toHaveLength(2);
});

for (const width of [1366, 390]) {
  test(`synthetic real-backend payout journey ${width}px`, async ({ page, request }, testInfo) => {
    const monthId = width === 1366 ? 1 : 2;
    const positionId = width === 1366 ? 1 : 5;
    await page.setViewportSize({ width, height: 900 });
    const posts: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push(request.url());
    });
    await page.goto(
      `/v2/data/payouts?month=${monthId}&from=monthly-close-v2&step=future_payouts&monthId=${monthId}`,
    );
    await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
    expect(posts).toEqual([]);
    await expect(page.getByLabel("PDF отчёта Alfa")).toHaveCount(0);
    await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
    await expect(page.getByText(/Возможный ручной дубль/)).toBeVisible();
    await expect(page.locator(`#payout-group-${positionId}`)).toBeHidden();
    await expect(page.locator(`#payout-group-${positionId + 1}`)).toBeHidden();
    await page.getByRole("button", { name: "Развернуть всё" }).click();
    await page.getByLabel("Решение для дубля 1").selectOption("count_manual");
    await page.getByLabel("Ручная запись для дубля 1").selectOption(String(monthId));
    await page.getByRole("button", { name: "Выбрать доступные" }).click();
    await expect(page.getByText("Выбрано событий: 3")).toBeVisible();
    await page.getByRole("button", { name: "Свернуть всё" }).click();
    await expect(page.getByText(/Возможный ручной дубль/)).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`collapsed-${width}.png`), fullPage: true });
    const apply = page.getByRole("button", { name: "Применить выбранные", exact: true });
    await apply.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await page.keyboard.press("Escape");
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(0);
    await apply.focus();
    await page.keyboard.press("Enter");
    const confirm = page.getByRole("button", { name: "Подтвердить выбор (2 групп)" });
    await confirm.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Подтверждено: 2 из 2/)).toBeVisible();
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(2);
    await page.screenshot({ path: testInfo.outputPath(`confirmed-${width}.png`), fullPage: true });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ).toBe(true);
    const actual = await request.get(`/api/investment-flows?month_id=${monthId}`);
    expect(await actual.json()).toEqual([]);
    const manual = await request.get(`/api/expected-flows?month_id=${monthId}&forecast_version=v1`);
    const rows = await manual.json();
    expect(rows).toHaveLength(1);
    expect(rows[0].expected_net_amount.amount).toBe("999.00");
    expect(rows[0].is_confirmed).toBe(false);
    await page.reload();
    await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(2);
    await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
    await expect(page.getByText(/ALREADY_PRESENT/).first()).toBeVisible();
    await expect(page.getByText("Выбрано событий: 0")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Применить выбранные", exact: true }),
    ).toBeDisabled();
    await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
      "href",
      `/v2/close?month=${monthId}&step=future_payouts`,
    );
  });
}
