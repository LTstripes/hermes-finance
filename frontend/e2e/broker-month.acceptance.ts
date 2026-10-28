import { createHash } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";

async function monthPanel(page: Page, panel: "brokers" | "close") {
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: panel === "brokers" ? /Брокерские выписки/ : /Закрыть месяц/ })
    .click();
  const discard = page.getByRole("button", { name: "Перейти без сохранения", exact: true });
  // The router's dirty-input dialog may render after click() resolves.
  // Wait for either the destination or that explicit navigation decision.
  await expect
    .poll(
      async () =>
        new URL(page.url()).searchParams.get("panel") === panel || (await discard.isVisible()),
    )
    .toBe(true);
  if (await discard.isVisible()) await discard.click();
  await expect(page).toHaveURL((url) => url.searchParams.get("panel") === panel);
}
async function uploadOriginal(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
) {
  if (
    !new URL(page.url()).searchParams.has("panel") ||
    new URL(page.url()).searchParams.get("panel") !== "brokers"
  )
    await monthPanel(page, "brokers");
  const uploaded = page.waitForResponse(
    (r) => r.url().endsWith("/api/broker-months/intakes") && r.request().method() === "POST",
  );
  await page.getByLabel("XML-файлы", { exact: true }).setInputFiles(file);
  const ack = await (await uploaded).json();
  const review = page.getByRole("button", {
    name: `Открыть разбор загрузки #${ack.intake_id}`,
    exact: true,
  });
  await expect(review).toBeEnabled();
  await review.click();
  const changeSource = page.getByRole("button", { name: "Открыть выписку", exact: true });
  if (await changeSource.isVisible()) await changeSource.click();
  await page.getByRole("button", { name: "Проверить изменения", exact: true }).click();
}
function expectFinancialInventoryUnchanged(
  actual: { table_digests: Record<string, string> },
  before: { table_digests: Record<string, string> },
) {
  for (const [name, digest] of Object.entries(before.table_digests)) {
    if (!name.startsWith("source_intake_") && name !== "source_return_proof_dependencies")
      expect(actual.table_digests[name], name).toBe(digest);
  }
}
async function showSourceReview(page: Page) {
  const summary = page.getByText("Исправления и сохранение месяца", { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
}
async function selectSourceAccount(page: Page, value: string) {
  await page.getByLabel("Счёт источника месяца", { exact: true }).selectOption(value);
  const confirm = page.getByRole("button", { name: "Сменить счёт", exact: true });
  if (await confirm.isVisible()) await confirm.click();
}
async function reloadWorkspace(page: Page) {
  await page.reload();
  if (new URL(page.url()).searchParams.get("panel") === "brokers") {
    await showSourceReview(page);
  }
}
test.beforeEach(async ({ page }) => {
  page.on("dialog", (dialog) =>
    dialog.type() === "beforeunload" ? dialog.accept() : dialog.dismiss(),
  );
});

test("October primary entry exposes saved sources and historical stock/bond quantity without inventing monthly return", async ({
  page,
  request,
}, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const forbidden: string[] = [];
  const previews: unknown[] = [];
  page.on("request", (sent) => {
    const path = new URL(sent.url()).pathname;
    if (sent.method() === "POST" && /\/(apply|close|reopen|finance-link)$/.test(path))
      forbidden.push(path);
    if (sent.method() === "POST" && path.endsWith("/payout-preview"))
      previews.push(sent.postDataJSON());
  });
  await page.goto("/v2/data/months");
  await page.getByRole("button", { name: "Создать другой период" }).click();
  const form = page.getByRole("region", { name: "Создание месяца" });
  await form.getByLabel("Целевой год").fill("2035");
  await form.getByLabel("Целевой месяц").selectOption("10");
  await form.getByRole("button", { name: "Создать месяц", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Черновик Октябрь 2035 подтверждён" }),
  ).toBeVisible({ timeout: 15000 });
  const month = (await (await request.get("/api/months")).json()).find(
    (row: { year: number; month: number }) => row.year === 2035 && row.month === 10,
  );
  const row = page.getByText("Октябрь 2035", { exact: true }).locator("xpath=ancestor::li");
  await row.getByRole("button", { name: /Действия месяца/ }).click();
  await expect(page.getByRole("menuitem", { name: "Редактор", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await row.getByRole("link", { name: "Открыть месяц", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/v2/close\\?month=${month.id}$`));
  await monthPanel(page, "brokers");
  const sources = page.getByRole("region", { name: "Брокерские выписки", exact: true });
  await expect(sources.getByRole("heading", { name: "Брокерские выписки" })).toBeVisible();
  await expect(page.getByLabel("Оригинальный XML MyBroker", { exact: true })).toBeHidden();
  await expect(sources.getByText(/Для выбранного счёта выписок этого периода нет/)).toBeVisible();
  const manual = async () =>
    Promise.all(
      ["incomes", "deposits", "positions", "debts", "comments"].map(async (name) =>
        (await request.get(`/api/${name}?month_id=${month.id}`)).json(),
      ),
    );
  const before = await manual();
  const files = await Promise.all(
    ["a", "b"].map(async (suffix, index) => ({
      name: `Брокерский 711350${index + 1} (01.09.35-30.09.35).xml`,
      mimeType: "application/xml",
      buffer: await (
        await request.get(`/api/synthetic-broker-source/month-entry-${suffix}`)
      ).body(),
    })),
  );
  await sources.getByLabel("XML-файлы").setInputFiles(files);
  for (const file of files)
    await expect(sources.getByText(`${file.name}: Сохранен`, { exact: true })).toBeVisible();
  const picker = sources.getByLabel("Счёт источника месяца");
  await selectSourceAccount(page, "7113501");
  await expect(
    page
      .getByRole("region", { name: "Предварительная доходность месяца" })
      .getByText(/нет доказанных границ этого месяца/),
  ).toContainText("2035-10-31");
  await expect(sources.getByRole("region", { name: "Состояние источников месяца" })).toContainText(
    "Полных месячных оригиналов: 0",
  );
  const instruments = page.getByRole("region", { name: "Бумаги и выплаты" });
  await expect(instruments.getByText("RU000A000000 · Акция")).toBeVisible();
  await expect(instruments.getByText("RU000A000001 · Облигация")).toBeVisible();
  const dates = instruments.getByLabel("Сохранённая дата количества");
  await dates.selectOption("2035-09-30");
  await expect(instruments.getByText(/Наблюдаемое количество: 10 на 2035-09-30/)).toBeVisible();
  expect(previews).toHaveLength(0);
  await instruments
    .getByRole("button", { name: "Запросить предварительные выплаты T-Invest" })
    .click();
  await expect(
    instruments.getByRole("heading", { name: /Фактические строки источника/ }),
  ).toBeVisible();
  await expect(
    instruments.getByRole("heading", { name: "Возможно уже выплачено (possible_paid)" }),
  ).toBeVisible();
  await expect(
    instruments.getByRole("heading", { name: "Будущие кандидаты (future)" }),
  ).toBeVisible();
  await expect(instruments.getByText(/^Источник:.*количество: 10 на 2035-09-30/)).toBeVisible();
  await selectSourceAccount(page, "7113502");
  await dates.selectOption("2035-09-30");
  await expect(instruments.getByText(/Наблюдаемое количество: 25 на 2035-09-30/)).toBeVisible();
  await page.goBack();
  await expect(picker).toHaveValue("7113502");
  await page.goBack();
  await expect(picker).toHaveValue("7113501");
  await reloadWorkspace(page);
  await expect(picker).toHaveValue("7113501");
  await expect(dates).toHaveValue("2035-09-30");
  await expect(
    instruments.getByRole("heading", { name: /Фактические строки источника/ }),
  ).toHaveCount(0);
  await instruments.getByRole("button", { name: "Synthetic entry bond", exact: true }).click();
  // The old stock's date control must retire before choosing the bond's date.
  // Wait for the new ISIN panel, not a timeout or retry of a stale event.
  await expect(
    instruments.getByRole("region", { name: "Предварительные выплаты RU000A000001" }),
  ).toBeVisible();
  await dates.selectOption("2035-09-30");
  await expect(instruments.getByText(/Наблюдаемое количество: 2 на 2035-09-30/)).toBeVisible();
  await expect(instruments.getByText(/не заменяет закрывающий EOD 2035-10-31/)).toBeVisible();
  expect(await manual()).toEqual(before);
  expect(forbidden).toEqual([]);
  expect(previews).toHaveLength(1);
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await sources.screenshot({ path: info.outputPath("october-entry-source-status-1280-125.png") });
});

test("statement returns show native EOD facts, NKD caveat, exact export and stale/null account isolation on desktop", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const accounts = await (await request.get("/api/accounts")).json();
  const account = accounts.find((a: { name: string }) => a.name === "Synthetic statement broker");
  const empty = accounts.find(
    (a: { name: string }) => a.name === "Synthetic empty statement broker",
  );
  const params = `account_id=${account.id}&request_id=synthetic-statement-return`;
  const value = await (await request.get(`/api/broker-statement-returns?${params}`)).json();
  expect(value.status).toBe("indicative");
  expect(value.bond_nkd_basis).toBe("unknown");
  await page.goto("/v2/capital/statement-return");
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption(String(account.id));
  await page.getByLabel("Принятая выписка").selectOption("synthetic-statement-return");
  await expect(page.getByText("2,80%", { exact: true })).toBeVisible();
  await expect(
    page.getByText("По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"),
  ).toBeVisible();
  await expect(
    page.getByText("Доходность за фактический период; не приведена к году"),
  ).toBeVisible();
  await expect(page.getByText("Подтверждено отсутствие пересечений за период.")).toBeVisible();
  const exportLink = page.getByRole("link", { name: /Экспорт результата/ });
  const href = await exportLink.getAttribute("href");
  if (!href) throw new Error("Statement export link missing");
  const exported = await (await request.get(href)).json();
  expect(exported).toEqual(value);
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("statement-return-indicative-1280-125.png"),
    fullPage: true,
  });
  // Withdraw only synthetic coverage, then verify viewed export cannot keep its rate.
  const coverages = await (
    await request.get(`/api/cash-boundary-coverages?account_id=${account.id}`)
  ).json();
  const coverage = coverages[0];
  const intent = {
    operation: "revoke",
    coverage_id: coverage.id,
    expected_revision: value.cash_coverage_revision_id ? 1 : 0,
    reason_code: "attestation_withdrawn",
  };
  const plan = await (
    await request.post("/api/cash-boundary-coverages/preview", { data: intent })
  ).json();
  const revoked = await request.post("/api/cash-boundary-coverages/apply", {
    data: {
      ...intent,
      request_id: "synthetic-statement-revoke",
      confirmation_digest: plan.confirmation_digest,
    },
  });
  expect(revoked.ok()).toBe(true);
  const stale = await (await request.get(href)).json();
  expect(stale.rate_fraction).toBeNull();
  expect(stale.reason_codes).toContain("statement_preview_stale");
  await page.getByRole("button", { name: "Обновить результат" }).click();
  await expect(page.getByText("Недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText(/Не подтверждён полный список датированных/)).toBeVisible();
  await expect(page.getByText("10 280,00 ₽").first()).toBeVisible();
  await page.screenshot({
    path: info.outputPath("statement-return-unavailable-1280-125.png"),
    fullPage: true,
  });
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption(String(empty.id));
  await expect(page.getByText("Для этого счёта нет принятой выписки с оценками.")).toBeVisible();
  await expect(page.getByText("Недоступна", { exact: true })).toHaveCount(0);
  await expect(exportLink).toHaveCount(0);
  await page.getByLabel("Брокерский счёт", { exact: true }).focus();
  await expect(page.getByLabel("Брокерский счёт", { exact: true })).toBeFocused();
});

test("exact structural exceptions permit reviewed incomplete DRAFT and GET, while server Close stays blocked", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const xml = await (await request.get("/api/synthetic-broker-source/structure")).body();
  await page.goto("/v2/close?month=6&step=final_review_close");
  await uploadOriginal(page, {
    name: "Брокерский 7654321 (01.06.30-30.06.30).xml",
    mimeType: "application/xml",
    buffer: xml,
  });
  const response = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("3");
  const preview = await (await response).json();
  expect(preview).toMatchObject({
    can_apply: true,
    bookkeeping_ready: false,
    conflicts: [],
    exact_return_ready: false,
  });
  expect(preview.exceptions).toContain("unparsed_source_rows");
  expect(preview.identity.evidence.draft_structure.financial_authority).toBe("none");
  const apply = page.getByRole("button", {
    name: "Сохранить данные месяца",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  await expect(page.getByText(/Можно сохранить неполный source-DRAFT/)).toBeVisible();
  const aliases = page.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ });
  if (await aliases.count()) await aliases.check();
  await expect(apply).toBeEnabled();
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("incomplete-structure-preview-1280-125.png"),
    fullPage: true,
  });
  await apply.click();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  const batches = await (await request.get("/api/broker-months?reporting_month_id=6")).json();
  expect(batches).toHaveLength(1);
  const saved = await (await request.get(`/api/broker-months/${batches[0].request_id}`)).json();
  expect(saved).toMatchObject({
    status: "draft",
    bookkeeping_ready: false,
    exact_return_ready: false,
  });
  expect(saved.exceptions).toContain("unparsed_source_rows");
  expect(saved.accepted.document.syntax_blockers).toContain("unparsed_source_rows");
  await monthPanel(page, "close");
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeDisabled();
  expect((await request.post("/api/months/6/close")).status()).toBe(422);
  await reloadWorkspace(page);
  await monthPanel(page, "brokers");
  await showSourceReview(page);
  await expect(page.getByText(/Черновик неполный; Close заблокирован/)).toBeVisible();
  await page.screenshot({
    path: info.outputPath("incomplete-structure-get-1280.png"),
    fullPage: true,
  });
});

test("source-first original → reviewed atomic DRAFT → GET → global Close; partial Money stays blocked", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let writes = 0;
  let reads = 0;
  page.on("request", (sent) => {
    if (sent.url().includes("/api/broker-months/apply") && sent.method() === "POST") writes += 1;
    if (/\/api\/broker-months\/[A-Za-z0-9_-]+$/.test(sent.url()) && sent.method() === "GET")
      reads += 1;
  });
  const xml = await (await request.get("/api/synthetic-broker-source/complete")).body();
  const filename = "Брокерский 1234567 (01.01.30-31.01.30).xml";
  await page.goto("/v2/close?month=1&step=final_review_close");
  await uploadOriginal(page, { name: filename, mimeType: "application/xml", buffer: xml });
  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/broker-months/preview"),
  );
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("1");
  const preview = await (await previewResponse).json();
  expect(preview.account_bindings).toHaveLength(3);
  await page.getByText("Полный состав источника и привязки", { exact: true }).click();
  const aliases = page.getByRole("table", { name: "Привязки исходных счетов" });
  for (const identity of ["1234567", "ROW-A", "ROW-B", "filename_account", "acc_code"])
    await expect(aliases).toContainText(identity);
  await expect(page.getByRole("table", { name: "Позиции по исходному отчёту" })).toContainText(
    "RU000A000001",
  );
  await expect(page.getByText(/Общая оценка источника, включая отдельный RUB cash/)).toContainText(
    "2 400,01",
  );
  const apply = page.getByRole("button", {
    name: "Сохранить данные месяца",
    exact: true,
  });
  await expect(apply).toBeDisabled();
  expect(writes).toBe(0);
  const bindingReview = page.getByRole("checkbox", {
    name: /Я подтверждаю, что все новые aliases/,
  });
  await bindingReview.focus();
  await page.keyboard.press("Space");
  await expect(bindingReview).toBeChecked();
  await expect(apply).toBeEnabled();
  await page.screenshot({ path: info.outputPath("preview-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await expect(aliases).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("alias-preview-1280-125-percent.png"),
    fullPage: true,
  });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1";
  });
  await apply.click();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  expect(writes).toBe(1);
  expect(reads).toBe(1);
  const batches = await (await request.get("/api/broker-months?reporting_month_id=1")).json();
  expect(batches).toHaveLength(1);
  const saved = batches[0];
  expect(saved).toMatchObject({
    bookkeeping_ready: true,
    coverage_state: "unknown",
    exact_return_ready: false,
  });
  expect(saved.accepted.position_ids).toHaveLength(2);
  expect(saved.accepted.trade_ids).toHaveLength(1);
  const workflow = await (await request.get("/api/months/1/close-workflow")).json();
  expect(workflow.readiness.can_close).toBe(true);
  expect(JSON.stringify(workflow.readiness)).toContain("active_account_snapshot_missing");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: info.outputPath("draft-1280.png"), fullPage: true });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath("draft-125-percent.png"), fullPage: true });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1";
  });
  const forecast = page.getByRole("button", {
    name: "Получить и сохранить прогнозы Т-Инвест",
    exact: true,
  });
  await expect(forecast).toBeEnabled();
  await forecast.click();
  await expect(page.getByText(/Позиций обновлено: 2; без изменений: 0/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Ожидаемые купоны и дивиденды" })).toContainText(
    /25\s*₽/,
  );
  await expect(
    page.getByRole("table", { name: "Возврат номинала · отдельно от дохода" }),
  ).toContainText(/10\s000\s*₽/);
  const forecasts = await (
    await request.get("/api/payouts/calendar?month_id=1&forecast_version=v1")
  ).json();
  expect(forecasts.flatMap((period: { items: unknown[] }) => period.items)).toHaveLength(3);
  const savedForecasts = await (await request.get("/api/synthetic-broker-inventory")).json();
  await page.screenshot({ path: info.outputPath("draft-forecasts-1280.png"), fullPage: true });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("draft-forecasts-1280-125-percent.png"),
    fullPage: true,
  });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1";
  });
  await forecast.click();
  await expect(page.getByText(/Позиций обновлено: 0; без изменений: 2/)).toBeVisible();
  expect(
    (await (await request.get("/api/synthetic-broker-inventory")).json()).table_digests,
  ).toEqual(savedForecasts.table_digests);
  const providerCalls = await (await request.get("/api/synthetic-draft-provider-calls")).json();
  await reloadWorkspace(page);
  await expect(page.getByRole("table", { name: "Ожидаемые купоны и дивиденды" })).toContainText(
    /25\s*₽/,
  );
  expect(await (await request.get("/api/synthetic-draft-provider-calls")).json()).toEqual(
    providerCalls,
  );
  await monthPanel(page, "close");
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  expect((await (await request.get(`/api/broker-months/${saved.request_id}`)).json()).status).toBe(
    "closed",
  );
  const replay = await request.post("/api/broker-months/apply", {
    multipart: {
      file: { name: filename, mimeType: "application/xml", buffer: xml },
      confirmation: JSON.stringify({
        reporting_month_id: 1,
        account_id: 1,
        confirmation_digest: saved.confirmation_digest,
        request_id: saved.request_id,
        reviewed_account_bindings: preview.account_bindings,
      }),
    },
  });
  expect(replay.status()).toBe(200);
  expect((await replay.json()).duplicate).toBe(true);
  await reloadWorkspace(page);
  await monthPanel(page, "brokers");
  await expect(page.getByText(/Сохранённые источники доступны для чтения/)).toBeVisible();
  await expect(page.getByLabel("Оригинальный XML MyBroker")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("closed-1280.png"), fullPage: true });

  await page.goto("/v2/close?month=2&step=final_review_close");
  const partial = await (await request.get("/api/synthetic-broker-source/partial")).body();
  await uploadOriginal(page, {
    name: "Брокерский 1234567 (01.02.30-28.02.30).xml",
    mimeType: "application/xml",
    buffer: partial,
  });
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("1");
  await page.getByText("Полный состав источника и привязки", { exact: true }).click();
  await expect(page.getByRole("table", { name: "Привязки исходных счетов" })).toContainText(
    "Существующая",
  );
  await expect(
    page.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }),
  ).toHaveCount(0);
  await expect(page.getByText(/Можно сохранить неполный source-DRAFT/)).toBeVisible();
  await page.getByText("Все денежные строки и секции источника").click();
  await expect(page.getByText("Не разобрано — требуется доказательство")).toBeVisible();
  await page
    .getByRole("button", {
      name: "Сохранить данные месяца",
      exact: true,
    })
    .click();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  const blocked = await (await request.get("/api/months/2/close-workflow")).json();
  expect(blocked.readiness.can_close).toBe(false);
  expect(JSON.stringify(blocked.readiness)).toContain("money_semantics_unsupported");
  await monthPanel(page, "close");
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeDisabled();
  expect((await request.post("/api/months/2/close")).status()).toBe(422);
  await page.screenshot({ path: info.outputPath("partial-money-1280.png"), fullPage: true });
});

test("desktop Money accepts atomic batches and reload retains earlier coupons/H2 with NULL tax and deferred NKD", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const xml = await (await request.get("/api/synthetic-broker-source/money")).body();
  const filename = "Брокерский 1234567 (01.03.30-31.03.30).xml";
  const scope = { reporting_month_id: 3, account_id: 1 };
  const original = { name: filename, mimeType: "application/xml", buffer: xml };
  const preview = await (
    await request.post("/api/broker-months/preview", {
      multipart: { file: original, intent: JSON.stringify(scope) },
    })
  ).json();
  const baseResponse = await request.post("/api/broker-months/apply", {
    multipart: {
      file: original,
      confirmation: JSON.stringify({
        ...scope,
        request_id: "desktop-money-base",
        confirmation_digest: preview.confirmation_digest,
        reviewed_account_bindings: preview.account_bindings,
      }),
    },
  });
  expect(baseResponse.ok()).toBe(true);
  let writes = 0;
  let gets = 0;
  page.on("request", (sent) => {
    if (sent.url().endsWith("/api/broker-months/apply") && sent.method() === "POST") writes++;
    if (/\/api\/broker-months\/[^/?]+$/.test(sent.url()) && sent.method() === "GET") gets++;
  });
  await page.goto("/v2/close?month=3&step=final_review_close");
  await monthPanel(page, "brokers");
  await showSourceReview(page);
  await page.getByText("Принять Money в этот черновик").click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const inventory = page.getByRole("table", { name: "Все наблюдения Money" });
  await expect(inventory).toContainText("trade_paid_nkd_candidate");
  const choose = inventory.getByRole("checkbox");
  await choose.nth(0).check();
  await choose.nth(2).check();
  await page.getByLabel("Подтверждённая облигация для строки 2").selectOption("2");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const confirm = page.getByRole("checkbox", {
    name: /Я подтверждаю перечисленные конкретные решения Money/,
  });
  await confirm.focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  const stored = page.getByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  await expect(stored).toContainText("50 000");
  await expect(stored).toContainText("Неизвестно");
  expect(writes).toBe(1);
  expect(gets).toBe(1);
  const firstMoney = await (await request.get("/api/broker-months/desktop-money-base")).json();
  const firstMoneyId = firstMoney.money_acceptance.request_id;
  await expect(stored.getByRole("row")).toHaveCount(3);
  await reloadWorkspace(page);
  await expect(stored.getByRole("row")).toHaveCount(3);
  await page.getByText("Принять Money в этот черновик").click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await inventory.getByRole("checkbox").nth(1).check();
  await page.getByLabel("Подтверждённая облигация для строки 3").selectOption("2");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await confirm.check();
  const beforeSecondGets = gets;
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  await expect(stored.getByRole("row")).toHaveCount(4);
  expect(writes).toBe(2);
  expect(gets).toBe(beforeSecondGets + 1);
  await reloadWorkspace(page);
  await expect(stored.getByRole("row")).toHaveCount(4);
  await expect(stored).toContainText("50 000");
  await expect(stored).toContainText("1 000");
  await expect(stored).toContainText("2 000");
  const read = await (await request.get("/api/broker-months/desktop-money-base")).json();
  expect(read.money_acceptance.targets).toHaveLength(1);
  expect(read.money_acceptance.current_targets).toHaveLength(3);
  expect(
    read.money_acceptance.current_targets.every((t: { effective: boolean }) => t.effective),
  ).toBe(true);
  expect(read.exceptions).toContain("money_semantics_unsupported");
  const pdf = await (await request.get("/api/synthetic-broker-source/money-pdf")).body();
  const pdfForm = {
    document: { name: "synthetic-money.pdf", mimeType: "application/pdf", buffer: pdf },
    account_mappings: JSON.stringify([
      { hermes_account_id: 1, provider_account_ref: "SYN-DEPO-001" },
    ]),
  };
  const preparation = await (
    await request.post("/api/statement-import/prepare", { multipart: pdfForm })
  ).json();
  const pdfRow = preparation.rows[0];
  const coupon = read.money_acceptance.current_targets.find(
    (t: { role: string; facts: { net_amount_kopecks: string } }) =>
      t.role === "coupon" && t.facts.net_amount_kopecks === "100000",
  );
  const linkedPdf = await (
    await request.post("/api/statement-import/apply", {
      multipart: {
        ...pdfForm,
        expected_document_sha256: preparation.document_sha256,
        selections: JSON.stringify([
          {
            natural_identity: pdfRow.natural_identity,
            material_fingerprint: pdfRow.material_fingerprint,
            expected_hermes_account_id: 1,
            expected_hermes_instrument_id: 2,
            action: "link_existing",
            existing_cash_flow_id: coupon.target_id,
            expected_candidate_ids: pdfRow.expected_candidate_ids,
          },
        ]),
      },
    })
  ).json();
  expect(linkedPdf.success).toBe(true);
  expect(linkedPdf.items[0].investment_cash_flow_id).toBe(coupon.target_id);
  const afterPdf = await (await request.get(`/api/broker-months/${firstMoneyId}`)).json();
  expect(afterPdf.targets.every((t: { effective: boolean }) => t.effective)).toBe(true);
  expect(afterPdf.exceptions).toEqual(read.money_acceptance.exceptions);
  expect(afterPdf.current_targets).toHaveLength(3);
  expect(afterPdf.targets[0].components.tax_amount_kopecks).toBeNull();
  await reloadWorkspace(page);
  await expect(stored.getByRole("row")).toHaveCount(4);
  await expect(stored).toContainText("Неизвестно");
  await expect(stored).not.toContainText("Требуется сверка");
  const rejected = await request.post("/api/months/3/close");
  expect(rejected.status()).toBe(422);
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await expect(stored).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({ path: info.outputPath("synthetic-money-desktop.png"), fullPage: true });
});

test("desktop paid NKD uses independently reviewed native basis, one revision and 52864.50 cash through Close", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const xml = await (await request.get("/api/synthetic-broker-source/trade-money")).body();
  const original = {
    name: "Брокерский 1234567 (01.04.30-30.04.30).xml",
    mimeType: "application/xml",
    buffer: xml,
  };
  const scope = { reporting_month_id: 4, account_id: 1 };
  const preview = await (
    await request.post("/api/broker-months/preview", {
      multipart: { file: original, intent: JSON.stringify(scope) },
    })
  ).json();
  const baseResponse = await request.post("/api/broker-months/apply", {
    multipart: {
      file: original,
      confirmation: JSON.stringify({
        ...scope,
        request_id: "desktop-trade-base",
        confirmation_digest: preview.confirmation_digest,
        reviewed_account_bindings: preview.account_bindings,
      }),
    },
  });
  expect(baseResponse.ok()).toBe(true);
  const base = await baseResponse.json();
  await page.goto("/v2/close?month=4&step=final_review_close");
  await monthPanel(page, "brokers");
  await showSourceReview(page);
  await page.getByText("Принять Money в этот черновик").click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const inventory = page.getByRole("table", { name: "Все наблюдения Money" });
  await expect(inventory.getByRole("checkbox")).toHaveCount(4);
  for (const checkbox of await inventory.getByRole("checkbox").all()) await checkbox.check();
  await page.getByLabel("Подтверждённая облигация для строки 2").selectOption("2");
  await page.getByLabel("Подтверждённая облигация для строки 3").selectOption("2");
  await page
    .getByLabel("Точное исполнение покупки для НКД строки 5")
    .selectOption(String(base.accepted.trade_ids[0]));
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const confirm = page.getByRole("checkbox", {
    name: /Я подтверждаю перечисленные конкретные решения Money/,
  });
  await expect(confirm).toBeDisabled();
  await expect(page.getByText(/Равенство сумм не доказывает basis/)).toBeVisible();
  await page
    .getByLabel("Независимо доказанное включение НКД в native сумму сделки")
    .selectOption("includes_paid_nkd");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("paid-nkd-review-1280-125-percent.png"),
    fullPage: true,
  });
  await confirm.focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  const stored = page.getByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  await expect(stored.getByRole("row")).toHaveCount(5, { timeout: 30000 });
  await expect(stored).toContainText("НКД и комиссия покупки");
  await expect(stored).toContainText("включает НКД");
  const read = await (await request.get("/api/broker-months/desktop-trade-base")).json();
  expect(read.bookkeeping_ready).toBe(true);
  expect(read.accepted.cash_control_difference_kopecks).toBe(0);
  expect(read.accepted.document.rub_money[0].ending_amount).toBe("52864.5");
  expect(
    read.money_acceptance.current_targets.filter((t: { role: string }) => t.role === "trade"),
  ).toHaveLength(1);
  const trade = await (
    await request.get(`/api/executed-trades/${base.accepted.trade_ids[0]}`)
  ).json();
  expect(trade.revision).toBe(2);
  expect(
    trade.evidence.cash_legs
      .map((leg: { amount_minor: number }) => leg.amount_minor)
      .reduce((a: number, b: number) => a + b, 0),
  ).toBe(1013550);
  await reloadWorkspace(page);
  await expect(stored.getByRole("row")).toHaveCount(5, { timeout: 30000 });
  expect((await (await request.get("/api/months/4/close-readiness")).json()).can_close).toBe(true);
  await page.screenshot({ path: info.outputPath("paid-nkd-get-1280.png"), fullPage: true });
  await monthPanel(page, "close");
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  const closed = page.waitForResponse(
    (response) => response.url().endsWith("/api/months/4/close"),
    { timeout: 30000 },
  );
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect((await closed).status()).toBe(200);
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible({
    timeout: 30000,
  });
});

test("stock separate fee explicit independent basis Preview Apply GET reload Close", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const xml = await (await request.get("/api/synthetic-broker-source/stock-fee")).body();
  const original = {
    name: "Брокерский 1234567 (01.05.30-31.05.30).xml",
    mimeType: "application/xml",
    buffer: xml,
  };
  const scope = { reporting_month_id: 5, account_id: 1 };
  const preview = await (
    await request.post("/api/broker-months/preview", {
      multipart: { file: original, intent: JSON.stringify(scope) },
    })
  ).json();
  const applied = await request.post("/api/broker-months/apply", {
    multipart: {
      file: original,
      confirmation: JSON.stringify({
        ...scope,
        request_id: "desktop-stock-base",
        confirmation_digest: preview.confirmation_digest,
        reviewed_account_bindings: preview.account_bindings,
      }),
    },
  });
  expect(applied.ok()).toBe(true);
  const base = await applied.json();
  await page.goto("/v2/close?month=5&step=final_review_close");
  await monthPanel(page, "brokers");
  await showSourceReview(page);
  await page.getByText("Принять Money в этот черновик").click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await page.getByRole("checkbox", { name: "Комиссия покупки акции" }).check();
  await page
    .getByLabel("Точное исполнение покупки акции для строки 2")
    .selectOption(String(base.accepted.trade_ids[0]));
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const confirm = page.getByRole("checkbox", {
    name: /Я подтверждаю перечисленные конкретные решения Money/,
  });
  await expect(confirm).toBeDisabled();
  await expect(confirm).not.toBeChecked();
  await expect(page.getByText(/Расчёт S/)).toContainText("100");
  await expect(page.getByText(/Расчёт S/)).toContainText("1,25");
  await page
    .getByLabel("Независимое основание суммы без комиссии")
    .fill("synthetic-independent-source-rule-v1");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await expect(confirm).not.toBeChecked();
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("stock-fee-review-1280-125-percent.png"),
    fullPage: true,
  });
  await confirm.focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  const stored = page.getByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  await expect(stored).toContainText("Комиссия покупки акции", { timeout: 30000 });
  await expect(stored).toContainText("synthetic-independent-source-rule-v1");
  await expect(stored).not.toContainText("НКД");
  const read = await (await request.get("/api/broker-months/desktop-stock-base")).json();
  expect(read.bookkeeping_ready).toBe(true);
  expect(read.accepted.cash_control_difference_kopecks).toBe(0);
  expect(read.accepted.document.rub_money[0].ending_amount).toBe("898.75");
  const trade = await (
    await request.get(`/api/executed-trades/${base.accepted.trade_ids[0]}`)
  ).json();
  expect(trade.revision).toBe(2);
  expect(trade.evidence.cash_legs.map((leg: { role: string }) => leg.role).sort()).toEqual([
    "commission",
    "settlement",
  ]);
  expect(trade.evidence.cash_reconciliation).not.toHaveProperty("nkd_leg");
  await reloadWorkspace(page);
  await expect(stored).toContainText("synthetic-independent-source-rule-v1", { timeout: 30000 });
  expect(
    await stored
      .locator("tbody td")
      .nth(2)
      .evaluate((cell) => cell.scrollWidth <= cell.clientWidth),
  ).toBe(true);
  await stored.screenshot({ path: info.outputPath("stock-fee-stored-evidence.png") });
  expect((await (await request.get("/api/months/5/close-readiness")).json()).can_close).toBe(true);
  await page.screenshot({ path: info.outputPath("stock-fee-reload-1280.png"), fullPage: true });
  await monthPanel(page, "close");
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  const closed = page.waitForResponse((response) => response.url().endsWith("/api/months/5/close"));
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect((await closed).status()).toBe(200);
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible({
    timeout: 30000,
  });
});

test("exceptions-first known account needs only original plus explicit source-DRAFT Save, with zero writes and exact replay", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const xml = await (await request.get("/api/synthetic-broker-source/original-first")).body();
  const filename = "Брокерский 8480000 (01.08.30-31.08.30).xml";
  const file = { name: filename, mimeType: "application/xml", buffer: xml };
  const before = await (await request.get("/api/synthetic-broker-inventory")).json();
  let applies = 0;
  let reads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/broker-months/apply")) applies++;
    if (/\/api\/broker-months\/[A-Za-z0-9_-]+$/.test(r.url()) && r.method() === "GET") reads++;
  });
  await page.goto("/v2/close?month=8&step=final_review_close");
  await uploadOriginal(page, file);
  await expect(page.getByText(/Период XML не совпадает с открытым DRAFT/)).toBeVisible();
  await expect(page.getByLabel("Брокерский счёт", { exact: true })).toHaveValue("");
  await page.screenshot({
    path: info.outputPath("original-first-wrong-month-1440.png"),
    fullPage: true,
  });
  await page.goto("/v2/close?month=7&step=final_review_close");
  const discovery = page.waitForResponse((r) =>
    r.url().endsWith("/api/mybroker-preflight/preview"),
  );
  const ordinary = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await uploadOriginal(page, file);
  const preflight = await (await discovery).json();
  const auto = await (await ordinary).json();
  expect(preflight.documents[0].mappings.state).toBe("blocked"); // compatible instruments need new mappings
  expect(auto).toMatchObject({
    account_id: 4,
    reporting_month_id: 7,
    can_apply: true,
    bookkeeping_ready: false,
    account_bindings: [],
  });
  await expect(page.getByLabel("Брокерский счёт", { exact: true })).toHaveValue("4");
  const manual = await (
    await request.post("/api/broker-months/preview", {
      multipart: {
        file: { name: filename, mimeType: "application/xml", buffer: xml },
        intent: JSON.stringify({ account_id: 4, reporting_month_id: 7 }),
      },
    })
  ).json();
  expect(auto).toEqual(manual);
  expectFinancialInventoryUnchanged(
    await (await request.get("/api/synthetic-broker-inventory")).json(),
    before,
  );
  const save = page.getByRole("button", {
    name: "Сохранить данные месяца",
    exact: true,
  });
  await expect(save).toBeEnabled();
  const summary = page.getByRole("region", { name: "Сводка исходного DRAFT" });
  await expect(summary.getByText("Денежные операции не разобраны", { exact: true })).toBeVisible();
  await expect(summary).toContainText("Synthetic original-first broker (#4)");
  await expect(summary).toContainText("01.08.2030 — 31.08.2030");
  await expect(
    summary.getByText("Общая оценка источника, включая cash").locator(".."),
  ).toContainText("2 400,01");
  await expect(page.getByRole("table", { name: "Позиции по исходному отчёту" })).toHaveCount(0);
  await expect(
    page.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }),
  ).toHaveCount(0);
  await page.screenshot({
    path: info.outputPath("source-draft-summary-1440.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await expect(page.getByRole("checkbox", { name: /Я проверил весь счёт/ })).toHaveCount(0);
  await save.focus();
  await expect(save).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(applies).toBe(0);
  expectFinancialInventoryUnchanged(
    await (await request.get("/api/synthetic-broker-inventory")).json(),
    before,
  );
  await page.screenshot({
    path: info.outputPath("source-draft-single-confirm-1280-125.png"),
    fullPage: true,
  });
  let attempts = 0;
  await page.route("**/api/broker-months/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    attempts++;
    if (attempts === 1) return route.abort("timedout");
    if (attempts === 2)
      return route.fulfill({
        status: 404,
        json: { error: { code: "not_found", message: "Synthetic delayed GET", details: [] } },
      });
    if (attempts === 3) {
      const response = await route.fetch();
      const wrong = await response.json();
      wrong.accepted.cash_id++;
      return route.fulfill({ response, json: wrong });
    }
    return route.continue();
  });
  const appliedResponse = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/apply"));
  await page.keyboard.press("Enter");
  const applied = await (await appliedResponse).json();
  const retry = page.getByRole("button", { name: "Повторить чтение", exact: true });
  await expect(
    page.getByText(
      "Сохранение подтверждено сервером, независимое чтение не завершено — повторить чтение",
    ),
  ).toBeVisible();
  await expect(retry).toBeEnabled();
  await expect(page.getByRole("list", { name: "Выбранные оригиналы Money" })).toHaveCount(0);
  const afterPost = await (await request.get("/api/synthetic-broker-inventory")).json();
  for (let i = 0; i < 2; i++) {
    await retry.click();
    await expect(retry).toBeEnabled();
    await expect(
      page.getByText(/Сохранённый результат подтверждён независимым чтением/),
    ).toHaveCount(0);
    expect(applies).toBe(1);
    expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterPost);
  }
  await page.screenshot({
    path: info.outputPath("source-ack-get-only-recovery-1280-125.png"),
    fullPage: true,
  });
  await retry.click();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  expect(applies).toBe(1);
  expect(reads).toBe(4);
  const reread = await (await request.get(`/api/broker-months/${applied.request_id}`)).json();
  expect(reread.accepted).toEqual(applied.accepted);
  await page.unroute("**/api/broker-months/*");
  await page.getByText("Принять Money в этот черновик", { exact: true }).click();
  await expect(page.getByRole("list", { name: "Выбранные оригиналы Money" })).toContainText(
    filename,
  );
  const primaryPreview = page.waitForResponse((r) =>
    r.url().endsWith("/api/broker-months/preview"),
  );
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const primary = await (await primaryPreview).json();
  expect(primary.contract_version).toBe("broker_money_v1");
  expect(primary.sources).toHaveLength(1);
  // Real backend accepts only SHA-matching original bytes with the valid filename;
  // normalized JSON or a reconstructed File cannot satisfy this source union.
  expect(primary.sources[0].source.document_sha256).toBe(
    createHash("sha256").update(xml).digest("hex"),
  );
  expect(primary.sources[0].adapter).toBe("mybroker-money-candidates-v1");
  expect(primary.sources[0].original_required).not.toBe(true);
  expect(primary.blockers).not.toContain("overlapping_original_required");
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterPost);
  await page.screenshot({
    path: info.outputPath("retained-primary-money-1280-125.png"),
    fullPage: true,
  });
  const saved = await (await request.get("/api/broker-months?reporting_month_id=7")).json();
  expect(saved).toHaveLength(1);
  expect(saved[0]).toMatchObject({ account_id: 4, bookkeeping_ready: false });
  await page.screenshot({
    path: info.outputPath("source-draft-saved-1280-125.png"),
    fullPage: true,
  });
  // Same original + same reviewed intent/key is a zero-economic-write replay.
  const afterSave = await (await request.get("/api/synthetic-broker-inventory")).json();
  const replay = await request.post("/api/broker-months/apply", {
    multipart: {
      file: { name: filename, mimeType: "application/xml", buffer: xml },
      confirmation: JSON.stringify({
        reporting_month_id: 7,
        account_id: 4,
        confirmation_digest: auto.confirmation_digest,
        request_id: saved[0].request_id,
        reviewed_account_bindings: auto.account_bindings,
      }),
    },
  });
  expect(replay.ok()).toBe(true);
  expect((await replay.json()).duplicate).toBe(true);
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterSave);

  const altered = Buffer.from(
    xml.toString().replace('real_volume="1000.01"', 'real_volume="1001.01"'),
  );
  expect(altered.equals(xml)).toBe(false);
  const conflictResponse = page.waitForResponse((r) =>
    r.url().endsWith("/api/broker-months/preview"),
  );
  await uploadOriginal(page, { ...file, buffer: altered });
  const conflict = await (await conflictResponse).json();
  expect(conflict.can_apply).toBe(false);
  expect(conflict.conflicts).toContain("overlapping_endpoint_conflict");
  await expect(page.getByRole("region", { name: "Сводка исходного DRAFT" })).toContainText(
    "Пересекающиеся источники противоречат друг другу",
  );
  await expect(save).toBeDisabled();
  await page.screenshot({
    path: info.outputPath("source-draft-conflict-1280-125.png"),
    fullPage: true,
  });

  const currencyResponse = page.waitForResponse((r) =>
    r.url().endsWith("/api/broker-months/preview"),
  );
  await uploadOriginal(page, {
    ...file,
    buffer: Buffer.from(xml.toString().replaceAll("RU000A000848", "RU000A000777")),
  });
  const currency = await (await currencyResponse).json();
  expect(currency.can_apply).toBe(false);
  expect(currency.conflicts).toContain("instrument_currency_unproven");
  await expect(page.getByRole("region", { name: "Сводка исходного DRAFT" })).toContainText(
    "Валюта инструмента не подтверждена",
  );
  await expect(page.getByRole("region", { name: "Сводка исходного DRAFT" })).toContainText(
    "RUB автоматически не назначается",
  );
  await expect(save).toBeDisabled();
  await page.screenshot({
    path: info.outputPath("source-draft-unknown-currency-1280-125.png"),
    fullPage: true,
  });
  expect(applies).toBe(1);
  expectFinancialInventoryUnchanged(
    await (await request.get("/api/synthetic-broker-inventory")).json(),
    afterSave,
  );
});

test("lost source POST response reads old key first, exact replay is duplicate, and catalogue return retains File", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const xml = await (await request.get("/api/synthetic-broker-source/session")).body();
  const file = {
    name: "Брокерский 8480000 (01.10.30-31.10.30).xml",
    mimeType: "application/xml",
    buffer: xml,
  };
  await page.goto("/v2/close?month=9&step=final_review_close");
  await uploadOriginal(page, file);
  const save = page.getByRole("button", {
    name: "Сохранить данные месяца",
    exact: true,
  });
  await expect(save).toBeEnabled();
  // SPA navigation must keep the actual File; a full reload deliberately does not.
  await page.getByRole("link", { name: "Данные", exact: true }).click();
  await page.getByRole("button", { name: "Перейти без сохранения", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Источники и актуальность", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Справочники и сопоставления", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Справочники и сопоставления", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Источники и актуальность", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByText(`Оригинал в текущем сеансе: ${file.name}`)).toBeVisible();
  await expect(save).toHaveCount(0);

  const order: string[] = [];
  let id = "";
  let committedInventory: unknown;
  let posts = 0;
  let delayRead = true;
  await page.route("**/api/broker-months/*", async (route) => {
    const req = route.request();
    if (req.url().endsWith("/apply")) {
      order.push("POST");
      posts++;
      if (posts === 1) {
        const response = await route.fetch();
        expect(response.ok()).toBe(true);
        id = (await response.json()).request_id;
        committedInventory = await (await request.get("/api/synthetic-broker-inventory")).json();
        return route.abort("connectionreset");
      }
    } else if (req.method() === "GET" && id && req.url().endsWith(`/api/broker-months/${id}`)) {
      order.push(`GET:${req.url().split("/").at(-1)}`);
      if (delayRead) {
        delayRead = false;
        return route.fulfill({
          status: 404,
          json: { error: { code: "not_found", message: "Synthetic read lag", details: [] } },
        });
      }
    }
    return route.continue();
  });
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Проверить изменения", exact: true }).click();
  await expect(save).toBeEnabled();
  await save.click();
  const replay = page.getByRole("button", {
    name: "Повторить сохранение с прежним запросом",
    exact: true,
  });
  await expect(replay).toBeEnabled();
  expect(order.slice(0, 2)).toEqual(["POST", `GET:${id}`]);
  await expect(
    page.getByText(
      "Сохранение подтверждено сервером, независимое чтение не завершено — повторить чтение",
    ),
  ).toHaveCount(0);
  await page.screenshot({
    path: info.outputPath("source-lost-post-get-first-1440.png"),
    fullPage: true,
  });
  const response = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/apply"));
  // A URL/Back scope change cannot discard the uncertain original key or expose
  // it as a different account's actions. No POST recovery is offered while detached.
  await page.goBack();
  await expect(page.getByRole("alertdialog")).toContainText("Сохранение ещё не подтверждено");
  await page.getByRole("button", { name: "Вернуться к форме", exact: true }).click();
  expect(posts).toBe(1);
  await expect(replay).toBeEnabled();
  await replay.click();
  const duplicate = await (await response).json();
  expect(duplicate.duplicate).toBe(true);
  expect(duplicate.request_id).toBe(id);
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(
    committedInventory,
  );
  await page.unroute("**/api/broker-months/*");
  await page.getByText("Принять Money в этот черновик", { exact: true }).click();
  const selected = page.getByRole("list", { name: "Выбранные оригиналы Money" });
  await expect(selected).toContainText(file.name);
  // Register a second intersecting source using the existing S1 route. The
  // retained primary alone must not be mistaken for a complete Money union.
  const overlap = { ...file, buffer: Buffer.concat([xml, Buffer.from("\n")]) };
  const sourcePlan = await (
    await request.post("/api/mybroker-import/preview", { multipart: { file: overlap } })
  ).json();
  expect(sourcePlan.can_apply).toBe(true);
  const sourceApply = await request.post("/api/mybroker-import/apply", {
    multipart: {
      file: overlap,
      confirmation: JSON.stringify({
        confirmation_digest: sourcePlan.confirmation_digest,
        covered_from: sourcePlan.document.covered_from,
        covered_to: sourcePlan.document.covered_to,
        mappings: sourcePlan.mappings,
        skipped_isins: [],
        owner_reviewed: false,
        request_id: "desktop-session-overlap",
      }),
    },
  });
  expect(sourceApply.ok()).toBe(true);
  const afterOverlap = await (await request.get("/api/synthetic-broker-inventory")).json();
  const missingResponse = page.waitForResponse((r) =>
    r.url().endsWith("/api/broker-months/preview"),
  );
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const missing = await (await missingResponse).json();
  expect(missing.can_apply).toBe(false);
  expect(missing.blockers).toContain("overlapping_original_required");
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterOverlap);
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles({
    name: "invalid.xml",
    mimeType: "application/xml",
    buffer: Buffer.from("<invalid/>"),
  });
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await expect(page.getByRole("alert").last()).toBeVisible();
  await expect(selected).toContainText(file.name);
  await expect(selected).toContainText("invalid.xml");
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterOverlap);
  await page.getByRole("button", { name: "Убрать invalid.xml", exact: true }).click();
  await expect(selected).not.toContainText("invalid.xml");
  await page.screenshot({
    path: info.outputPath("money-supplemental-correction-1440.png"),
    fullPage: true,
  });
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(overlap);
  const union = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const forward = await (await union).json();
  expect(forward.blockers).not.toContain("overlapping_original_required");
  expect(forward.blockers).not.toContain("original_not_in_accepted_source_union");
  expect(forward.sources).toHaveLength(2);
  await page
    .getByRole("button", { name: `Убрать ${file.name}`, exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: `Убрать ${file.name}`, exact: true }).click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles([overlap, file]);
  const reversed = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const backward = await (await reversed).json();
  expect(backward.inventory).toEqual(forward.inventory);
  expect(backward.blockers).toEqual(forward.blockers);
  expect(backward.confirmation_digest).toBe(forward.confirmation_digest);
  expect(await (await request.get("/api/synthetic-broker-inventory")).json()).toEqual(afterOverlap);
  await page.screenshot({
    path: info.outputPath("money-overlap-both-orders-1440.png"),
    fullPage: true,
  });
  await reloadWorkspace(page);
  await page.getByText("Принять Money в этот черновик", { exact: true }).click();
  await expect(page.getByRole("list", { name: "Выбранные оригиналы Money" })).toBeEmpty();
});

test("source identity inbox keeps 12 ready and 1 pending until one opt-in, grouped decision and fresh atomic DRAFT/GET", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const months = await (await request.get("/api/months")).json();
  const month = months.find(
    (m: { year: number; month: number }) => m.year === 2031 && m.month === 1,
  );
  const xml = await (await request.get("/api/synthetic-broker-source/source-inbox")).body();
  const before = await (await request.get("/api/synthetic-broker-inventory")).json();
  let lookups = 0;
  let posts = 0;
  page.on("request", (req) => {
    if (req.url().endsWith("/public-identity-lookup")) {
      lookups++;
      expect(req.postDataJSON()).toEqual({ consent: true, isins: ["RU000A008813"] });
    }
    if (req.url().endsWith("/api/broker-months/apply")) posts++;
  });
  await page.goto(`/v2/close?month=${month.id}&step=final_review_close`);
  await uploadOriginal(page, {
    name: "Брокерский 8860000 (01.01.31-31.01.31).xml",
    mimeType: "application/xml",
    buffer: xml,
  });
  await expect(page.getByText(/MATCHED — 12; PENDING REVIEW — 1/)).toBeVisible();
  const save = page.getByRole("button", {
    name: "Сохранить данные месяца",
    exact: true,
  });
  await expect(save).toBeDisabled();
  expect(lookups).toBe(0);
  expectFinancialInventoryUnchanged(
    await (await request.get("/api/synthetic-broker-inventory")).json(),
    before,
  );
  await page.getByText("Все сопоставленные бумаги (12)").click();
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: /Synthetic inbox stock 11.*MATCHED/ })
      .first(),
  ).toBeVisible();
  const choice = page.getByLabel("Решение для RU000A008813");
  await choice.focus();
  await expect(choice).toBeFocused();
  await expect(choice.locator("option").filter({ hasText: "NULL-ISIN" })).toHaveAttribute(
    "disabled",
    "",
  );
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("source-inbox-pending-1440-125.png"),
    fullPage: true,
  });
  await page.getByRole("checkbox", { name: /Разрешаю автоматический поиск/ }).check();
  await expect(choice.locator("option").filter({ hasText: "Создать:" })).toHaveCount(1);
  const selected = await choice
    .locator("option")
    .filter({ hasText: "Создать:" })
    .getAttribute("value");
  if (!selected) throw new Error("Synthetic public option missing");
  await choice.selectOption(selected);
  const fresh = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await page.getByRole("button", { name: /Подтвердить решения и заново/ }).click();
  const ready = await (await fresh).json();
  expect(ready.can_apply).toBe(true);
  expect(ready.document.positions).toHaveLength(13);
  expect(ready.document.document_sha256).toBe(createHash("sha256").update(xml).digest("hex"));
  expect(posts).toBe(0);
  expect(lookups).toBe(1);
  await expect(save).toBeEnabled();
  await save.click();
  await expect(
    page.getByText(/Сохранённый результат подтверждён независимым чтением/),
  ).toBeVisible();
  const after = await (await request.get("/api/synthetic-broker-inventory")).json();
  expect(after.counts.position_snapshots - before.counts.position_snapshots).toBe(13);
  expect(after.counts.cash_balances - before.counts.cash_balances).toBe(1);
  expect(after.counts.investment_cash_flows).toBe(before.counts.investment_cash_flows);
  expect(posts).toBe(1);
  await page.screenshot({
    path: info.outputPath("source-inbox-draft-get-1440-125.png"),
    fullPage: true,
  });
});

test("durable full source observations survive reload and reviewed currency override without economic Apply", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const months = await (await request.get("/api/months")).json();
  const month = months.find(
    (m: { year: number; month: number }) => m.year === 2031 && m.month === 1,
  );
  const xml = (await (await request.get("/api/synthetic-broker-source/source-inbox")).body())
    .toString("utf8")
    .replaceAll("RU000A008813", "RU000A008815");
  const file = {
    name: "Брокерский 8860000 (01.01.31-31.01.31).xml",
    mimeType: "application/xml",
    buffer: Buffer.from(xml),
  };
  const before = await (await request.get("/api/synthetic-broker-inventory")).json();
  let economicPosts = 0;
  let savePosts = 0;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/api/broker-months/apply")) economicPosts++;
    if (req.method() === "POST" && req.url().endsWith("/api/broker-months/intakes")) savePosts++;
  });
  await page.goto(`/v2/close?month=${month.id}&step=final_review_close`);
  await uploadOriginal(page, file);
  await expect(page.getByText(/MATCHED — 12; PENDING REVIEW — 1/)).toBeVisible();
  // Lose the independent GET once after a successful server ACK.
  let failRead = true;
  await page.route(/\/api\/broker-months\/intakes\/\d+$/, async (route) => {
    if (route.request().method() === "GET" && failRead) {
      failRead = false;
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Сохранить разбор", exact: true }).click();
  await expect(page.getByRole("button", { name: "Повторить чтение журнала" })).toBeVisible();
  await page.getByRole("button", { name: "Повторить чтение журнала" }).click();
  await expect(
    page
      .getByRole("region", { name: "Долговечный разбор источника" })
      .getByText(/Сохранено наблюдений:/),
  ).toBeVisible();
  expect(savePosts).toBe(2);
  const list = await (
    await request.get(
      `/api/broker-months/intakes?reporting_month_id=${month.id}&include_unbound=true`,
    )
  ).json();
  const intake = list.find(
    (v: { document_sha256: string }) =>
      v.document_sha256 === createHash("sha256").update(xml).digest("hex"),
  );
  expect(intake.document.positions).toHaveLength(13);
  expect(
    intake.proposals.find((p: { isin: string }) => p.isin === "RU000A008815").currency_assessment
      .basis,
  ).toBe("owner_default_rub");
  expect(intake.financial_authority).toBe("none");
  await reloadWorkspace(page);
  await page.getByLabel("Сохранённый разбор", { exact: true }).selectOption(String(intake.id));
  await expect(
    page
      .getByRole("region", { name: "Долговечный разбор источника" })
      .getByText(/Сохранено наблюдений:/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  await expect(page.getByText(/RUB — допущение Owner/)).toBeVisible();
  await uploadOriginal(page, file);
  const currency = page.getByLabel("Валюта предложения RU000A008815", { exact: true });
  await expect(currency).toBeEnabled();
  await currency.fill("USD");
  await currency.focus();
  await expect(currency).toBeFocused();
  await page.getByRole("button", { name: "Проверить изменения разбора" }).click();
  const workflow = page.waitForResponse((r) =>
    r.url().includes(`/api/months/${month.id}/close-workflow`),
  );
  await page.getByRole("button", { name: "Подтвердить сохранение разбора" }).click();
  await workflow;
  await page.getByLabel("Сохранённый разбор", { exact: true }).selectOption(String(intake.id));
  await expect(page.getByText(/Выбрано Owner/)).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: info.outputPath("durable-source-intake-1440-125.png"),
    fullPage: true,
  });
  await page.getByRole("region", { name: "Долговечный разбор источника" }).screenshot({
    path: info.outputPath("durable-source-queue-1440-125.png"),
  });
  const after = await (await request.get("/api/synthetic-broker-inventory")).json();
  for (const [name, value] of Object.entries(before.counts)) {
    if (!name.startsWith("source_intake_") && name !== "source_return_proof_dependencies")
      expect(after.counts[name], name).toBe(value);
  }
  // The reviewed currency change retires source-return evidence, without
  // creating a proof or changing any pre-existing financial table.
  expect(after.counts.source_return_proof_dependencies).toBe(
    before.counts.source_return_proof_dependencies + 1,
  );
  expect(economicPosts).toBe(0);
  const close = await request.post(`/api/months/${month.id}/close`);
  expect(close.ok()).toBe(false);
  expect(
    (await (await request.get(`/api/broker-months/intakes/${intake.id}`)).json()).state.overrides,
  ).toEqual({ RU000A008815: "USD" });
});

test("Month workspace: two accounts, valid/broken/valid XML, replay, Back/Reload, corrections and negative Close", async ({
  page,
  request,
}, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  async function post(path: string, data: unknown) {
    const result = await request.post(path, { data });
    expect(result.ok(), await result.text()).toBe(true);
    return result.json();
  }
  const month = await post("/api/months", {
    year: 2034,
    month: 5,
    snapshot_date: "2034-06-01",
    source: "manual",
  });
  const brokerA = await post("/api/accounts", {
    name: "Month synthetic broker A",
    account_type: "brokerage",
  });
  const brokerB = await post("/api/accounts", {
    name: "Month synthetic broker B",
    account_type: "iis",
  });
  const savings = await post("/api/accounts", {
    name: "Month synthetic savings",
    account_type: "deposit",
  });
  const rub = (amount: string) => ({ amount, currency: "RUB" });
  const salary = await request.put(`/api/incomes/salary/${month.id}`, {
    data: {
      gross_amount: rub("100000.00"),
      tax_amount: rub("13000.00"),
      net_amount: rub("87000.00"),
    },
  });
  expect(salary.ok()).toBe(true);
  await post("/api/deposits", {
    reporting_month_id: month.id,
    account_id: savings.id,
    name: "Month synthetic deposit",
    deposit_type: "deposit",
    balance: rub("12345.67"),
    annual_rate: "10.00",
  });
  await post("/api/debts", {
    reporting_month_id: month.id,
    debt_type: "credit_card",
    name: "Month synthetic credit card",
    current_balance: rub("7654.32"),
  });
  await post("/api/comments", {
    reporting_month_id: month.id,
    text: "Protected synthetic month comment",
  });
  const manual = async () =>
    Promise.all(
      ["incomes", "deposits", "debts", "comments", "positions"].map(async (name) =>
        (await request.get(`/api/${name}?month_id=${month.id}`)).json(),
      ),
    );
  const instrumentsBefore = await (await request.get("/api/instruments")).json();
  await post("/api/positions", {
    reporting_month_id: month.id,
    account_id: brokerA.id,
    instrument_id: instrumentsBefore.find((row: { isin: string }) => row.isin === "RU000A000000")
      .id,
    quantity: "3",
    average_cost_per_unit: rub("99.00"),
    market_price_per_unit: rub("101.00"),
    price_source: "manual",
    price_date: "2034-05-31",
    notes: "Protected synthetic manual position",
  });
  const before = await manual();
  // This scenario owns disjoint native aliases: preceding acceptance journeys
  // may already have frozen 7654321/8765432 mappings to their own Hermes accounts.
  const rawA = Buffer.from(
    (await (await request.get("/api/synthetic-broker-source/month-ui-a")).body())
      .toString("utf8")
      .replaceAll("7654321", "7452034"),
  );
  const rawB = Buffer.from(
    (await (await request.get("/api/synthetic-broker-source/month-ui-b")).body())
      .toString("utf8")
      .replaceAll("8765432", "8562034"),
  );
  const fileA = {
    name: "Брокерский 7452034 (01.05.34-31.05.34).xml",
    mimeType: "application/xml",
    buffer: rawA,
  };
  const fileB = {
    name: "Брокерский 8562034 (01.05.34-31.05.34).xml",
    mimeType: "application/xml",
    buffer: rawB,
  };
  const fileBad = {
    name: "broken.xml",
    mimeType: "application/xml",
    buffer: Buffer.from("<broken>"),
  };
  let saves = 0;
  const financialPosts: string[] = [];
  page.on("request", (sent) => {
    const path = new URL(sent.url()).pathname;
    if (sent.method() === "POST" && path === "/api/broker-months/intakes") saves++;
    if (sent.method() === "POST" && (path.endsWith("/apply") || path.endsWith("/close")))
      financialPosts.push(path);
  });
  await page.goto(`/v2/close?month=${month.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Месяц.*Май\s2034/);
  await expect(page.getByText(/Снимок 01.06.2034/)).toBeVisible();
  await monthPanel(page, "brokers");
  const sourcePanel = page.getByRole("region", { name: "Брокерские выписки", exact: true });
  let failedRead = false;
  await page.route(/\/api\/broker-months\/intakes\/\d+$/, async (route) => {
    if (!failedRead && route.request().method() === "GET") {
      failedRead = true;
      await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    } else await route.continue();
  });
  await sourcePanel.getByLabel("XML-файлы").setInputFiles([fileA, fileBad, fileB]);
  const retry = sourcePanel.getByRole("button", { name: /^Повторить чтение / });
  await expect(retry).toBeEnabled();
  expect(saves).toBe(3);
  await expect(sourcePanel.getByText("broken.xml: Не сохранен", { exact: true })).toBeVisible();
  const currentIntakes = async () =>
    (await (await request.get("/api/broker-months/intakes?include_unbound=true")).json()).filter(
      (row: { covered_from: string }) => row.covered_from === "2034-05-01",
    );
  const saved = await currentIntakes();
  expect(saved).toHaveLength(2);
  for (const row of saved) {
    expect(row.financial_authority).toBe("none");
    expect(row.state.account_id).toBeNull();
    expect(row.state.reporting_month_id).toBeNull();
  }
  expect(await manual()).toEqual(before);
  expect(await (await request.get("/api/instruments")).json()).toEqual(instrumentsBefore);
  await expect(sourcePanel.getByLabel("XML-файлы")).toBeEnabled();
  await expect(retry).toBeEnabled();
  await retry.click();
  expect(saves).toBe(3);
  await expect(sourcePanel.getByLabel("XML-файлы")).toBeEnabled();
  await sourcePanel.getByLabel("XML-файлы").setInputFiles([fileA, fileB]);
  await expect.poll(() => saves).toBe(5);
  await expect(
    sourcePanel.getByText(`${fileA.name}: Сохранен`, { exact: true }).first(),
  ).toBeVisible();
  await expect(
    sourcePanel.getByText(`${fileB.name}: Сохранен`, { exact: true }).first(),
  ).toBeVisible();
  expect(await currentIntakes()).toHaveLength(2);
  const picker = sourcePanel.getByLabel("Счёт источника месяца");
  const list = sourcePanel.getByRole("list", { name: "Источники и исключения месяца" });
  await selectSourceAccount(page, "7452034");
  await expect(list).not.toContainText("8562034");
  await selectSourceAccount(page, "8562034");
  await expect(list).not.toContainText("7452034");
  await page.goBack();
  await expect(picker).toHaveValue("7452034");
  await reloadWorkspace(page);
  await expect(picker).toHaveValue("7452034");
  await sourcePanel.getByRole("link", { name: "Облигации и доходность · 7452034" }).click();
  await expect(page).toHaveURL(
    /\/v2\/returns\?.*scope=source%3A7452034.*start=2034-04-30&end=2034-05-31#returns-instruments/,
  );
  const returnsPaper = page.getByRole("row").filter({ hasText: "RU000A000001" });
  await returnsPaper.getByRole("button").click();
  await expect(page.getByText(/Количество:/)).toBeVisible();
  await page.goBack();
  await expect(picker).toHaveValue("7452034");
  await page.getByRole("link", { name: /Снимок и общие данные/ }).click();
  await page.getByLabel("Дата снимка", { exact: true }).fill("2034-05-31");
  await page.getByRole("button", { name: "Сохранить общие данные", exact: true }).click();
  await expect(page.getByText("Сохранено", { exact: true })).toBeVisible();
  await monthPanel(page, "brokers");
  await expect(page.getByText(/Снимок 31.05.2034/)).toBeVisible();
  const sourceA = (await currentIntakes()).find(
    (row: { document: { filename_account: string } }) =>
      row.document.filename_account === "7452034",
  );
  await selectSourceAccount(page, "7452034");
  await sourcePanel.getByRole("button", { name: `Разобрать и исправить #${sourceA.id}` }).click();
  const journal = page.getByRole("region", { name: "Долговечный разбор источника" });
  await uploadOriginal(page, fileA);
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption(String(brokerA.id));
  await expect(
    page.getByRole("button", { name: "Проверить изменения", exact: true }),
  ).toBeEnabled();
  let releasePreview!: () => void;
  let previewHeld!: () => void;
  const release = new Promise<void>((resolve) => {
    releasePreview = resolve;
  });
  const held = new Promise<void>((resolve) => {
    previewHeld = resolve;
  });
  await page.route("**/api/broker-months/preview", async (route) => {
    const result = await route.fetch();
    previewHeld();
    await release;
    await route.fulfill({ response: result }).catch(() => {
      /* retired request */
    });
  });
  await page.getByRole("button", { name: "Проверить изменения", exact: true }).click();
  await held;
  await selectSourceAccount(page, "8562034");
  await selectSourceAccount(page, "7452034");
  releasePreview();
  await page.unroute("**/api/broker-months/preview");
  await expect(page.getByRole("region", { name: "Сводка исходного DRAFT" })).toHaveCount(0);
  await expect(page.getByText(/^Оригинал в текущем сеансе:/)).toHaveCount(0);
  await uploadOriginal(page, fileA);
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption(String(brokerA.id));
  await expect(
    page.getByRole("button", { name: "Проверить изменения", exact: true }),
  ).toBeEnabled();
  await journal.getByLabel("Валюта предложения счёта").fill("USD");
  await journal.getByRole("button", { name: "Проверить изменения разбора", exact: true }).click();
  await expect(journal.getByText(/финансовых изменений — 0/)).toBeVisible();
  await selectSourceAccount(page, "8562034");
  await expect(journal.getByRole("button", { name: "Подтвердить сохранение разбора" })).toHaveCount(
    0,
  );
  await expect(
    page.getByText(`Оригинал в текущем сеансе: ${fileA.name}`, { exact: false }),
  ).toHaveCount(0);
  await expect(journal.getByLabel("Валюта предложения счёта")).toHaveValue("");
  await expect(journal.getByRole("option", { name: new RegExp(`#${sourceA.id} ·`) })).toHaveCount(
    0,
  );
  await selectSourceAccount(page, "7452034");
  await expect(journal.getByLabel("Сохранённый разбор")).toHaveValue(String(sourceA.id));
  await expect(journal.getByLabel("Валюта предложения счёта")).toHaveValue("");
  await expect(journal.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  await selectSourceAccount(page, "");
  await expect(journal.getByLabel("Сохранённый разбор")).toHaveValue("");
  await page.goBack();
  await expect(picker).toHaveValue("7452034");
  await reloadWorkspace(page);
  await expect(picker).toHaveValue("7452034");
  await showSourceReview(page);
  await expect(journal.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  await selectSourceAccount(page, "8562034");
  const sourceB = (await currentIntakes()).find(
    (row: { document: { filename_account: string } }) =>
      row.document.filename_account === "8562034",
  );
  await sourcePanel.getByRole("button", { name: `Разобрать и исправить #${sourceB.id}` }).click();
  await expect(journal.getByLabel("Сохранённый разбор")).toHaveValue(String(sourceB.id));
  await uploadOriginal(page, fileB);
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption(String(brokerB.id));
  await expect(journal.getByRole("option", { name: /Synthetic unknown month bond/ })).toHaveCount(
    1,
  );
  await journal.getByLabel("Валюта предложения счёта").fill("RUB");
  await journal.getByRole("button", { name: "Проверить изменения разбора", exact: true }).click();
  await expect(journal.getByText(/финансовых изменений — 0/)).toBeVisible();
  // Commit the non-economic review normally, then lose its ACK and first GET.
  // The immutable request is resolved via journal history, with no second POST.
  let decisionPosts = 0;
  let decisionKey = "";
  await page.route(`**/api/broker-months/intakes/${sourceB.id}/decisions`, async (route) => {
    decisionPosts++;
    const result = await route.fetch();
    expect(result.ok()).toBe(true);
    decisionKey = (await result.json()).request_id;
    await route.abort("connectionreset");
  });
  await journal
    .getByRole("button", { name: "Подтвердить сохранение разбора", exact: true })
    .click();
  await expect(journal.getByRole("button", { name: "Повторить чтение журнала" })).toBeEnabled();
  await selectSourceAccount(page, "7452034");
  await expect(page.getByText(/Переключение счёта отложено/)).toContainText("8562034");
  await expect(journal.getByLabel("Сохранённый разбор")).toHaveValue(String(sourceB.id));
  await expect(journal.getByLabel("Валюта предложения счёта")).toBeDisabled();
  await expect(page.getByRole("region", { name: "Бумаги и выплаты" })).toHaveCount(0);
  await page
    .locator("#month-source-review")
    .screenshot({ path: info.outputPath("month-scope-pending-history-get-1440.png") });
  await journal.getByRole("button", { name: "Повторить чтение журнала" }).click();
  await expect(page.getByText(/Переключение счёта отложено/)).toHaveCount(0);
  await expect(journal.getByLabel("Сохранённый разбор")).toHaveValue(String(sourceA.id));
  expect(decisionPosts).toBe(1);
  expect(decisionKey).not.toBe("");
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/broker-months/intakes/${sourceB.id}`)).json()).state
          .account_id,
    )
    .toBe(brokerB.id);
  await selectSourceAccount(page, "8562034");
  await reloadWorkspace(page);
  await expect(picker).toHaveValue("8562034");
  await monthPanel(page, "close");
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeDisabled();
  const denied = await request.post(`/api/months/${month.id}/close`);
  expect(denied.ok()).toBe(false);
  expect((await (await request.get(`/api/months/${month.id}`)).json()).status).toBe("draft");
  expect(await manual()).toEqual(before);
  expect(await (await request.get("/api/instruments")).json()).toEqual(instrumentsBefore);
  expect(financialPosts).toEqual([]);
  expect(brokerA.id).not.toBe(brokerB.id);
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.screenshot({
    path: info.outputPath("month-two-accounts-negative-close-1440.png"),
    fullPage: true,
  });
});

test("strict dividend v2 and durable payout: API to UI, lost ACK, Back Reload, retirement reaffirmation", async ({
  page,
  request,
}, info) => {
  test.setTimeout(150000);
  page.setDefaultTimeout(15000);
  const months = await (await request.get("/api/months")).json();
  const month = months.find(
    (row: { year: number; month: number }) => row.year === 2036 && row.month === 1,
  );
  const accounts = await (await request.get("/api/accounts")).json();
  const account = accounts.find(
    (row: { name: string }) => row.name === "Synthetic payout settlement",
  );
  const instruments = await (await request.get("/api/instruments")).json();
  const stock = instruments.find((row: { isin: string }) => row.isin === "RU000A000000");
  const scope = { reporting_month_id: month.id, account_id: account.id };
  const xml = await (await request.get("/api/synthetic-broker-source/dividend-settlement")).body();
  const original = {
    name: "Брокерский 7116600 (01.01.36-31.01.36).xml",
    mimeType: "application/xml",
    buffer: xml,
  };
  const sourcePreview = await request.post("/api/broker-months/preview", {
    multipart: { file: original, intent: JSON.stringify(scope) },
  });
  expect(sourcePreview.ok(), await sourcePreview.text()).toBe(true);
  const plan = await sourcePreview.json();
  const source = await request.post("/api/broker-months/apply", {
    multipart: {
      file: original,
      confirmation: JSON.stringify({
        ...scope,
        request_id: "desktop-dividend-base",
        confirmation_digest: plan.confirmation_digest,
        reviewed_account_bindings: plan.account_bindings,
      }),
    },
  });
  expect(source.ok(), await source.text()).toBe(true);
  const ecf = await request.post("/api/expected-flows", {
    data: {
      ...scope,
      instrument_id: stock.id,
      flow_type: "dividend",
      expected_date: "2036-02-01",
      gross_amount: { amount: "1130.00", currency: "RUB" },
      expected_tax_amount: { amount: "130.00", currency: "RUB" },
      source: "synthetic-independent-forecast",
      source_as_of_date: "2036-01-31",
      forecast_version: "v1",
    },
  });
  expect(ecf.ok(), await ecf.text()).toBe(true);
  const manual = await ecf.json();
  await page.goto(`/v2/close?month=${month.id}&panel=brokers`);
  await showSourceReview(page);
  await page.getByText("Принять Money в этот черновик", { exact: true }).click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByLabel("Проверять также строгие net-дивиденды").check();
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const inventory = page.getByRole("table", { name: "Все наблюдения Money" });
  await expect(inventory).toContainText("dividend_paid_candidate");
  await inventory
    .getByRole("row")
    .filter({ hasText: "dividend_paid_candidate" })
    .getByRole("checkbox")
    .check();
  await inventory
    .getByRole("row")
    .filter({ hasText: "account_cash_in_candidate" })
    .getByRole("checkbox")
    .check();
  await page.getByLabel(/Подтверждённая акция для строки/).selectOption(String(stock.id));
  await page
    .getByLabel("Независимое основание окончательного net-зачисления")
    .fill("synthetic-final-net");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  await page
    .getByRole("checkbox", { name: /Я подтверждаю перечисленные конкретные решения Money/ })
    .check();
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  const stored = page.getByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  await expect(stored).toContainText("Дивиденд", { timeout: 30000 });
  await expect(stored).toContainText("Неизвестно");
  const sourceRead = await (await request.get("/api/broker-months/desktop-dividend-base")).json();
  const moneyId = sourceRead.money_acceptance.request_id;
  expect(sourceRead.money_acceptance.contract_version).toBe("broker_money_v2");
  const moneyReceipt = await (await request.get(`/api/broker-months/${moneyId}`)).json();
  const actual = moneyReceipt.targets.find(
    (target: { role: string }) => target.role === "dividend",
  );
  expect(actual.facts.net_amount_kopecks).toBe("100000");
  expect(actual.facts.tax_amount_kopecks).toBeNull();
  const obligationUrl = `/api/broker-months/payout-obligations?reporting_month_id=${month.id}&account_id=${account.id}`;
  expect((await (await request.get(obligationUrl)).json())[0].coverage_state).toBe("unknown");
  const before = await (await request.get("/api/synthetic-broker-inventory")).json();
  const review = page.getByRole("region", { name: "Сверка фактических выплат", exact: true });
  async function prepareSettlement(operation: string, state: string) {
    await review.getByText(`Выплата #${actual.target_id}: ${state}`, { exact: true }).click();
    if (operation !== "link")
      await review.getByRole("combobox", { name: "Решение", exact: true }).selectOption(operation);
    else
      await review
        .getByRole("combobox", { name: "Ручной прогноз", exact: true })
        .selectOption(String(manual.id));
    for (const label of [
      "Ссылка на проверенный источник",
      "Основание точной связи события",
      "Основание полного исполнения или отзыва",
    ])
      await review.getByLabel(label, { exact: true }).fill("synthetic-reviewed-event");
    await review.getByRole("button", { name: "Проверить связь выплаты", exact: true }).click();
    await review.getByRole("checkbox", { name: /Подтверждаю это конкретное решение/ }).check();
  }
  await prepareSettlement("link", "требуется сверка");
  let r1 = "";
  let payoutWrites = 0;
  page.on("request", (sent) => {
    if (sent.url().endsWith("/api/broker-months/payout-apply")) payoutWrites++;
  });
  await page.route(
    "**/api/broker-months/payout-apply",
    async (route) => {
      r1 = route.request().postDataJSON().request_id;
      const response = await route.fetch();
      expect(response.ok(), await response.text()).toBe(true);
      await route.abort("failed");
    },
    { times: 1 },
  );
  await review.getByRole("button", { name: "Подтвердить связь выплаты", exact: true }).click();
  await expect(review.getByRole("button", { name: "Повторить GET связи" })).toBeVisible();
  await page.goto(`/v2/returns?month=${month.id}`);
  await page.goBack();
  const [workflowAfterBackReload] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().endsWith(`/api/months/${month.id}/close-workflow`),
      { timeout: 30000 },
    ),
    page.reload(),
  ]);
  expect(workflowAfterBackReload.status()).toBe(200);
  await showSourceReview(page);
  await review.getByText(`Выплата #${actual.target_id}: исполнено`, { exact: true }).click();
  await expect(review.getByRole("button", { name: "Проверить связь выплаты" })).toBeDisabled();
  await review.getByRole("button", { name: "Повторить GET связи" }).click();
  await expect(review.getByRole("button", { name: "Повторить GET связи" })).toHaveCount(0);
  expect(payoutWrites).toBe(1);
  const first = await (await request.get(`/api/broker-months/${r1}`)).json();
  expect(first.relations[0].state).toBe("paid");
  const calendar = await (
    await request.get(`/api/payouts/calendar?month_id=${month.id}&forecast_version=v1`)
  ).json();
  expect(calendar).toEqual([]);
  await page.screenshot({
    path: info.outputPath("payout-independent-get-after-reload.png"),
    fullPage: true,
  });
  await prepareSettlement("retire", "исполнено");
  let r2 = "";
  const retirement = page.waitForResponse((response) => {
    if (
      !response.url().endsWith("/api/broker-months/payout-apply") ||
      response.request().method() !== "POST"
    )
      return false;
    const sent = response.request().postDataJSON();
    if (
      sent.operation !== "retire" ||
      sent.reporting_month_id !== month.id ||
      sent.account_id !== account.id ||
      sent.investment_cash_flow_id !== actual.target_id
    )
      return false;
    r2 = sent.request_id;
    return true;
  });
  const retirementReceiptRead = page.waitForResponse(
    (response) =>
      r2 !== "" &&
      response.request().method() === "GET" &&
      response.url().endsWith(`/api/broker-months/${r2}`),
  );
  const retirementObligationsRead = page.waitForResponse(
    (response) =>
      r2 !== "" && response.request().method() === "GET" && response.url().endsWith(obligationUrl),
  );
  await review.getByRole("button", { name: "Подтвердить связь выплаты", exact: true }).click();
  const retiredResponse = await retirement;
  expect(retiredResponse.ok(), await retiredResponse.text()).toBe(true);
  const retired = await retiredResponse.json();
  expect(retired.request_id).toBe(r2);
  const retiredReceiptResponse = await retirementReceiptRead;
  expect(retiredReceiptResponse.ok(), await retiredReceiptResponse.text()).toBe(true);
  const retiredReceipt = await retiredReceiptResponse.json();
  expect(retiredReceipt.request_id).toBe(r2);
  expect(retiredReceipt.confirmation_digest).toBe(retired.confirmation_digest);
  expect(retiredReceipt.accepted).toEqual(retired.accepted);
  const retiredObligationsResponse = await retirementObligationsRead;
  expect(retiredObligationsResponse.ok(), await retiredObligationsResponse.text()).toBe(true);
  const retiredObligations = await retiredObligationsResponse.json();
  const retiredCurrent = retiredObligations.find(
    (row: { investment_cash_flow_id: number }) => row.investment_cash_flow_id === actual.target_id,
  );
  expect(retiredCurrent.terminal_relation.state).toBe("retired");
  expect(retiredCurrent.terminal_relation.retired_request_id).toBe(r2);
  await expect(
    review.getByText(`Выплата #${actual.target_id}: доказательство отозвано`, { exact: true }),
  ).toBeVisible();
  await prepareSettlement("reaffirm", "доказательство отозвано");
  const reaffirmation = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/broker-months/payout-apply") &&
      response.request().method() === "POST",
  );
  const reaffirmationRead = page.waitForResponse((response) =>
    response.url().endsWith(obligationUrl),
  );
  await review.getByRole("button", { name: "Подтвердить связь выплаты", exact: true }).click();
  const reaffirmedResponse = await reaffirmation;
  expect(reaffirmedResponse.ok(), await reaffirmedResponse.text()).toBe(true);
  const reaffirmed = await reaffirmedResponse.json();
  const obligationsResponse = await reaffirmationRead;
  expect(obligationsResponse.ok(), await obligationsResponse.text()).toBe(true);
  const obligations = await obligationsResponse.json();
  const current = obligations.find(
    (row: { investment_cash_flow_id: number }) => row.investment_cash_flow_id === actual.target_id,
  );
  expect(current.terminal_relation.state).toBe("paid");
  expect(current.terminal_relation.accepted_request_id).toBe(reaffirmed.request_id);
  expect(payoutWrites).toBe(3);
  await expect(
    review.getByText(`Выплата #${actual.target_id}: исполнено`, { exact: true }),
  ).toBeVisible();
  const old = await (await request.get(`/api/broker-months/${r1}`)).json();
  expect(old.accepted).toEqual(first.accepted);
  expect(old.relations[0].retired_request_id).toBe(r2);
  const after = await (await request.get("/api/synthetic-broker-inventory")).json();
  for (const [table, digest] of Object.entries(before.table_digests)) {
    if (!["broker_month_applies", "applied_payout_reconciliations"].includes(table))
      expect(after.table_digests[table], table).toBe(digest);
  }
  expect((await (await request.get(`/api/broker-months/${moneyId}`)).json()).accepted).toEqual(
    moneyReceipt.accepted,
  );
  const [workflowAfterReload] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().endsWith(`/api/months/${month.id}/close-workflow`),
      { timeout: 30000 },
    ),
    page.reload(),
  ]);
  expect(workflowAfterReload.status()).toBe(200);
  await showSourceReview(page);
  await expect(
    review.getByText(`Выплата #${actual.target_id}: исполнено`, { exact: true }),
  ).toBeVisible();
});

test("terminal retirement Close preserves UNKNOWN through Month calendar Back Reload and R3 R5", async ({
  page,
  request,
}, info) => {
  test.setTimeout(180000);
  const seed = await (await request.get("/api/synthetic-terminal-payout")).json();
  const monthId = seed.forecast_month_id;
  const calendarUrl = `/api/payouts/calendar?month_id=${monthId}&forecast_version=v1`;
  const calendarPage = `/v2/data/payouts?month=${monthId}&from=monthly-close-v2&monthId=${monthId}&step=future_payouts`;
  const inventory = () => request.get("/api/synthetic-broker-inventory").then((r) => r.json());
  const original = await inventory();
  async function acceptStep(step: number, operation: string, predecessor?: number) {
    const intent = {
      ...seed.intent,
      operation,
      predecessor_id: predecessor ?? null,
    };
    const first = await (
      await request.post("/api/broker-months/payout-preview", { data: intent })
    ).json();
    const reviewed = {
      ...intent,
      claims: {
        reference: "synthetic-original-review",
        independent_event_reference: "synthetic-exact-event",
        settlement_basis_reference: "synthetic-full-settlement",
        review_context_digest: first.review_context_digest,
        provider_identity_key: "n:1",
        actual_is_exact_event: operation !== "retire",
        full_event_settled_not_partial: true,
        exact_manual_row_is_same_event: operation !== "retire",
      },
    };
    const plan = await (
      await request.post("/api/broker-months/payout-preview", {
        data: reviewed,
      })
    ).json();
    expect(plan.can_apply, JSON.stringify(plan.blockers)).toBe(true);
    const response = await request.post("/api/broker-months/payout-apply", {
      data: {
        ...reviewed,
        request_id: `terminal-ui-R${step}`,
        confirmation_digest: plan.confirmation_digest,
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  }
  async function transition(action: "close" | "reopen") {
    const response = await request.post(`/api/months/${monthId}/${action}`);
    expect(response.ok(), await response.text()).toBe(true);
  }
  async function checkUnknown(afterReload: boolean) {
    const before = await inventory();
    const calendar = await (await request.get(calendarUrl)).json();
    expect(calendar).toHaveLength(1);
    expect(calendar[0].items).toEqual([]);
    expect(calendar[0].actual_attribution_coverage).toBe("unknown");
    expect(calendar[0].passive_net).toEqual({
      amount: "0.00",
      currency: "RUB",
    });
    const [workflowResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith(`/api/months/${monthId}/close-workflow`)),
      page.goto(`/v2/close?month=${monthId}&step=future_payouts`),
    ]);
    expect(workflowResponse.status()).toBe(200);
    const workflow = await workflowResponse.json();
    const future = workflow.steps.find((s: { id: string }) => s.id === "future_payouts");
    expect(future.reason_codes).toEqual(["month_closed_read_only"]);
    expect(future.affects_close).toBe(false);
    await expect(
      page.getByRole("heading", { name: "Месяц · Декабрь 2037", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Открыть месяц заново", exact: true }),
    ).toBeVisible();
    await page.goto(calendarPage);
    const region = page.getByRole("region", {
      name: "Календарь выплат: горизонтальная прокрутка таблицы",
    });
    await expect(region).toContainText("Полнота неизвестна; известная часть:");
    await expect(region).toContainText("0 выплат");
    await expect(region).not.toContainText("999");
    if (afterReload) {
      await page.goto(`/v2/returns?month=${monthId}`);
      await page.goBack();
      await page.reload();
      await expect(region).toContainText("Полнота неизвестна; известная часть:");
      await expect(region).toContainText("0 выплат");
      await page.screenshot({
        path: info.outputPath("retired-closed-calendar-after-back-reload.png"),
        fullPage: true,
      });
    }
    expect((await inventory()).digest).toBe(before.digest);
  }
  async function draftWarning(expected: boolean) {
    const workflow = await (await request.get(`/api/months/${monthId}/close-workflow`)).json();
    const future = workflow.steps.find((s: { id: string }) => s.id === "future_payouts");
    expect(future.reason_codes.includes("payout_reconciliation_changed")).toBe(expected);
    expect(future.affects_close).toBe(false);
  }
  const r1 = await acceptStep(1, "link");
  await draftWarning(false); // APP-only, NULL ECF: no false Month warning.
  await acceptStep(2, "retire", r1.relations[0].id);
  await draftWarning(true); // Advisory while editable; CLOSED remains read-only.
  await transition("close");
  await checkUnknown(true);
  await transition("reopen");
  const r3 = await acceptStep(3, "reaffirm", r1.relations[0].id);
  await transition("close");
  expect(await (await request.get(calendarUrl)).json()).toEqual([]);
  await page.goto(calendarPage);
  await expect(page.getByText("Нет ожидаемых выплат", { exact: true })).toBeVisible();
  await transition("reopen");
  await acceptStep(4, "retire", r3.relations[0].id);
  await transition("close");
  await checkUnknown(false);
  await transition("reopen");
  await acceptStep(5, "reaffirm", r3.relations[0].id);
  await transition("close");
  expect(await (await request.get(calendarUrl)).json()).toEqual([]);
  await page.goto(calendarPage);
  await page.reload();
  await expect(page.getByText("Нет ожидаемых выплат", { exact: true })).toBeVisible();
  for (const [accepted, retired] of [
    [r1, "terminal-ui-R2"],
    [r3, "terminal-ui-R4"],
  ]) {
    const receipt = await (await request.get(`/api/broker-months/${accepted.request_id}`)).json();
    expect(receipt.accepted).toEqual(accepted.accepted);
    expect(receipt.relations[0].retired_request_id).toBe(retired);
  }
  const after = await inventory();
  expect(after.table_digests.investment_cash_flows).toBe(
    original.table_digests.investment_cash_flows,
  );
  expect(after.counts.investment_cash_flows).toBe(original.counts.investment_cash_flows);
});
