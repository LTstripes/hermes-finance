import { expect, test } from "@playwright/test";

test("one-time source proof survives Back/Reload in ordinary Month and monthly GET; ABA retires it", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  const inputs = await (await request.get("/api/synthetic-proof-inputs")).json();
  const writes: string[] = [];
  page.on("request", (item) => {
    if (item.method() === "POST") writes.push(new URL(item.url()).pathname);
  });
  await page.goto("/v2/capital/monthly-returns?source_account=1234567");
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
  expect(april.growth_kopecks).toBe(60000);
  expect(may.growth_kopecks).toBeNull();
  await page.reload();
  await expect(proof.getByText(/Источник подтверждён:/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Взносы и рост", exact: true })).toContainText(
    "600,00 ₽",
  );
  await proof.screenshot({ path: info.outputPath("source-proof-current-reload.png") });
  await page.goto(`/v2/close?month=${inputs.month_id}&source_account=1234567`);
  const summary = page.getByRole("region", {
    name: "Предварительная доходность месяца",
    exact: true,
  });
  await expect(summary).toContainText("600 ₽");
  await expect(summary).toContainText("Modified Dietz");
  await summary.screenshot({ path: info.outputPath("source-proof-current-month.png") });
  await summary.getByRole("link", { name: "Доходность и подтверждение источников" }).click();
  await expect(proof.getByText(/Источник подтверждён:/)).toBeVisible();
  await page.goBack();
  await expect(summary).toContainText("600 ₽");
  await page.reload();
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
  await expect(summary).not.toContainText("600 ₽");
  await expect(summary).toContainText("Подтверждение источника устарело");
  await summary.screenshot({ path: info.outputPath("source-proof-stale-month.png") });
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
    "/v2/capital/monthly-returns?source_account=7654321&bond_period=2030-05-01&bond_isin=RU000STALE01#bond-slice",
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

  await page.getByLabel("Счёт в выписке", { exact: true }).selectOption("8765432");
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
    "/v2/capital/monthly-returns?source_account=7654321&bond_period=2030-05-01#bond-slice",
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

  await page.getByLabel("Счёт в выписке", { exact: true }).selectOption("8765432");
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
  await expect(page.getByLabel("Счёт в выписке", { exact: true })).toHaveValue("8765432");
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
  await page.goto(`/v2/close?month=${month.id}&source_account=2222222&instrument_isin=${stock}`);
  const panel = page.getByRole("region", { name: "Инструменты и выплаты месяца" });
  await expect(panel.getByRole("region", { name: `Инструмент ${stock}` })).toBeVisible();
  await expect(page.getByText(/Снимок 01.06.2030/)).toBeVisible();
  await expect(panel.getByText(/Интервал результата: \(2030-04-30, 2030-05-31\]/)).toBeVisible();
  const native = await (
    await request.get(
      "/api/source-returns/instruments?source_account=2222222&opening_date=2030-04-30&closing_date=2030-05-31",
    )
  ).json();
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

  const run = panel.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" });
  const responseA = page.waitForResponse((response) =>
    response.url().endsWith("/api/source-returns/payout-preview"),
  );
  await run.click();
  const a = await (await responseA).json();
  expect(a).toMatchObject({
    source_account: "2222222",
    native_source_account: "2222222-000",
    isin: stock,
    as_of: "2030-05-31",
    quantity: "10",
    financial_authority: "none",
  });
  expect(a.rows.filter((row: { countable_future: boolean }) => row.countable_future)).toHaveLength(
    2,
  );
  await expect(panel.getByRole("table", { name: "Будущие кандидаты (future)" })).toContainText(
    "25,00 ₽",
  );
  await expect(panel.getByRole("table", { name: "Будущие кандидаты (future)" })).not.toContainText(
    "possible_paid",
  );
  const requestsAfterA = (await (await request.get("/api/synthetic-month-state")).json())
    .provider_requests.length;
  await panel.getByLabel("Дата количества из выписки").fill("2030-04-30");
  await expect(panel.getByRole("table", { name: "Будущие кандидаты (future)" })).toHaveCount(0);
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(requestsAfterA);
  const missingResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/source-returns/payout-preview"),
  );
  await run.click();
  const missing = await (await missingResponse).json();
  expect(missing.quantity).toBeNull();
  expect(missing.rows).toHaveLength(0);
  await expect(panel.getByText(/количество: неизвестно на 2030-04-30/)).toBeVisible();
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(requestsAfterA);

  await page.getByLabel("Счёт источника месяца").selectOption("3333333");
  await panel.getByRole("button", { name: "Синтетическая акция месяца", exact: true }).click();
  await expect(panel.getByLabel("Дата количества из выписки")).toHaveValue("2030-05-31");
  await expect(panel.getByRole("table", { name: "Будущие кандидаты (future)" })).toHaveCount(0);
  const responseB = page.waitForResponse((response) =>
    response.url().endsWith("/api/source-returns/payout-preview"),
  );
  await run.click();
  const b = await (await responseB).json();
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
  const actuals = panel.getByRole("table", {
    name: "Actual для сверки · включая события после даты количества",
  });
  await expect(actuals).toContainText("2030-06-15");
  await expect(actuals).toContainText("12,34 ₽");
  await expect(
    panel.getByRole("table", { name: "Возможно уже выплачено (possible_paid)" }),
  ).toContainText("2030-06-15");
  await expect(panel.getByRole("region", { name: "Будущие кандидаты (future)" })).not.toContainText(
    "2030-06-15",
  );
  await panel.screenshot({ path: info.outputPath("month-stock-actual-possible-paid-1440.png") });

  await panel.getByRole("button", { name: "Синтетическая облигация", exact: true }).click();
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
  await expect(panel.getByRole("region", { name: `Инструмент ${bond}` })).toBeVisible();
  await expect(
    panel.getByRole("table", { name: "Actual для сверки · включая события после даты количества" }),
  ).toHaveCount(0);
  expect(
    (await (await request.get("/api/synthetic-month-state")).json()).provider_requests,
  ).toHaveLength(providerCount);
  await panel.getByRole("button", { name: "Синтетическая акция месяца", exact: true }).click();
  await page.goBack();
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
  expect(writes.every((path) => path === "/api/source-returns/payout-preview")).toBe(true);
});
