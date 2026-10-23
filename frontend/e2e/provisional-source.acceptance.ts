import fs from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("synthetic zero-metadata desktop: unbound intake → 211 RUB / 2.01%", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  const metadataRequests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (requestEvent) => {
    const path = new URL(requestEvent.url()).pathname;
    if (
      path === "/api/accounts" ||
      path === "/api/months" ||
      path.startsWith("/api/broker-months/preview") ||
      path.startsWith("/api/broker-months/apply")
    )
      metadataRequests.push(path);
  });

  const raw = await (await request.get("/api/synthetic-provisional-original")).body();
  const stateBefore = await (await request.get("/api/synthetic-provisional-state")).json();
  expect(stateBefore).toEqual({
    Account: 0,
    BrokerIdentityMapping: 0,
    BrokerMonthApply: 0,
    CashBalance: 0,
    Instrument: 0,
    MyBrokerImport: 0,
    PositionSnapshot: 0,
    ReportingMonth: 0,
  });
  const intakes = await (
    await request.get("/api/broker-months/intakes?include_unbound=true")
  ).json();
  expect(intakes).toHaveLength(1);
  const intake = intakes[0];
  expect(intake.state.account_id).toBeNull();
  expect(intake.state.reporting_month_id).toBeNull();

  await page.goto("/v2/data/source-intake");
  await expect(page.getByRole("heading", { name: "Разбор источника" })).toBeVisible();
  await expect(page.getByText(/Страница выбирает уже сохранённый журнал/)).toBeVisible();
  const picker = page.getByLabel("Сохранённый разбор");
  await picker.selectOption(String(intake.id));
  await expect(page.getByText(/без привязки к Hermes-счёту или отчётному месяцу/)).toBeVisible();
  await expect(page.getByText(/финансовая власть: нет/)).toBeVisible();

  const panel = page.getByRole("region", {
    name: "Предварительная доходность по source-intake",
  });
  await page.getByLabel("Точный оригинал XML").setInputFiles({
    name: "Брокерский 1234567 (01.04.30-30.04.30).xml",
    mimeType: "application/xml",
    buffer: raw,
  });
  const pending = page.waitForResponse((response) =>
    response.url().endsWith("/broker-statement-provisional/context"),
  );
  await panel.getByRole("button", { name: "Рассчитать наблюдаемые величины" }).click();
  const context = await (await pending).json();
  expect(context.scope).toBe("native_source");
  expect(context.account_id).toBeNull();
  expect(context.financial_authority).toBe("none");
  expect(context.journal.binding).toBe("unbound");
  expect(context.hard_blockers).toEqual([]);
  expect(context.observed.total_opening_kopecks).toBe("1000000");
  expect(context.observed.total_closing_kopecks).toBe("1121100");
  await expect(panel.getByText(/нативный счёт строк/)).toBeVisible();
  await expect(panel.getByText(/Изменение стоимости по отчёту брокера: 1.211,00/)).toBeVisible();

  await panel.getByRole("button", { name: "Рассчитать предварительный сценарий" }).click();
  await expect(panel.getByText("Выбери все необходимые допущения и режим графика.")).toBeVisible();
  for (const requirement of context.required_assumptions)
    await panel
      .getByLabel(requirement.requirement_id, { exact: true })
      .selectOption(requirement.choices[0]);
  await panel.getByLabel("Режим графика", { exact: true }).selectOption("dated");
  const evaluated = page.waitForResponse((response) =>
    response.url().endsWith("/broker-statement-provisional/evaluate"),
  );
  await panel.getByRole("button", { name: "Рассчитать предварительный сценарий" }).click();
  const result = await (await evaluated).json();
  expect(result.scope).toBe("native_source");
  expect(result.account_id).toBeNull();
  expect(result.scenario_result_kopecks).toBe("21100");
  await expect(panel.getByText(/2,01% · за фактический период, не аннулизировано/)).toBeVisible();
  await expect(
    panel.getByText(/Сценарный результат после выбранных внешних движений: 211,00/),
  ).toBeVisible();
  await panel.screenshot({ path: info.outputPath("synthetic-provisional-1440.png") });
  await page.screenshot({
    path: info.outputPath("synthetic-provisional-combined-1440.png"),
    fullPage: true,
  });

  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Экспорт предварительного расчёта JSON" }).click();
  const path = await (await download).path();
  expect(JSON.parse(await fs.readFile(path, "utf8"))).toEqual(result);

  const stateAfter = await (await request.get("/api/synthetic-provisional-state")).json();
  expect(stateAfter).toEqual(stateBefore);
  const after = await (await request.get(`/api/broker-months/intakes/${intake.id}`)).json();
  expect(after.head_seq).toBe(intake.head_seq);
  expect(after.history).toEqual(intake.history);
  expect(metadataRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test("renamed XML and second account upload, reload and blocked provisional result", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const source = await (await request.get("/api/synthetic-provisional-original")).text();
  const first = source.replace(">", ' synthetic_revision="935-b2">');
  const account = /acc_code="([^"]+)"/.exec(first)?.[1];
  if (!account) throw new Error("Synthetic account missing from fixture");
  const second = first.replaceAll(account, "7654321");
  const stateBefore = await (await request.get("/api/synthetic-provisional-state")).json();
  await page.goto("/v2/capital/monthly-returns");
  await page.getByLabel("XML-файлы", { exact: true }).setInputFiles([
    { name: "renamed.xml", mimeType: "application/xml", buffer: Buffer.from(first) },
    {
      name: "Брокерский 7654321 (01.04.30-30.04.30).xml",
      mimeType: "application/xml",
      buffer: Buffer.from(second),
    },
  ]);
  await expect(page.getByText(/renamed.xml: Сохранен/)).toBeVisible();
  await expect(page.getByText(/7654321.*Сохранен/)).toBeVisible();
  await page.reload();
  const intakes = await (
    await request.get("/api/broker-months/intakes?include_unbound=true")
  ).json();
  const inferred = intakes.find((row: { document: { warnings?: string[] } }) =>
    row.document.warnings?.includes("period_inferred_from_content"),
  );
  expect(inferred).toBeTruthy();
  expect(
    intakes.some(
      (row: { document: { filename_account: string } }) =>
        row.document.filename_account === "7654321",
    ),
  ).toBeTruthy();
  await page.goto("/v2/data/source-intake");
  await page.getByLabel("Сохранённый разбор").selectOption(String(inferred.id));
  await page.getByLabel("Точный оригинал XML").setInputFiles({
    name: "renamed.xml",
    mimeType: "application/xml",
    buffer: Buffer.from(first),
  });
  const panel = page.getByRole("region", { name: "Предварительная доходность по source-intake" });
  const pending = page.waitForResponse((response) =>
    response.url().endsWith("/broker-statement-provisional/context"),
  );
  await panel.getByRole("button", { name: "Рассчитать наблюдаемые величины" }).click();
  const context = await (await pending).json();
  expect(context.hard_blockers).toContain("source_period_inferred");
  expect(context.observed.total_opening_kopecks).toBeNull();
  expect(context.observed.total_closing_kopecks).toBeNull();
  await expect(panel.getByText("source_period_inferred", { exact: true })).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Рассчитать предварительный сценарий" }),
  ).toBeDisabled();
  await panel.screenshot({ path: info.outputPath("renamed-period-blocked-1440.png") });
  expect(await (await request.get("/api/synthetic-provisional-state")).json()).toEqual(stateBefore);
  expect(errors).toEqual([]);
});
