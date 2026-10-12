import { expect, test } from "@playwright/test";

test("exact structural exceptions permit reviewed incomplete DRAFT and GET, while server Close stays blocked", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const xml = await (await request.get("/api/synthetic-broker-source/structure")).body();
  await page.goto("/v2/close?month=6&step=final_review_close");
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("1");
  await page.getByLabel("Оригинальный XML MyBroker", { exact: true }).setInputFiles({
    name: "Брокерский 1234567 (01.06.30-30.06.30).xml",
    mimeType: "application/xml",
    buffer: xml,
  });
  const response = page.waitForResponse((r) => r.url().endsWith("/api/broker-months/preview"));
  await page.getByRole("button", { name: "Проверить MyBroker", exact: true }).click();
  const preview = await (await response).json();
  expect(preview).toMatchObject({
    can_apply: true,
    bookkeeping_ready: false,
    conflicts: [],
    exact_return_ready: false,
  });
  expect(preview.exceptions).toContain("unparsed_source_rows");
  expect(preview.identity.evidence.draft_structure.financial_authority).toBe("none");
  const apply = page.getByRole("button", { name: "Сформировать неполный черновик", exact: true });
  await expect(apply).toBeDisabled();
  await expect(page.getByText(/Черновик неполный. Есть неразобранные/)).toBeVisible();
  const aliases = page.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ });
  if (await aliases.count()) await aliases.check();
  await page
    .getByRole("checkbox", { name: "Я проверил весь счёт и видимую неполноту черновика." })
    .check();
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
  await expect(page.getByText(/Черновик неполный; Close заблокирован/)).toBeVisible();
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
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeDisabled();
  expect((await request.post("/api/months/6/close")).status()).toBe(422);
  await page.reload();
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
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("1");
  await page
    .getByLabel("Оригинальный XML MyBroker", { exact: true })
    .setInputFiles({ name: filename, mimeType: "application/xml", buffer: xml });
  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/broker-months/preview"),
  );
  await page.getByRole("button", { name: "Проверить MyBroker", exact: true }).click();
  const preview = await (await previewResponse).json();
  expect(preview.account_bindings).toHaveLength(3);
  const aliases = page.getByRole("table", { name: "Привязки исходных счетов" });
  for (const identity of ["1234567", "ROW-A", "ROW-B", "filename_account", "acc_code"])
    await expect(aliases).toContainText(identity);
  await expect(page.getByRole("table", { name: "Позиции по исходному отчёту" })).toContainText(
    "RU000A000001",
  );
  await expect(page.getByText(/Общая оценка источника/)).toContainText("2 400,01");
  const apply = page.getByRole("button", { name: "Сформировать черновик", exact: true });
  await expect(apply).toBeDisabled();
  const reviewed = page.getByRole("checkbox", {
    name: "Я проверил весь счёт и видимую неполноту черновика.",
  });
  await reviewed.focus();
  await page.keyboard.press("Space");
  await expect(reviewed).toBeChecked();
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
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible();
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
  await page.reload();
  await expect(page.getByText(/Доступно чтение сохранённого источника/)).toBeVisible();
  await expect(page.getByLabel("Оригинальный XML MyBroker")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("closed-1280.png"), fullPage: true });

  await page.goto("/v2/close?month=2&step=final_review_close");
  const partial = await (await request.get("/api/synthetic-broker-source/partial")).body();
  await page.getByLabel("Брокерский счёт", { exact: true }).selectOption("1");
  await page.getByLabel("Оригинальный XML MyBroker", { exact: true }).setInputFiles({
    name: "Брокерский 1234567 (01.02.30-28.02.30).xml",
    mimeType: "application/xml",
    buffer: partial,
  });
  await page.getByRole("button", { name: "Проверить MyBroker", exact: true }).click();
  await expect(page.getByRole("table", { name: "Привязки исходных счетов" })).toContainText(
    "Существующая",
  );
  await expect(
    page.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }),
  ).toHaveCount(0);
  await expect(page.getByText(/Черновик неполный. Есть неразобранные/)).toBeVisible();
  await page.getByText("Все денежные строки и секции источника").click();
  await expect(page.getByText("Не разобрано — требуется доказательство")).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Я проверил весь счёт и видимую неполноту черновика." })
    .check();
  await page.getByRole("button", { name: "Сформировать неполный черновик", exact: true }).click();
  await expect(page.getByText(/Черновик неполный; Close заблокирован/)).toBeVisible();
  const blocked = await (await request.get("/api/months/2/close-workflow")).json();
  expect(blocked.readiness.can_close).toBe(false);
  expect(JSON.stringify(blocked.readiness)).toContain("money_semantics_unsupported");
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
  await page.reload();
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
  await page.reload();
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
  await page.reload();
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
  await page.reload();
  await expect(stored.getByRole("row")).toHaveCount(5, { timeout: 30000 });
  expect((await (await request.get("/api/months/4/close-readiness")).json()).can_close).toBe(true);
  await page.screenshot({ path: info.outputPath("paid-nkd-get-1280.png"), fullPage: true });
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  const closed = page.waitForResponse(
    (response) => response.url().endsWith("/api/months/4/close"),
    { timeout: 30000 },
  );
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect((await closed).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible({
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
  await page.reload();
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
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  const closed = page.waitForResponse((response) => response.url().endsWith("/api/months/5/close"));
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect((await closed).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible({
    timeout: 30000,
  });
});
