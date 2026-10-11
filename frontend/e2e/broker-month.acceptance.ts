import { expect, test } from "@playwright/test";

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

test("desktop Money adds one reviewed coupon/H2 batch to DRAFT, GET shows NULL tax and deferred NKD", async ({
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
  await page.getByText("Принять купоны и пополнения в этот черновик").click();
  await page.getByLabel(/Оригинальные XML для Money/).setInputFiles(original);
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const inventory = page.getByRole("table", { name: "Все наблюдения Money" });
  await expect(inventory).toContainText("trade_paid_nkd_candidate");
  const choose = inventory.getByRole("checkbox");
  for (let index = 0; index < 3; index++) await choose.nth(index).check();
  await page.getByLabel("Подтверждённая облигация для строки 2").selectOption("2");
  await page.getByLabel("Подтверждённая облигация для строки 3").selectOption("2");
  await page.getByRole("button", { name: "Проверить Money", exact: true }).click();
  const confirm = page.getByRole("checkbox", {
    name: /Я подтверждаю перечисленные конкретные решения Money/,
  });
  await confirm.focus();
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: "Принять один Money batch", exact: true }).click();
  const stored = page.getByRole("table", { name: "Сохранённые купоны и пополнения" });
  await expect(stored).toContainText("50 000");
  await expect(stored).toContainText("Неизвестно");
  expect(writes).toBe(1);
  expect(gets).toBe(1);
  const read = await (await request.get("/api/broker-months/desktop-money-base")).json();
  expect(read.money_acceptance.targets).toHaveLength(3);
  expect(read.money_acceptance.targets.every((t: { effective: boolean }) => t.effective)).toBe(
    true,
  );
  expect(read.exceptions).toContain("money_semantics_unsupported");
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
