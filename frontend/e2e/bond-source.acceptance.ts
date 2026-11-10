import { expect, type Page, type Locator, test } from "@playwright/test";
import { displayMetric } from "../src/ui-v2/returns/model";

async function openDisclosure(page: Page, name: string) {
  const summary = page.getByText(name, { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
  await expect(summary.locator("..")).toHaveAttribute("open", "");
}

async function openReturnDiagnostics(page: Page, link: Locator) {
  const href = await link.getAttribute("href");
  expect(href).toBeTruthy();
  const target = new URL(href ?? "", page.url());
  target.searchParams.set("diagnostics", "performance");
  await page.goto(target.toString());
  await openDisclosure(page, "Подробнее о данных");
}

test("API Decimal boundary rates render identically in Month and Returns after Back/Reload", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  const inputs = await (await request.get("/api/synthetic-proof-inputs")).json();
  const before = await (await request.get("/api/synthetic-bond-state")).json();
  const writes: string[] = [];
  page.on("request", (item) => {
    if (!["GET", "HEAD"].includes(item.method())) writes.push(item.method());
  });
  let fraction = "0.001259";
  // Synthetic response at the API/display boundary; do not mutate financial fixtures.
  await page.route("**/api/source-returns/monthly?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const row of body.months) {
      if (row.closing_date === "2030-04-30") row.modified_dietz_return = fraction;
    }
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/returns/overview?**", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.selected.rate = { ...body.selected.rate, value: fraction, unit: "fraction" };
    await route.fulfill({ response, json: body });
  });
  for (const [value, expected] of [
    ["0.001259", "0,13%"],
    ["-0.00125", "−0,13%"],
    ["0.00009999", "0,01%"],
    ["-0.00995", "−1,00%"],
    ["0.99995", "100,00%"],
  ]) {
    fraction = value;
    await page.goto(`/v2/close?month=${inputs.month_id}&source_account=1234567&panel=brokers`);
    await openDisclosure(page, "Подробности предварительного результата");
    const card = page.getByRole("region", { name: "Предварительная доходность месяца" });
    await expect(card).toContainText(expected);
    await card.getByText("Источники расчёта", { exact: true }).click();
    await openReturnDiagnostics(
      page,
      card.getByRole("link", { name: "Доходность и подтверждение источников" }),
    );

    const monthly = page.getByRole("region", { name: "Результат периода", exact: true });
    await expect(monthly).toContainText(expected);
    await page.reload();
    await expect(monthly).toContainText(expected);
    await page.goBack();
    await openDisclosure(page, "Подробности предварительного результата");
    await expect(card).toContainText(expected);
  }
  await page.getByRole("region", { name: "Предварительная доходность месяца" }).screenshot({
    path: info.outputPath("source-rate-half-up-carry.png"),
  });
  expect(writes).toEqual([]);
  expect(await (await request.get("/api/synthetic-bond-state")).json()).toEqual(before);
});

test("source structure proof survives Back/Reload and unrelated financial ABA", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  const inputs = await (await request.get("/api/synthetic-proof-inputs")).json();
  const writes: string[] = [];
  page.on("request", (item) => {
    if (item.method() === "POST") writes.push(new URL(item.url()).pathname);
  });
  await page.goto("/v2/returns/account?diagnostics=1&period=history&scope=source:1234567");
  const proof = page.getByRole("region", {
    name: "Подтверждение источников доходности",
    exact: true,
  });
  await expect(proof.getByText(/Оригиналы можно проверить один раз/)).toBeVisible();
  await proof.getByLabel("Оригиналы для подтверждения").setInputFiles(inputs.paths);
  await proof.getByRole("button", { name: "Проверить оригиналы", exact: true }).focus();
  await page.keyboard.press("Enter");
  const preview = proof.getByRole("region", { name: "Preview подтверждения источника" });
  await expect(preview).toBeVisible();
  await expect(preview.getByRole("button", { name: "Сохранить подтверждение" })).toBeDisabled();
  await preview.getByRole("checkbox").focus();
  await page.keyboard.press("Space");
  await preview.getByRole("button", { name: "Сохранить подтверждение" }).focus();
  await page.keyboard.press("Enter");
  await expect(proof.getByText(/Источник подтверждён:/)).toBeVisible();
  const get = await (
    await request.get("/api/source-returns/monthly?source_account=1234567")
  ).json();
  const april = get.months.find(
    (row: { closing_date: string }) => row.closing_date === "2030-04-30",
  );
  const may = get.months.find((row: { closing_date: string }) => row.closing_date === "2030-05-31");
  const june = get.months.find(
    (row: { closing_date: string }) => row.closing_date === "2030-06-30",
  );
  expect(get.source_proof.status).toBe("current");
  expect(april.growth_kopecks).toBe(60000);
  expect(may.growth_kopecks).toBeNull();
  expect(june.growth_kopecks).toBe(60000);
  await page.reload();
  await expect(proof.getByText(/Источник подтверждён:/)).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Счёт", exact: true })).toHaveValue(
    "source:1234567-000",
  );
  // The old account-cash subtotal cannot be presented as a clean security
  // result. The new history uses clean operands; original monthly evidence is
  // verified separately above and remains inspectable in the month history.
  const history = page.getByRole("region", { name: "За всю историю", exact: true });
  const current = new URL(page.url());
  const initialOverview = await (
    await request.get(
      `/api/returns/overview?${new URLSearchParams({ scope: current.searchParams.get("scope") ?? "", start: current.searchParams.get("start") ?? "", end: current.searchParams.get("end") ?? "" })}`,
    )
  ).json();
  if (initialOverview.all_history?.pnl.value != null) {
    await expect(history.getByRole("heading", { name: /истори/i })).toBeVisible();
    await expect(history).not.toContainText("%");
  } else await expect(history).toHaveCount(0);
  const knownMonths = initialOverview.history.some(
    (row: { pnl: { value: string | null }; rate: { value: string | null } }) =>
      row.pnl.value !== null || row.rate.value !== null,
  );
  await expect(page.getByRole("region", { name: "Результат по месяцам" })).toHaveCount(
    knownMonths ? 1 : 0,
  );
  await proof.screenshot({ path: info.outputPath("source-proof-current-reload.png") });
  await page.goto(`/v2/close?month=${inputs.month_id}&source_account=1234567&panel=brokers`);
  await openDisclosure(page, "Подробности предварительного результата");
  const summary = page.getByRole("region", {
    name: "Предварительная доходность месяца",
    exact: true,
  });
  await expect(summary).toContainText("600 ₽");
  await expect(summary).toContainText("Modified Dietz");
  await summary.screenshot({ path: info.outputPath("source-proof-current-month.png") });
  await summary.getByText("Источники расчёта", { exact: true }).click();
  await openReturnDiagnostics(
    page,
    summary.getByRole("link", { name: "Доходность и подтверждение источников" }),
  );

  await expect(proof.getByText(/Источник подтверждён:/)).toBeVisible();
  const selected = page.getByRole("region", { name: "Результат периода", exact: true });
  const cleanOverview = await (
    await request.get(
      "/api/returns/overview?scope=source%3A1234567-000&start=2030-03-31&end=2030-04-30",
    )
  ).json();
  expect(cleanOverview.contract_version).toBe("returns_source_v2");
  expect(new URL(page.url()).searchParams.get("start")).toBe("2030-03-31");
  expect(new URL(page.url()).searchParams.get("end")).toBe("2030-04-30");
  if (
    cleanOverview.selected.pnl.value !== null ||
    cleanOverview.selected.rate.value !== null ||
    cleanOverview.selected_available_months_total?.pnl.value != null
  ) {
    await expect(selected).toContainText("31.03.2030 — 30.04.2030");
    if (cleanOverview.selected.pnl.value !== null)
      await expect(selected).toContainText(displayMetric(cleanOverview.selected.pnl, true));
    else if (cleanOverview.selected.rate.value !== null)
      await expect(selected).toContainText(displayMetric(cleanOverview.selected.rate));
    else
      await expect(selected).toContainText(
        displayMetric(cleanOverview.selected_available_months_total.pnl, true),
      );
  } else await expect(selected).toHaveCount(0);
  if (cleanOverview.all_history?.pnl.value != null) {
    await expect(history).toContainText(displayMetric(cleanOverview.all_history.pnl, true));
    await expect(history.getByRole("heading", { name: /истори/i })).toBeVisible();
  } else await expect(history).toHaveCount(0);
  await page.goBack();
  await openDisclosure(page, "Подробности предварительного результата");
  await expect(summary).toContainText("600 ₽");
  await page.reload();
  await openDisclosure(page, "Подробности предварительного результата");
  await expect(summary).toContainText("600 ₽");
  expect(writes).toEqual([
    "/api/source-returns/proofs/preview",
    "/api/source-returns/proofs/confirm",
  ]);
  expect((await (await request.get("/api/synthetic-proof-inputs")).json()).other_tables).toEqual(
    inputs.other_tables,
  );
  await request.post("/api/synthetic-proof-aba");
  await page.reload();
  await openDisclosure(page, "Подробности предварительного результата");
  await expect(summary).toBeVisible();
  // Classification ABA retires financial evidence, not immutable source structure.
  await expect(summary).toContainText(/600\s*₽/);
  await summary.getByText("Подробнее о предварительном расчёте", { exact: true }).click();
  await expect(summary).not.toContainText("Подтверждение источника устарело");
  const retained = await (
    await request.get("/api/source-returns/monthly?source_account=1234567")
  ).json();
  expect(retained.source_proof.status).toBe("current");
  expect(retained.source_proof.proof_id).toBe(get.source_proof.proof_id);
  for (const closing of ["2030-04-30", "2030-06-30"]) {
    const row = retained.months.find(
      (item: { closing_date: string }) => item.closing_date === closing,
    );
    expect(row.growth_kopecks).toBe(60000);
    expect(row.modified_dietz_return).not.toBeNull();
  }
  expect((await (await request.get("/api/synthetic-proof-inputs")).json()).other_tables).toEqual(
    inputs.other_tables,
  );
  await summary.screenshot({ path: info.outputPath("source-proof-financial-aba-retained.png") });
});

test("explicit stale bond ISIN stays unavailable on reload; account switch resets to its default", async ({
  page,
  request,
}, info) => {
  const before = await (await request.get("/api/synthetic-bond-state")).json();
  const mutations: string[] = [];
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method())) mutations.push(r.method());
  });
  await page.goto(
    "/v2/returns/account?diagnostics=1&period=history&scope=source:7654321&bond_period=2030-05-01&bond_isin=RU000STALE01#bond-slice",
  );
  const panel = page.getByRole("region", { name: "Облигации: позиции, сделки и купоны" });
  await expect(panel.getByText("Выбранная облигация недоступна", { exact: true })).toBeVisible();
  await expect(panel.getByText("RU000STALE01", { exact: true })).toBeVisible();
  await expect(panel.getByRole("region", { name: /Детали облигации/ })).toHaveCount(0);
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toHaveCount(0);
  await page.reload();
  await expect(panel.getByText("Выбранная облигация недоступна", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("bond_isin")).toBe("RU000STALE01");
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(panel.getByRole("region", { name: /Детали облигации/ })).toHaveCount(0);
  await panel.screenshot({ path: info.outputPath("bond-stale-isin.png") });
  await panel.getByRole("button", { name: "Синтетическая облигация", exact: true }).click();
  await expect(panel.getByRole("region", { name: "Детали облигации RU000A000001" })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("bond_isin")).toBe("RU000A000001");

  await page
    .getByRole("combobox", { name: "Счёт", exact: true })
    .selectOption("source:8765432-000");
  await expect(panel.getByText("8765432-000", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.has("bond_isin")).toBe(false);
  expect(new URL(page.url()).searchParams.has("bond_period")).toBe(false);
  await panel.getByLabel("Период облигаций").selectOption("2030-05-01");
  await expect(panel.getByRole("region", { name: "Детали облигации RU000A000001" })).toBeVisible();
  await page.reload();
  await expect(panel.getByText("8765432-000", { exact: true })).toBeVisible();
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(
    panel.getByRole("button", { name: "Синтетическая облигация", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    panel.getByRole("table", { name: "Облигации выбранного счёта и периода" }),
  ).toContainText("8");
  expect(new URL(page.url()).searchParams.has("bond_isin")).toBe(false);
  expect(await (await request.get("/api/synthetic-bond-state")).json()).toEqual(before);
  expect(mutations).toEqual([]);
});

test("two-account bond desktop: reported holdings, linked coupons, eligible estimates, unknown NKD and reload", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const before = await (await request.get("/api/synthetic-bond-state")).json();
  const errors: string[] = [];
  const mutations: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method())) mutations.push(`${r.method()} ${r.url()}`);
  });
  await page.goto(
    "/v2/returns/account?diagnostics=1&period=history&scope=source:7654321&bond_period=2030-05-01#bond-slice",
  );
  const panel = page.getByRole("region", { name: "Облигации: позиции, сделки и купоны" });
  await expect(panel.getByText("7654321-000", { exact: true })).toBeVisible();
  const first = withinTable();
  function withinTable() {
    return panel.getByRole("table", { name: "Облигации выбранного счёта и периода" });
  }
  await expect(first.getByRole("cell", { name: "2", exact: true })).toBeVisible();
  await expect(first.getByRole("cell", { name: /2.010,00/ })).toBeVisible();
  await expect(panel.getByText(/Сделок в выбранном интервале нет/)).toBeVisible();
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toContainText(
    "40,00 ₽",
  );
  await expect(panel.getByRole("table", { name: "Купоны по строкам источников" })).toContainText(
    "Сохранённая связь с инструментом",
  );
  const native = await (
    await request.get(
      "/api/source-returns/instruments?source_account=7654321&opening_date=2030-04-30&closing_date=2030-05-31",
    )
  ).json();
  const bond = native.instruments.find((row: { isin: string }) => row.isin === "RU000A000001");
  expect(native.financial_authority).toBe("none");
  expect(bond.analysis.pnl.value).toBeNull();
  expect(bond.analysis.modified_dietz.value).toBeNull();
  expect(bond.analysis.statement_estimate.pnl.value).toBe(4000);
  await panel.screenshot({ path: info.outputPath("bond-no-trade-1440.png") });

  await page
    .getByRole("combobox", { name: "Счёт", exact: true })
    .selectOption("source:8765432-000");
  await panel.getByLabel("Период облигаций").selectOption("2030-05-01");
  await expect(panel.getByText("8765432-000", { exact: true })).toBeVisible();
  await expect(withinTable().getByRole("cell", { name: "8", exact: true })).toBeVisible();
  await expect(panel.getByRole("table", { name: "Сделки по строкам источников" })).toContainText(
    "% от номинала",
  );
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toContainText(
    "55,00 ₽",
  );
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Счёт", exact: true })).toHaveValue(
    "source:8765432-000",
  );
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(withinTable().getByRole("cell", { name: "8", exact: true })).toBeVisible();
  await panel.getByLabel("Период облигаций").selectOption("2030-06-01");
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toHaveCount(0);
  await expect(panel.getByText("Условная оценка недоступна", { exact: true })).toBeVisible();
  await expect(panel.getByRole("table", { name: "Сделки по строкам источников" })).toContainText(
    "Не учтено в расчёте",
  );
  await panel.getByText("Полнота и происхождение", { exact: true }).click();
  await expect(panel.getByText(/Выписка #/).first()).toBeVisible();
  await panel.screenshot({ path: info.outputPath("bond-nkd-gap-1440.png") });
  await page.goBack();
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toBeVisible();
  expect(await (await request.get("/api/synthetic-bond-state")).json()).toEqual(before);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});

test("Month instruments and explicit source payout preview keep two accounts, dates, full/conditional/NULL and actual/candidate/future separate", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const before = await (await request.get("/api/synthetic-month-state")).json();
  const writes: string[] = [];
  page.on("request", (sent) => {
    if (!["GET", "HEAD"].includes(sent.method())) writes.push(new URL(sent.url()).pathname);
  });
  const months = await (await request.get("/api/months")).json();
  const month = months.find(
    (row: { year: number; month: number }) => row.year === 2030 && row.month === 5,
  );
  const stock = "RU000MONTH02";
  const bond = "RU000A000001";
  await page.goto(
    `/v2/close?month=${month.id}&source_account=2222222&instrument_isin=${stock}&panel=brokers`,
  );
  await openDisclosure(page, "Подробности инструментов и предварительных выплат");
  const panel = page.getByRole("region", { name: "Бумаги и выплаты" });
  await expect(panel.getByRole("region", { name: `Инструмент ${stock}` })).toBeVisible();
  await expect(page.getByText(/снимок 01.06.2030/i)).toBeVisible();
  await expect(panel.getByText(/Интервал результата: \(2030-04-30, 2030-05-31\]/)).toBeVisible();
  const native = await (
    await request.get(
      "/api/source-returns/instruments?source_account=2222222&opening_date=2030-04-30&closing_date=2030-05-31",
    )
  ).json();
  await panel.getByText("Сделки, выплаты и расчёт инструмента", { exact: true }).click();
  const stockData = native.instruments.find((row: { isin: string }) => row.isin === stock);
  expect(stockData.analysis.pnl.value).toBe(10000);
  expect(stockData.analysis.modified_dietz.value).toBe("0.1");
  await expect(panel.getByRole("heading", { name: "Полный P&L, ₽" }).locator("..")).toContainText(
    "100,00 ₽",
  );
  await expect(
    panel
      .getByRole("heading", { name: "Modified Dietz · приблизительно, за период", exact: true })
      .locator(".."),
  ).toContainText("10 %");
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(0);
  expect(writes).toEqual([]);

  await expect(
    panel.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" }),
  ).toHaveCount(0);
  // The Month route intentionally has no provider action. Keep the exact
  // synthetic backend reconciliation cases here; the default preview component
  // retains its table/currentness coverage in UiV2MonthInstruments.test.tsx.
  const preview = async (source_account: string, as_of: string) => {
    const response = await request.post("/api/source-returns/payout-preview", {
      data: { source_account, isin: stock, as_of },
    });
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const a = await preview("2222222", "2030-05-31");
  expect(a).toMatchObject({
    source_account: "2222222",
    native_source_account: "2222222-000",
    isin: stock,
    as_of: "2030-05-31",
    quantity: "10",
    financial_authority: "none",
  });
  const futureA = a.rows.filter((row: { countable_future: boolean }) => row.countable_future);
  expect(futureA).toHaveLength(2);
  expect(
    futureA.some(
      (row: { announced_amount_kopecks: string }) => row.announced_amount_kopecks === "2500",
    ),
  ).toBe(true);
  expect(futureA.every((row: { status: string }) => row.status === "future")).toBe(true);
  const requestsAfterA = (await (await request.get("/api/synthetic-month-state")).json())
    .provider_requests.length;
  const missing = await preview("2222222", "2030-04-30");
  expect(missing.quantity).toBeNull();
  expect(missing.rows).toHaveLength(0);
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(requestsAfterA);
  await openDisclosure(page, "Подробности");
  await page.getByLabel("Счёт источника месяца").selectOption("3333333");
  await openDisclosure(page, "Подробности инструментов и предварительных выплат");
  await expect(panel.getByText(/Выбранный счёт: 3333333 · нативный: 3333333-000/)).toBeVisible();
  await panel.getByRole("button", { name: "Синтетическая акция месяца", exact: true }).click();
  await expect(panel.getByLabel("Сохранённая дата количества")).toHaveValue("2030-05-31");
  await expect(panel.getByText(/Наблюдаемое количество: 5 на 2030-05-31/)).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(requestsAfterA);
  const b = await preview("3333333", "2030-05-31");
  expect(b).toMatchObject({
    source_account: "3333333",
    native_source_account: "3333333-000",
    isin: stock,
    quantity: "5",
    financial_authority: "none",
  });
  expect(
    b.actuals.some(
      (event: { event_date: string; net_payout_kopecks: string }) =>
        event.event_date === "2030-06-15" && event.net_payout_kopecks === "1234",
    ),
  ).toBe(true);
  expect(
    b.rows.find((row: { payment_date: string }) => row.payment_date === "2030-06-15").status,
  ).toBe("possible_paid");
  expect(
    b.rows
      .filter((row: { countable_future: boolean }) => row.countable_future)
      .every((row: { payment_date: string }) => row.payment_date !== "2030-06-15"),
  ).toBe(true);
  await panel.screenshot({ path: info.outputPath("month-stock-source-quantity-1440.png") });

  await panel.getByRole("button", { name: "Синтетическая облигация", exact: true }).click();
  await panel.getByText("Сделки, выплаты и расчёт инструмента", { exact: true }).click();
  await expect(panel.getByRole("heading", { name: "Полный P&L, ₽" }).locator("..")).toContainText(
    "Недоступен",
  );
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toBeVisible();
  await expect(
    panel.getByRole("table", { name: "Actual для сверки · включая события после даты количества" }),
  ).toHaveCount(0);
  const providerCount = (await (await request.get("/api/synthetic-month-state")).json())
    .provider_requests.length;
  await page.reload();
  await openDisclosure(page, "Подробности инструментов и предварительных выплат");
  await expect(panel.getByRole("region", { name: `Инструмент ${bond}` })).toBeVisible();
  await expect(
    panel.getByRole("table", { name: "Actual для сверки · включая события после даты количества" }),
  ).toHaveCount(0);
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(providerCount);
  await panel.getByRole("button", { name: "Синтетическая акция месяца", exact: true }).click();
  await page.goBack();
  await openDisclosure(page, "Подробности инструментов и предварительных выплат");
  await expect(panel.getByRole("region", { name: `Инструмент ${bond}` })).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await panel.screenshot({ path: info.outputPath("month-bond-conditional-null-1440-125.png") });
  const after = await (await request.get("/api/synthetic-month-state")).json();
  expect(after.snapshot_sha256).toBe(before.snapshot_sha256);
  expect(writes).toEqual([]);
});
