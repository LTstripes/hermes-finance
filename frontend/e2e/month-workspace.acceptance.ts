import { expect, type Page, test } from "@playwright/test";

test("XML plus one Alfa PDF preview retains historical scope without a financial write", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1366, height: 1000 });
  const metric = (value: string | null) => ({ value, status: "provisional", reason_codes: [] });
  const intervals = ["7114901", "7114902"].map((source_account) => ({
    source_account,
    source_sha256: source_account.repeat(8),
    opening_date: "2038-12-31",
    closing_date: "2039-10-31",
    period_kind: "historical_interval",
    history_from_zero: false,
    pnl: metric("12345"),
    modified_dietz: metric("0.01235"),
    xirr_period: metric("0.02"),
    xirr_annualized: metric("0.03"),
    instruments: [],
    account_only: [],
    unallocated_payouts: [],
    reason_codes: [],
    reconciliation: {
      xml_payout_occurrences: 2,
      linked_payout_occurrences: 2,
      cash_delta_kopecks: "0",
      pdf_closing_delta_kopecks: "0",
      pdf_pnl_delta_kopecks: "0",
    },
  }));
  intervals[0].pnl = metric(null);
  intervals[0].modified_dietz = metric(null);
  intervals[0].xirr_period = metric(null);
  intervals[0].xirr_annualized = metric(null);
  Object.assign(intervals[0], {
    known_subtotal: metric("12345"),
    source_advisories: ["4_Transfers_unsupported"],
    unresolved_movements: [{ isin: "RU000A000000", reason: "unresolved_native_security_movement" }],
    instruments: [
      {
        isin: "RU000A000000",
        pnl: metric(null),
        known_subtotal: metric("9000"),
        modified_dietz: metric(null),
        xirr_period: metric(null),
        xirr_annualized: metric(null),
        event_count: 2,
        reason_codes: ["unresolved_native_security_movement"],
      },
    ],
  });
  let previews = 0;
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/(?:apply|close)(?:\?|$)/.test(new URL(r.url()).pathname))
      writes.push(r.url());
  });
  await page.route("**/api/mybroker-preflight/preview", async (route) => {
    const data = route.request().postDataBuffer()?.toString() ?? "";
    expect((data.match(/name="income_report"/g) ?? []).length).toBe(1);
    expect((data.match(/name="files"/g) ?? []).length).toBe(2);
    previews++;
    await route.fulfill({
      json: {
        source_return_preview: {
          contract: "xml-pdf-source-return-preview-v1",
          financial_apply_available: false,
          close_available: false,
          pdf_period: { covered_from: "2039-01-01", covered_to: "2039-10-31" },
          pdf_payout_rows: 2,
          source_accounts: ["7114901", "7114902"],
          comparison: [],
          intervals,
        },
      },
    });
  });
  const created = await request.post("/api/months", {
    data: { year: 2039, month: 10, snapshot_date: "2039-10-31", source: "manual" },
  });
  expect(created.status()).toBe(201);
  const month = await created.json();
  await page.goto(`/v2/close?month=${month.id}`);
  await tile(page, /Брокерские выписки/);
  const buffers = await Promise.all(
    ["a", "b"].map(async (suffix) =>
      (await request.get(`/api/synthetic-broker-source/workspace-october-${suffix}`)).body(),
    ),
  );
  await openDisclosure(page, "Подробности");
  await expect(page.getByText("Проверяем сохранённые выписки…", { exact: true })).toHaveCount(0);
  let sourceReadHeld = false;
  let releaseSourceRead = () => {};
  const sourceReadGate = new Promise<void>((resolve) => {
    releaseSourceRead = resolve;
  });
  await page.route("**/api/broker-months/intakes?**", async (route) => {
    sourceReadHeld = true;
    await sourceReadGate;
    await route.continue();
  });
  await openDisclosure(page, "Исходники и повторный выбор файла");
  await page.getByLabel("XML-файлы", { exact: true }).setInputFiles(
    buffers.map((buffer, i) => ({
      name: `Брокерский 711490${i + 1} (01.01.39-31.10.39).xml`,
      mimeType: "application/xml",
      buffer: Buffer.from(
        buffer
          .toString()
          .replaceAll("7114001", "7114901")
          .replaceAll("7114002", "7114902")
          .replaceAll("2040", "2039"),
      ),
    })),
  );
  await expect(page.getByText(/Брокерский 711490[12].*: Сохран[её]н$/)).toHaveCount(2);
  await openDisclosure(page, "Подробности сверки XML с инвестиционным отчётом");
  await page.getByText("Расшифровка купонов и дивидендов — PDF Альфы", { exact: true }).click();
  await expect(page.locator('input[type="file"][accept=".xml"]')).toHaveCount(1);
  // Per-file Save labels precede the final list GET. Keyboard activation must
  // wait until the relocated PDF form is enabled, not merely present.
  const pdfInput = page.getByLabel("Загрузить PDF Альфы");
  await expect.poll(() => sourceReadHeld).toBe(true);
  await expect(pdfInput).toBeDisabled();
  expect(previews).toBe(0);
  releaseSourceRead();
  await expect(pdfInput).toBeEnabled();
  await pdfInput.setInputFiles({
    name: "synthetic-report.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("synthetic"),
  });
  const inspect = page.getByRole("button", { name: "Проверить XML и PDF", exact: true });
  await expect(inspect).toBeEnabled();
  await inspect.focus();
  await expect(inspect).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => previews).toBe(1);
  await expect(page.getByText(/Период PDF: 2039-01-01/)).toBeVisible();
  await expect(page.getByText(/Исторический период/)).toHaveCount(2);
  await expect(page.getByText(/Рублёвый результат счёта/).last()).toContainText("123.45");
  await expect(page.getByText(/Рублёвый результат счёта/).first()).toContainText("Не определено");
  await expect(page.getByText(/Дополнительные разделы исходного XML/)).toBeVisible();
  await expect(page.getByText(/Известная часть по денежным операциям/)).toContainText("123.45");
  await fits(page);
  await page.screenshot({
    path: info.outputPath("xml-pdf-historical-preview.png"),
    fullPage: true,
  });
  await inspect.click();
  await expect.poll(() => previews).toBe(2);
  expect(writes).toEqual([]);
});

async function openDisclosure(page: Page, name: string) {
  const summary = page.getByText(name, { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
  await expect(summary.locator("..")).toHaveAttribute("open", "");
}

async function uploadMonthFiles(
  page: Page,
  files: { name: string; mimeType: string; buffer: Buffer }[],
) {
  const uploaded = page.waitForResponse(
    (response) =>
      /\/api\/months\/\d+\/broker-sources$/.test(new URL(response.url()).pathname) &&
      response.request().method() === "POST",
  );
  const input = page.getByLabel("Выбрать файлы", { exact: true });
  await expect(input).toBeVisible();
  await expect(input).toBeEnabled();
  await input.setInputFiles(files);
  const response = await uploaded;
  expect(response.ok()).toBe(true);
  const ack = await response.json();
  expect(ack.financial_effects).toBe(0);
  expect(ack.results).toHaveLength(files.length);
  await expect(input).toBeEnabled();
  await expect(page.getByText("Проверяем сохранённые файлы…", { exact: true })).toHaveCount(0);
  return ack;
}

async function tile(page: Page, name: string | RegExp) {
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name })
    .click();
  await expect(page.locator("#month-work-area")).toBeVisible();
  await expect(page.locator("#month-work-area")).toHaveCount(1);
}

async function fits(page: Page) {
  const overflow = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    tables: [...document.querySelectorAll<HTMLElement>(".month-deposits-table")].map((table) => ({
      width: table.scrollWidth,
      available: table.parentElement?.clientWidth ?? 0,
    })),
  }));
  expect(overflow.page).toBe(false);
  for (const table of overflow.tables) expect(table.width).toBeLessThanOrEqual(table.available + 1);
}

test("Owner October workspace: one area, existing forms, two XML accounts, strict Apply and Close ACK recovery", async ({
  page,
  request,
}, info) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/v2/data/months");
  await page.getByRole("button", { name: "Создать другой период" }).click();
  await page.getByLabel("Целевой год").fill("2040");
  await page.getByLabel("Целевой месяц").selectOption("10");
  await page.getByRole("button", { name: "Создать месяц", exact: true }).click();
  const row = page
    .getByRole("listitem")
    .filter({ has: page.getByText("Октябрь 2040", { exact: true }) });
  const open = row.getByRole("link", { name: "Открыть месяц", exact: true });
  await expect(open).toBeVisible();
  const href = await open.getAttribute("href");
  const id = new URL(href ?? "", "http://fixture").searchParams.get("month");
  expect(id).toBeTruthy();
  await expect(page.getByRole("link", { name: "Проверить и закрыть" })).toHaveCount(0);
  await row.getByRole("button", { name: /Действия месяца/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Копировать", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await open.click();
  await expect(page.getByRole("navigation", { name: "Разделы месяца" })).toBeVisible();
  await expect(page.locator("#month-work-area")).toHaveCount(0);
  await expect(page.getByLabel("Выбрать файлы", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("october-entry.png"), fullPage: true });

  await tile(page, /Зарплата и другие доходы/);
  await page.getByLabel("Зарплата до вычета налогов", { exact: true }).fill("100000");
  await page.getByLabel("Фактическая зарплата после налогов", { exact: true }).fill("87000");
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Расходы и план/ })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText("Несохранённые изменения");
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.getByLabel("Фактическая зарплата после налогов", { exact: true })).toHaveValue(
    /87/,
  );
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let sent = () => {};
  const held = new Promise<void>((resolve) => {
    sent = resolve;
  });
  await page.route("**/api/incomes/**", async (route) => {
    if (route.request().method() === "GET") return route.continue();
    const response = await route.fetch();
    sent();
    await gate;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await held;
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Расходы и план/ })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText("Сохранение ещё не подтверждено");
  await page.getByRole("button", { name: "Вернуться к форме" }).click();
  await page.goBack();
  await expect(page.getByRole("alertdialog")).toContainText("Сохранение ещё не подтверждено");
  await page.getByRole("button", { name: "Вернуться к форме" }).click();
  await expect(
    page.getByLabel("Фактическая зарплата после налогов", { exact: true }),
  ).toBeVisible();
  release();
  await expect(page.getByRole("status").filter({ hasText: /^Сохранено$/ })).toBeVisible();
  await page.unroute("**/api/incomes/**");
  await tile(page, /Расходы и план/);
  await page.getByLabel("Категория расхода", { exact: true }).fill("Synthetic жильё");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("10000");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Расходы месяца" })
      .getByRole("cell", { name: "Synthetic жильё", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Категория расхода", { exact: true })).toHaveValue("");
  await expect(page.getByRole("status").filter({ hasText: /^Сохранено$/ })).toBeVisible();
  await tile(page, /Депозиты, накопления и деньги/);
  await page
    .getByLabel("Название вклада", { exact: true })
    .fill("Синтетический длинный вклад: все суммы и действия доступны");
  await page.getByLabel("Баланс вклада", { exact: true }).fill("12345678.90");
  await page.getByLabel("Годовая ставка %", { exact: true }).fill("12");
  await page.getByRole("button", { name: "Добавить вклад", exact: true }).click();
  await expect(page.getByRole("cell", { name: /^Синтетический длинный вклад/ })).toBeVisible();
  await expect(page.getByLabel("Название вклада", { exact: true })).toHaveValue("");
  await expect(
    page.getByRole("status").filter({
      hasText:
        /^Вклад «Синтетический длинный вклад: все суммы и действия доступны» сохранён; данные перечитаны\.$/,
    }),
  ).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => window.history.state?.monthNavigationGuard))
    .toBeUndefined();
  await fits(page);
  await page.reload();
  await expect(page.locator('[aria-current="page"]').filter({ hasText: /Депозиты/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: /^Синтетический длинный вклад/ })).toBeVisible();
  await page.getByRole("link", { name: "← К месяцу", exact: true }).first().click();
  await expect(page.locator("#month-work-area")).toHaveCount(0);
  await page.goBack();
  await expect(page.getByLabel("Название вклада", { exact: true })).toBeVisible();

  await tile(page, /Брокерские выписки/);
  const buffers = await Promise.all(
    ["a", "b"].map(async (suffix) =>
      (await request.get(`/api/synthetic-broker-source/workspace-october-${suffix}`)).body(),
    ),
  );
  const uploaded = await uploadMonthFiles(page, [
    {
      name: "Брокерский 7114001 (01.10.40-31.10.40).xml",
      mimeType: "application/xml",
      buffer: buffers[0],
    },
    { name: "broken.xml", mimeType: "application/xml", buffer: Buffer.from("<broken>") },
    {
      name: "Брокерский 7114002 (01.10.40-31.10.40).xml",
      mimeType: "application/xml",
      buffer: buffers[1],
    },
  ]);
  expect(uploaded.results[1]).toMatchObject({
    index: 1,
    item: null,
    error: { code: expect.any(String) },
  });
  expect(uploaded.results.filter((row: { error: unknown }) => row.error === null)).toHaveLength(2);
  for (const [index, alias] of [
    [0, "7114001"],
    [2, "7114002"],
  ] as const) {
    expect(uploaded.results[index].item.source_accounts).toEqual([`${alias}-000`]);
    expect(uploaded.results[index].item.intake_id).toEqual(expect.any(Number));
  }
  await expect(
    page.getByText("broken.xml: Не удалось сохранить файл; проверь его в подробностях.", {
      exact: true,
    }),
  ).toBeVisible();
  const savedFiles = page.getByRole("list", { name: "Сохранённые файлы", exact: true });
  await expect(savedFiles.getByRole("listitem")).toHaveCount(2);
  await openDisclosure(page, "Подробности");
  // Upload ACK also retires the pending-write history sentinel. Wait for its
  // asynchronous POP before starting a new account navigation (as after Save).
  await expect
    .poll(() => page.evaluate(() => window.history.state?.monthNavigationGuard))
    .toBeUndefined();
  for (const alias of ["7114001", "7114002"]) {
    if (alias === "7114002") {
      const duplicate = await uploadMonthFiles(page, [
        {
          name: "Брокерский 7114002 (01.10.40-31.10.40).xml",
          mimeType: "application/xml",
          buffer: buffers[1],
        },
      ]);
      expect(duplicate.results[0].duplicate).toBe(true);
      expect(duplicate.items).toHaveLength(2);
      await expect(page.getByText("Этот файл уже загружен.", { exact: true })).toBeVisible();
      await expect
        .poll(() => page.evaluate(() => window.history.state?.monthNavigationGuard))
        .toBeUndefined();
      const uploadedBRow = savedFiles
        .getByRole("listitem")
        .filter({ hasText: "Выписка счёта 7114002-000" });
      await uploadedBRow.getByText("Подробнее о файле", { exact: true }).click();
      const uploadedB = uploadedBRow.getByRole("button", {
        name: "Просмотреть данные",
        exact: true,
      });
      await uploadedB.click();
      await expect(
        page.getByRole("alertdialog", { name: "Открыть другую выписку?" }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Остаться", exact: true }).click();
      await expect(page.getByLabel("Счёт источника месяца", { exact: true })).toHaveValue(
        "7114001",
      );
      await expect(page.getByText(/^Оригинал в текущем сеансе:/)).toContainText("7114001");
      await uploadedB.click();
      await page.getByRole("button", { name: "Открыть выписку", exact: true }).click();
      await expect(page.getByLabel("Счёт источника месяца", { exact: true })).toHaveValue(
        "7114002",
      );
      await expect(page.getByText(/^Оригинал в текущем сеансе:/)).toContainText("7114002");
    }

    if ((await page.getByLabel("Счёт источника месяца", { exact: true }).inputValue()) !== alias)
      await page.getByLabel("Счёт источника месяца", { exact: true }).selectOption(alias);
    const confirmScope = page.getByRole("alertdialog", { name: "Сменить счёт?" });
    if (await confirmScope.isVisible())
      await confirmScope.getByRole("button", { name: "Сменить счёт", exact: true }).click();
    // Wait for the account navigation to commit before opening a source. The
    // previous all-account list already contains alias but still has two buttons.
    await expect(page.getByLabel("Счёт источника месяца", { exact: true })).toHaveValue(alias);
    const sources = page.getByRole("list", { name: "Источники и исключения месяца" });
    await expect(sources).toContainText(alias);
    await expect(sources).not.toContainText(alias === "7114001" ? "7114002" : "7114001");
    const review = sources.getByRole("button", { name: /Разобрать и исправить/ });
    await expect(review).toHaveCount(1);
    await review.click();
    await expect(page.getByLabel("Оригинальный XML MyBroker", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Проверить изменения", exact: true }).click();
    const apply = page.getByRole("button", { name: "Сохранить данные месяца", exact: true });
    await expect(apply).toBeEnabled();
    // The UI assertion measures independent readback, not the Apply round trip.
    // Arm before clicking so even an immediate ACK cannot be missed.
    const applied = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/broker-months/apply" &&
        response.request().method() === "POST",
    );
    // Reproduce the observed 5.02 s intake read without slowing the backend or
    // changing Apply/Close semantics. Arm before Apply invalidates the queries.
    let delayedIntakeReads = 0;
    const intakeListUrl = (url: URL) =>
      url.pathname === "/api/broker-months/intakes" &&
      url.searchParams.get("include_unbound") === "true" &&
      !url.searchParams.has("reporting_month_id");
    await page.route(intakeListUrl, async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 5500));
      delayedIntakeReads++;
      await route.fulfill({ response });
    });
    const sourcesRefreshed = page.waitForResponse(
      (response) => intakeListUrl(new URL(response.url())) && response.request().method() === "GET",
      // This read took 5.02 s in the failing CI trace. Bound only this source
      // refresh, leaving the suite and normal locator budgets unchanged.
      { timeout: 15000 },
    );
    await apply.click();
    expect((await applied).ok()).toBe(true);
    await expect(
      page.getByText(/Сохранённый результат подтверждён независимым чтением/),
    ).toBeVisible();
    const refreshed = await sourcesRefreshed;
    expect(refreshed.ok()).toBe(true);
    expect(await refreshed.finished()).toBeNull();
    expect(delayedIntakeReads).toBeGreaterThan(0);
    // The disclosure is rendered only after the intake query leaves isFetching.
    await expect(
      page.getByText("Подробности инструментов и предварительных выплат", { exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await page.unroute(intakeListUrl);
    await openDisclosure(page, "Подробности инструментов и предварительных выплат");
    for (const name of ["Synthetic stock", "Synthetic bond"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(page.getByText(/Наблюдаемое количество: 10 на 2040-10-31/)).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" }),
      ).toHaveCount(0);
    }
  }
  await page.screenshot({ path: info.outputPath("october-sources.png"), fullPage: true });
  const batches = await (await request.get(`/api/broker-months?reporting_month_id=${id}`)).json();
  expect(batches).toHaveLength(2);
  expect(new Set(batches.map((batch: { account_id: number }) => batch.account_id)).size).toBe(2);
  for (const batch of batches) expect(batch.accepted.position_ids).toHaveLength(2);
  await tile(page, /Закрыть месяц/);
  await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
  await expect(page.getByRole("list", { name: "Заполнение месяца" })).toHaveCount(0);
  await page.getByText("Подробнее о проверках", { exact: true }).click();
  await page.getByTestId("final-review-card-income_budget").getByRole("link").first().click();
  await expect(page).toHaveURL(/panel=income/);
  await expect(page.getByLabel("Фактическая зарплата после налогов", { exact: true })).toHaveValue(
    /87/,
  );
  await tile(page, /Закрыть месяц/);
  await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
  const close = page.getByRole("button", { name: "Закрыть месяц", exact: true });
  await expect(close).toBeEnabled();
  await page.screenshot({ path: info.outputPath("october-final.png"), fullPage: true });
  let closePosts = 0;
  await page.route(`**/api/months/${id}/close`, async (route) => {
    closePosts++;
    await route.fetch();
    await route.abort("failed");
  });
  await close.click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  expect(closePosts).toBe(1);
  await page.reload();
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  await tile(page, /Зарплата и другие доходы/);
  await expect(
    page.getByLabel("Фактическая зарплата после налогов", { exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("Фактическая зарплата после налогов", { exact: true })).toHaveValue(
    /87/,
  );
  await page.screenshot({ path: info.outputPath("october-closed.png"), fullPage: true });
});

for (const width of [1280, 1440, 1920])
  for (const zoom of [1, 1.25, 1.5]) {
    test(`Month desktop ${width} at ${zoom * 100}% CSS zoom: deposit data and actions fit`, async ({
      page,
      request,
    }, info) => {
      const month = await (
        await request.post("/api/months", {
          data: {
            year: 2042 + [1280, 1440, 1920].indexOf(width),
            month: Math.round(zoom * 4),
            snapshot_date: `${2042 + [1280, 1440, 1920].indexOf(width)}-${String(Math.round(zoom * 4)).padStart(2, "0")}-28`,
            source: "manual",
          },
        })
      ).json();
      const deposit = await request.post("/api/deposits", {
        data: {
          reporting_month_id: month.id,
          account_id: 2,
          name: "Синтетический длинный вклад: название переносится и остаётся читаемым",
          deposit_type: "deposit",
          balance: { amount: "12345678.90", currency: "RUB" },
          annual_rate: "12.50",
          actual_interest_received: { amount: "12345.67", currency: "RUB" },
        },
      });
      expect(deposit.ok()).toBe(true);
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/v2/data/months");
      await page.evaluate((value) => {
        document.documentElement.style.zoom = String(value);
      }, zoom);
      await expect(
        page.getByRole("link", { name: "Открыть месяц", exact: true }).first(),
      ).toBeVisible();
      const aligned = await page
        .getByRole("link", { name: "Открыть месяц", exact: true })
        .evaluateAll((links) => links.map((link) => link.getBoundingClientRect().x));
      expect(Math.max(...aligned) - Math.min(...aligned)).toBeLessThan(1);
      await fits(page);
      await page.screenshot({ path: info.outputPath("months.png"), fullPage: true });
      await page.goto(`/v2/close?month=${month.id}`);
      await page.evaluate((value) => {
        document.documentElement.style.zoom = String(value);
      }, zoom);
      await expect(page.getByRole("navigation", { name: "Разделы месяца" })).toBeVisible();
      await fits(page);
      await page.screenshot({ path: info.outputPath("tiles.png"), fullPage: true });
      await tile(page, /Депозиты, накопления и деньги/);
      const table = page.locator(".month-deposits-table");
      await expect(table).toContainText("12 345 678,90");
      await expect(table).toContainText("12 345,67");
      await expect(table.getByRole("button", { name: /Действия для вклада/ })).toBeVisible();
      await fits(page);
      await page.screenshot({ path: info.outputPath("deposits.png"), fullPage: true });
      await table.getByRole("button", { name: /Действия для вклада/ }).click();
      await page.getByRole("menuitem", { name: /Изменить/ }).click();
      const fields = await table
        .locator(
          'td[data-label="Баланс"] input, td[data-label="Получено"] input, td[data-label="Ставка %"] input, td[data-label="Тип"] select',
        )
        .evaluateAll((inputs) =>
          inputs.map((element) => {
            const input = element as HTMLInputElement | HTMLSelectElement;
            const style = getComputedStyle(input);
            const context = document.createElement("canvas").getContext("2d");
            if (!context) throw new Error("Canvas unavailable");
            context.font = style.font;
            const text =
              input instanceof HTMLSelectElement
                ? (input.selectedOptions[0]?.textContent ?? "")
                : input.value;
            return {
              text,
              required: context.measureText(text).width,
              available:
                input.clientWidth -
                Number.parseFloat(style.paddingLeft) -
                Number.parseFloat(style.paddingRight) -
                (input instanceof HTMLSelectElement ? 24 : 0),
            };
          }),
        );
      expect(fields).toHaveLength(4);
      for (const field of fields)
        expect(field.required, field.text).toBeLessThanOrEqual(field.available);
      await fits(page);
      await page.screenshot({ path: info.outputPath("deposit-edit.png"), fullPage: true });
      await page.getByRole("button", { name: "Отмена", exact: true }).click();
      await expect(table.locator("input, select")).toHaveCount(0);
      await expect(table).toContainText("12 345 678,90");
      await expect(table).toContainText("12 345,67");
      await tile(page, /Брокерские выписки/);
      const sourceDetails = page.getByText("Подробности", { exact: true });
      await expect(sourceDetails.locator("..")).not.toHaveAttribute("open");
      await expect(page.getByLabel("Выбрать файлы", { exact: true })).toBeVisible();
      await fits(page);
      await sourceDetails.focus();
      await page.keyboard.press("Enter");
      await expect(sourceDetails.locator("..")).toHaveAttribute("open", "");
      await expect(page.getByRole("region", { name: "Состояние источников месяца" })).toContainText(
        /Полных месячных оригиналов:/,
      );
      await expect(page.getByLabel("Счёт источника месяца", { exact: true })).toBeVisible();
      await fits(page);
      await page.screenshot({ path: info.outputPath("sources.png"), fullPage: true });
      await tile(page, /Закрыть месяц/);
      await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
      await fits(page);
      await page.screenshot({ path: info.outputPath("final.png"), fullPage: true });
    });
  }
