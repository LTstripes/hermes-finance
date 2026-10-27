import fs from "node:fs";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { makeUiV2Workflow } from "../src/test/uiV2Fixtures";
import { event, ISIN, source } from "../src/test/sourceInstrumentFixtures";

const closed = {
  id: 7,
  year: 2030,
  month: 4,
  status: "closed",
  snapshot_date: "2030-04-30",
  source: "manual",
};

test("ui-v2 final review keeps broker blockers, evidence and keyboard details @viewport-owned", async ({
  page,
}, testInfo) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/") && request.method() !== "GET") {
      writes.push(`${request.method()} ${pathname}`);
    }
  });
  await installApi(page);
  const workflow = makeUiV2Workflow({ blocked: true });
  const month = { ...workflow.month, ...closed, status: "draft" as const };
  workflow.month = month;
  const reasons = [
    ["4_Transfers_unsupported", "Переводы требуют сверки"],
    ["5_UFSR_unsupported", "Данные UFSR не поддерживаются"],
    ["commission_basis_unresolved", "Учёт комиссии не подтверждён"],
    ["money_semantics_unsupported", "Денежные операции не разобраны"],
    ["settlement_principal_unresolved", "Основная сумма расчётов не подтверждена"],
    ["unparsed_source_rows", "Есть неразобранные строки отчёта"],
    ["money_semantics_unsupported", "Денежные операции не разобраны"],
    ["new_source_reason", "Нужно исправить перед закрытием"],
    ["constructor", "Нужно исправить перед закрытием"],
  ];
  const items = reasons.map(([code, title], index) => ({
    severity: "hard_blocker" as const,
    code,
    message: `${title}. MyBroker счёт #${index + 1}: исходные доказательства требуют сверки.`,
    context: { count: index + 1, coverage_state: "unknown", bookkeeping_ready: false },
  }));
  workflow.readiness = {
    can_close: false,
    hard_blocker_count: items.length,
    warning_count: 0,
    reason_codes: items.map((item) => item.code),
  };
  if (!workflow.final_review.available) throw new Error("Synthetic final review is missing");
  workflow.final_review.month_header = month;
  workflow.final_review.close_readiness = { can_close: false, items };
  await page.route("**/api/months", (route) => route.fulfill({ json: [month] }));
  await page.route("**/api/months/7", (route) => route.fulfill({ json: month }));
  await page.route("**/api/months/7/close-workflow", (route) => route.fulfill({ json: workflow }));
  await page.route("**/api/broker-months?reporting_month_id=7", (route) =>
    route.fulfill({ json: [] }),
  );

  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/v2/close?month=7");
    await page
      .getByRole("navigation", { name: "Разделы месяца" })
      .getByRole("link", { name: /Закрыть месяц/ })
      .click();
    await page.getByText("Подробнее об итогах и проверках", { exact: true }).click();
    await expect(page).toHaveURL(/\/v2\/close\?.*panel=close/);
    await expect(
      page.getByRole("region", { name: "Рабочая область: Закрыть месяц" }),
    ).toContainText(`Требует внимания: ${items.length}`);
    await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeDisabled();
    const summary = page.getByText("Показать причины и диагностику", { exact: true });
    const details = summary.locator("..");
    await summary.focus();
    await expect(summary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    const rows = details.locator(".final-review__diagnostic-list").first().getByRole("listitem");
    await expect(rows).toHaveCount(items.length);
    for (const [index, item] of items.entries()) {
      const row = rows.nth(index);
      await expect(row.getByText("Блокер", { exact: true })).toBeVisible();
      await expect(row.locator("span").last()).toHaveText(item.message);
      await expect(row.locator("code")).toHaveText(item.code);
      await row.scrollIntoViewIfNeeded();
      await expect(row).toBeVisible();
    }
    await summary.focus();
    await page.keyboard.press("Space");
    await expect(details).not.toHaveAttribute("open");
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`broker-source-warnings-${width}.png`),
      fullPage: true,
    });
  }
  expect(writes).toEqual([]);
});

for (const outcome of ["success", "expired", "ambiguous"] as const) {
  test(`ui-v2 current-day quote preview ${outcome} is explicit and never blindly retried`, async ({
    page,
  }, testInfo) => {
    const calls = await installApi(page);
    const money = (amount: string) => ({ amount, currency: "RUB" });
    const position = {
      id: 31,
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      quantity: "1.000000",
      average_cost_per_unit: money("100.00"),
      market_price_per_unit: money("100.00"),
      market_value: money("100.00"),
      cost_basis: money("100.00"),
      unrealized_result: money("0.00"),
      accrued_interest: money("15.00"),
      price_source: "manual",
      price_date: "2030-04-30",
      updated_at: "2030-04-30T12:00:00Z",
      notes: null,
    };
    let saved = position;
    let previewCalls = 0;
    let applyCalls = 0;
    await page.route("**/api/months/7", (route) =>
      route.fulfill({ json: { ...closed, status: "draft" } }),
    );
    await page.route("**/api/accounts", (route) =>
      route.fulfill({
        json: [
          {
            id: 11,
            name: "Synthetic Broker",
            account_type: "brokerage",
            status: "active",
            include_in_capital: true,
            include_in_returns: true,
          },
        ],
      }),
    );
    await page.route("**/api/instruments?active=true", (route) =>
      route.fulfill({
        json: [
          {
            id: 21,
            name: "Synthetic Stock",
            ticker: "SYN",
            instrument_type: "stock",
            currency: "RUB",
            is_active: true,
            manual_price_allowed: true,
          },
        ],
      }),
    );
    await page.route("**/api/positions?month_id=7", (route) => route.fulfill({ json: [saved] }));
    await page.route("**/api/months/7/quote-preview", async (route) => {
      previewCalls++;
      await route.fulfill({
        json: {
          reporting_month_id: 7,
          month_status: "draft",
          target_date: "2030-04-30",
          month_editable: true,
          batch_error: null,
          batch_error_reason: null,
          preview_id: "synthetic-preview",
          rows: [
            {
              position_snapshot_id: 31,
              account_id: 11,
              instrument_id: 21,
              instrument_name: "Synthetic Stock",
              instrument_type: "stock",
              mapping_state: "mapped",
              identity: {
                provider: "t_invest",
                provider_instrument_id: "synthetic",
                provider_venue_id: null,
              },
              current_market_price_per_unit: money("100.00"),
              current_price_date: "2030-04-30",
              current_price_source: "manual",
              proposed_market_price_per_unit: money("110.00"),
              proposed_price_date: "2030-04-30",
              proposed_quote_kind: "last",
              proposed_raw_price: "110.00",
              proposed_raw_price_basis: "R",
              fetched_at_utc: "2030-04-30T12:00:00Z",
              freshness_status: "ok",
              status: "ok",
              failure_reason: null,
              message: null,
              apply_allowed: true,
            },
          ],
        },
      });
    });
    await page.route("**/api/months/7/quote-apply", async (route) => {
      applyCalls++;
      expect(route.request().postDataJSON()).toMatchObject({
        preview_id: "synthetic-preview",
        rows: [
          {
            position_snapshot_id: 31,
            expected_market_price_per_unit: money("110.00"),
            expected_quote_kind: "last",
          },
        ],
      });
      if (outcome === "expired") {
        await route.fulfill({
          status: 409,
          json: { error: { code: "preview_evidence_invalid", message: "synthetic", details: [] } },
        });
        return;
      }
      saved = {
        ...position,
        market_price_per_unit: money("110.00"),
        market_value: money("125.00"),
        price_source: "t_invest",
      };
      if (outcome === "ambiguous") {
        await route.abort("failed");
        return;
      }
      await route.fulfill({
        json: {
          reporting_month_id: 7,
          applied_count: 1,
          rows: [
            {
              position_snapshot_id: 31,
              market_price_per_unit: saved.market_price_per_unit,
              price_source: saved.price_source,
              price_date: saved.price_date,
              accrued_interest: saved.accrued_interest,
              market_value: saved.market_value,
              unrealized_result: money("25.00"),
              freshness: "ok",
            },
          ],
        },
      });
    });
    await page.goto("/v2/data/months/7?section=positions#month-quotes");
    await expect(page.getByRole("heading", { name: "Позиции", exact: true })).toBeVisible();
    expect(previewCalls).toBe(0);
    expect(applyCalls).toBe(0);
    expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
    await page.getByRole("button", { name: "Обновить котировки" }).click();
    await page.getByRole("button", { name: "Применить выбранные" }).click();
    if (outcome === "success") {
      await expect(page.getByText(/Котировки применены: 1/)).toBeVisible();
    } else {
      await expect(
        page.getByText(
          outcome === "expired"
            ? /Предпросмотр больше недействителен/
            : /Результат применения не подтверждён/,
        ),
      ).toBeVisible();
      await expect(page.getByText(/Котировки применены: 1/)).toHaveCount(0);
    }
    await expect(page.getByRole("button", { name: "Применить выбранные" })).toHaveCount(0);
    expect(applyCalls).toBe(1);
    expect(previewCalls).toBe(1);
    const screenshotDir = path.resolve(".visual-audit", testInfo.project.name);
    fs.mkdirSync(screenshotDir, { recursive: true });
    await page.screenshot({
      path: path.join(screenshotDir, `ui-v2-quote-${outcome}.png`),
      fullPage: true,
    });
    await page.reload();
    await expect(page.getByRole("button", { name: "Обновить котировки" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Применить выбранные" })).toHaveCount(0);
    expect(previewCalls).toBe(1);
    expect(applyCalls).toBe(1);
  });
}

async function installApi(
  page: Page,
  overrides: {
    debts?: object[];
    accounts?: object[];
    properties?: object[];
    month?: typeof closed;
  } = {},
) {
  let month = { ...(overrides.month ?? closed) };
  const calls: string[] = [];
  const expenses: object[] = [];
  const money = { amount: "0.00", currency: "RUB" };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith("/api/")) {
      await route.continue();
      return;
    }
    calls.push(`${request.method()} ${path}`);
    if (path === "/api/months" && request.method() === "GET") {
      await route.fulfill({ json: [month] });
    } else if (path === "/api/months/7/close-workflow") {
      const workflow = makeUiV2Workflow();
      workflow.month = { ...workflow.month, ...month, status: month.status as "draft" | "closed" };
      if (workflow.final_review.available) workflow.final_review.month_header = workflow.month;
      await route.fulfill({ json: workflow });
    } else if (path === "/api/months/7" && request.method() === "GET") {
      await route.fulfill({ json: month });
    } else if (path === "/api/months/7" && request.method() === "PATCH") {
      month = { ...month, ...request.postDataJSON() };
      await route.fulfill({ json: month });
    } else if (path === "/api/months/7/reopen" && request.method() === "POST") {
      month = { ...month, status: "draft" };
      await route.fulfill({ json: month });
    } else if (path === "/api/months/7/summary") {
      await route.fulfill({
        json: {
          month,
          salary_tax: { tax: money, calculated_net: money },
          salary_actual_net: money,
          coverage: { coverage_pct: null },
        },
      });
    } else if (path === "/api/months/7/dashboard") {
      await route.fulfill({
        json: { month, mortgage: null, summary: { liquid_capital: { linked_pairs: [] } } },
      });
    } else if (path === "/api/cash-balances/total") {
      await route.fulfill({
        json: { reporting_month_id: 7, total: money, total_in_capital: money },
      });
    } else if (path === "/api/expenses") {
      if (request.method() === "POST") {
        const row = { id: expenses.length + 1, is_recurring: false, ...request.postDataJSON() };
        expenses.push(row);
        await route.fulfill({ json: row });
      } else await route.fulfill({ json: expenses });
    } else if (path === "/api/debts" && request.method() === "GET" && overrides.debts) {
      await route.fulfill({ json: overrides.debts });
    } else if (path === "/api/accounts" && request.method() === "GET" && overrides.accounts) {
      await route.fulfill({ json: overrides.accounts });
    } else if (path === "/api/properties" && request.method() === "GET" && overrides.properties) {
      await route.fulfill({ json: overrides.properties });
    } else if (
      [
        "/api/broker-months/intakes",
        "/api/incomes",
        "/api/accounts",
        "/api/instruments",
        "/api/deposits",
        "/api/cash-balances",
        "/api/debts",
        "/api/properties",
        "/api/positions",
        "/api/investment-flows",
        "/api/expected-flows",
        "/api/savings",
        "/api/planned-budget",
        "/api/planned-budget/comparison",
      ].includes(path) &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: [] });
    } else if (path === "/api/comments" && request.method() === "GET") {
      await route.fulfill({ json: [] });
    } else {
      await route.fulfill({
        status: 404,
        json: { error: { code: "not_found", message: "synthetic", details: [] } },
      });
    }
  });
  return calls;
}

test("browser Back keeps an unsaved month until the user confirms", async ({ page }) => {
  await installApi(page);
  await page.goto("/v2/data/months");
  await page.goto("/v2/data/months/7");
  await expect(page.getByLabel("Дата снимка")).toBeDisabled();
  await page.getByRole("button", { name: "Открыть для редактирования" }).click();
  await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
  await page.getByLabel("Дата снимка").fill("2030-04-29");
  page.once("dialog", (dialog) => void dialog.dismiss());
  await page.evaluate(() => window.history.back());
  await expect(page.getByLabel("Дата снимка")).toHaveValue("2030-04-29");
  await expect(page).toHaveURL(/\/v2\/data\/months\/7$/);
  page.once("dialog", (dialog) => void dialog.accept());
  await page.evaluate(() => window.history.back());
  await expect(page).toHaveURL(/\/v2\/data\/months$/);
});

test("saving removes the history guard and Back returns to the month list", async ({ page }) => {
  await installApi(page);
  await page.goto("/v2/data/months");
  await page.goto("/v2/data/months/7");
  await page.getByRole("button", { name: "Открыть для редактирования" }).click();
  await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
  await page.getByLabel("Дата снимка").fill("2030-04-29");
  await page.getByRole("button", { name: "Сохранить общие данные" }).click();
  await expect(page.getByText("Общие данные сохранены и подтверждены.")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => window.history.state?.monthEditorDirtyGuard ?? null))
    .toBeNull();
  await page.evaluate(() => window.history.back());
  await expect(page).toHaveURL(/\/v2\/data\/months$/);
});

for (const width of [1280]) {
  test(
    `native month editor ${width}px and keyboard`,
    { tag: "@viewport-owned" },
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const calls = await installApi(page);
      await page.goto("/v2/data/months/7?from=monthly-close-v2&monthId=7&step=month_setup");
      await expect(page.getByRole("heading", { level: 1, name: "Редактор месяца" })).toBeVisible();
      await expect(page.getByTestId("data-month-context").getByText("Апрель 2030")).toBeVisible();
      await expect(page.getByLabel("Дата снимка")).toBeDisabled();
      await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
        "href",
        "/v2/close?month=7&step=month_setup",
      );
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => document.activeElement?.tagName)).toBe("A");
      await page.getByRole("button", { name: "Открыть для редактирования" }).click();
      await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
      await expect(page.getByLabel("Дата снимка")).toBeEnabled();
      expect(calls.filter((call) => call === "GET /api/months/7").length).toBeGreaterThanOrEqual(2);
      expect(calls).toContain("POST /api/months/7/reopen");
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`month-editor-${width}.png`),
        fullPage: true,
      });
    },
  );
}

const leaves = [
  ["income", "Зарплата и прочее", "Зарплата и прочее"],
  ["assets", "Активы", "Депозиты"],
  ["positions", "Позиции", "Позиции"],
  ["payouts", "Выплаты", "Фактические потоки"],
  ["budget", "Бюджет", "Расходы"],
  ["liabilities", "Долги и недвижимость", "Долги"],
] as const;

for (const [id, , heading] of leaves) {
  test(`deep link ${id} uses exact CLOSED month`, async ({ page }) => {
    const calls = await installApi(page);
    await page.goto(`/v2/data/months/7?section=${id}`);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(page.getByTestId("data-month-context")).toContainText("Апрель 2030");
    // Closed leaves expose no enabled mutation fields; filters remain available.
    const inputs = page.locator(
      'main input:not([type="search"]):not(#payout-exp-version), main textarea',
    );
    for (const input of await inputs.all()) await expect(input).toBeDisabled();
    expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
    expect(calls).toContain("GET /api/months/7");
  });
}

for (const width of [1280]) {
  test(
    `aggregate six leaves write readback navigation ${width}px`,
    { tag: "@viewport-owned" },
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const calls = await installApi(page);
      await page.goto(
        "/v2/data/months/7?from=monthly-close-v2&monthId=7&step=month_setup&extra=keep#editor",
      );
      await page.getByRole("button", { name: "Открыть для редактирования" }).click();
      await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
      await expect(page.getByLabel("Дата снимка")).toBeEnabled();
      const tabs = page.getByRole("navigation", { name: "Разделы редактора месяца" });
      for (const [id, label, heading] of leaves) {
        await tabs.getByRole("link", { name: label, exact: true }).focus();
        await page.keyboard.press("Enter");
        await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
        const writeField = {
          income: "Премия",
          assets: "Название вклада",
          positions: "Количество",
          payouts: "Брутто",
          budget: "Категория расхода",
          liabilities: "Название долга",
        }[id];
        await expect(page.getByLabel(writeField, { exact: true })).toBeEnabled();
        const url = new URL(page.url());
        expect(url.pathname).toBe("/v2/data/months/7");
        expect(url.searchParams.get("section")).toBe(id);
        expect(url.searchParams.get("extra")).toBe("keep");
        expect(url.hash).toBe("#editor");
        await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
          "href",
          "/v2/close?month=7&step=month_setup",
        );
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        ).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`${id}-${width}.png`), fullPage: true });
      }
      await tabs.getByRole("link", { name: "Бюджет", exact: true }).click();
      await page.getByLabel("Категория расхода", { exact: true }).fill("Синтетический расход");
      await page.getByLabel("Сумма расхода", { exact: true }).fill("123.45");
      await tabs.getByRole("link", { name: "Активы", exact: true }).click();
      await expect(page.getByRole("alertdialog")).toBeVisible();
      await page.getByRole("button", { name: "Остаться", exact: true }).click();
      await expect(page.getByLabel("Сумма расхода", { exact: true })).toHaveValue("123.45");
      await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
      await expect(page.getByText("Расход сохранён и подтверждён.")).toBeVisible();
      const write = calls.indexOf("POST /api/expenses");
      expect(write).toBeGreaterThan(-1);
      expect(calls.slice(write + 1)).toContain("GET /api/expenses");
      expect(calls.slice(write + 1)).toContain("GET /api/months/7");
      await expect(
        page.getByRole("cell", { name: "Синтетический расход", exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`budget-readback-${width}.png`),
        fullPage: true,
      });
      await tabs.getByRole("link", { name: "Активы", exact: true }).click();
      await tabs.getByRole("link", { name: "Бюджет", exact: true }).click();
      await expect(
        page.getByRole("cell", { name: "Синтетический расход", exact: true }),
      ).toBeVisible();
    },
  );
}

test("invalid and duplicate sections fail closed", async ({ page }) => {
  await installApi(page);
  for (const query of ["section=unknown", "section=income&section=budget", "section=constructor"]) {
    await page.goto(`/v2/data/months/7?${query}`);
    await expect(page.getByText("Неизвестный раздел. Выбери раздел редактора.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Зарплата и прочее", exact: true })).toHaveCount(
      0,
    );
  }
});

test("dirty leaf guards link, tab, beforeunload and browser Back", async ({ page }) => {
  await installApi(page);
  await page.goto("/v2/data/months");
  await page.goto("/v2/data/months/7");
  await page.getByRole("button", { name: "Открыть для редактирования" }).click();
  await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Разделы редактора месяца" })
    .getByRole("link", { name: "Бюджет", exact: true })
    .click();
  await page.getByLabel("Категория расхода", { exact: true }).fill("Черновик");
  expect(
    await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    }),
  ).toBe(true);
  await page.getByRole("link", { name: "← Отчётные месяцы" }).click();
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  page.once("dialog", (dialog) => void dialog.dismiss());
  await page.evaluate(() => window.history.back());
  await expect(page.getByLabel("Категория расхода", { exact: true })).toHaveValue("Черновик");
  page.once("dialog", (dialog) => void dialog.accept());
  await page.evaluate(() => window.history.back());
  await expect(page.getByLabel("Дата снимка")).toBeVisible();
  await page
    .getByRole("navigation", { name: "Разделы редактора месяца" })
    .getByRole("link", { name: "Бюджет", exact: true })
    .click();
  await page.getByLabel("Категория расхода", { exact: true }).fill("Отбросить");
  await page
    .getByRole("navigation", { name: "Разделы редактора месяца" })
    .getByRole("link", { name: "Активы", exact: true })
    .click();
  await page.getByRole("button", { name: "Перейти без сохранения", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Депозиты", exact: true })).toBeVisible();
});

for (const width of [1280]) {
  test(
    `#650 debt stacked editor ${width}px keeps Save/Cancel reachable without horizontal page scroll`,
    { tag: "@viewport-owned" },
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const longAccount = `Синтетический очень длинный накопительный счёт ${"· подразделение ".repeat(6)}`;
      // One catch-all mock serves the #650 fixtures: no overlapping routes.
      await installApi(page, {
        debts: [
          {
            id: 1,
            reporting_month_id: 7,
            debt_type: "credit_card",
            name: "Основная карта с очень длинным названием для проверки переноса",
            current_balance: { amount: "1234567890.50", currency: "RUB" },
            include_in_liquid_capital: true,
            linked_account_id: null,
            annual_rate: "19.90",
            next_due_date: "2030-06-20",
            contract_end_date: null,
            notes: null,
          },
        ],
        accounts: [
          {
            id: 11,
            name: longAccount,
            account_type: "deposit",
            status: "active",
            external_code: null,
            include_in_capital: true,
            include_in_returns: true,
            notes: null,
          },
        ],
        properties: [],
      });

      await page.goto("/v2/data/months");
      await page.goto("/v2/data/months/7");
      await page.getByRole("button", { name: "Открыть для редактирования" }).click();
      await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
      await page
        .getByRole("navigation", { name: "Разделы редактора месяца" })
        .getByRole("link", { name: "Долги и недвижимость", exact: true })
        .click();
      await expect(page.getByRole("heading", { name: "Долги", exact: true })).toBeVisible();

      // Owner language, no technical shorthand; money is one unit.
      await expect(page.getByText("Кредитные карты:", { exact: false })).toBeVisible();
      await expect(page.getByText("Долг по кредитным картам:", { exact: false })).toBeVisible();
      expect(await page.getByText("CC ", { exact: false }).count()).toBe(0);
      expect(await page.locator(".money").count()).toBeGreaterThan(0);

      // Open the stacked editor below the readonly row.
      await page.getByRole("button", { name: /Изменить долг/ }).click();
      const editor = page.getByRole("form", { name: /Редактирование долга/ });
      await expect(editor).toBeVisible();
      await expect(editor.getByLabel("Название долга")).toBeVisible();
      await expect(editor.getByLabel("Текущий баланс долга")).toBeVisible();
      await expect(editor.getByRole("button", { name: "Сохранить", exact: true })).toBeVisible();
      await expect(editor.getByRole("button", { name: "Отмена" })).toBeVisible();
      await expect(
        page.getByText("Итоги ниже посчитаны по сохранённым данным", { exact: false }),
      ).toBeVisible();

      // Save/Cancel are reachable with vertical scroll only: no page-level horizontal scrolling.
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      ).toBe(true);
      for (const label of ["Название долга", "Текущий баланс долга", "Годовая ставка, %"]) {
        await editor.getByLabel(label).scrollIntoViewIfNeeded();
        await expect(editor.getByLabel(label)).toBeVisible();
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
        ).toBe(true);
      }
      await editor.getByRole("button", { name: "Сохранить", exact: true }).scrollIntoViewIfNeeded();
      await expect(editor.getByRole("button", { name: "Сохранить", exact: true })).toBeVisible();
      await editor.getByRole("button", { name: "Отмена" }).scrollIntoViewIfNeeded();
      await expect(editor.getByRole("button", { name: "Отмена" })).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      ).toBe(true);

      // Keyboard reaches Save/Cancel.
      await editor.getByLabel("Название долга").focus();
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");

      await page.screenshot({
        path: testInfo.outputPath(`debt-stacked-editor-${width}.png`),
        fullPage: true,
      });

      // Link editor keeps the same reachable treatment with a long account name.
      await editor.getByRole("button", { name: "Отмена" }).click();
      await page.getByRole("button", { name: "Связать счёт" }).click();
      const linkEditor = page.getByRole("form", { name: /Связь долга/ });
      await expect(linkEditor).toBeVisible();
      await linkEditor.scrollIntoViewIfNeeded();
      await expect(linkEditor.getByLabel("Счёт для связи с долгом")).toBeVisible();
      await expect(linkEditor.getByRole("button", { name: "Сохранить связь" })).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`debt-link-editor-${width}.png`),
        fullPage: true,
      });
    },
  );
}

const uxName =
  "Синтетическая облигация с очень длинным названием эмитента и дополнительными условиями выпуска серии 2030";
const uxMoney = (amount: string) => ({ amount, currency: "RUB" });
const uxAccount = {
  id: 11,
  name: "Синтетический брокерский счёт",
  account_type: "brokerage",
  status: "active",
  include_in_capital: true,
  include_in_returns: true,
};
const uxInstrument = {
  id: 21,
  name: uxName,
  ticker: "SYN",
  isin: ISIN,
  instrument_type: "bond",
  currency: "RUB",
  is_active: true,
  manual_price_allowed: true,
};
const uxActual = {
  id: 41,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  flow_type: "coupon",
  event_date: "2030-05-15",
  gross_amount: null,
  tax_amount: null,
  commission_amount: null,
  net_amount: uxMoney("860.00"),
  currency: "RUB",
  source: "broker_statement_native",
  amount_basis: "broker_statement_net_v1",
  statement_link: null,
};

async function installMonthUx(page: Page, status = "draft") {
  const calls = await installApi(page, {
    month: { ...closed, month: 5, snapshot_date: "2030-05-31", status },
    accounts: [uxAccount],
    properties: [
      {
        id: 2,
        reporting_month_id: 7,
        name: "Синтетическая квартира",
        estimated_value: uxMoney("7000000.00"),
        mortgage_balance: uxMoney("3000000.00"),
        monthly_payment: uxMoney("50000.00"),
        mortgage_annual_rate: null,
      },
    ],
  });
  await page.route("**/api/instruments?*", (route) => route.fulfill({ json: [uxInstrument] }));
  await page.route("**/api/positions?*", (route) =>
    route.fulfill({
      json: [
        {
          id: 31,
          reporting_month_id: 7,
          account_id: 11,
          instrument_id: 21,
          quantity: "123.456789",
          average_cost_per_unit: uxMoney("12345.67"),
          market_price_per_unit: uxMoney("13456.78"),
          market_value: uxMoney("1661330.85"),
          cost_basis: uxMoney("1524156.78"),
          unrealized_result: uxMoney("137174.07"),
          accrued_interest: null,
          price_source: "manual",
          price_date: "2030-05-31",
        },
      ],
    }),
  );
  await page.route("**/api/investment-flows?*", (route) => route.fulfill({ json: [uxActual] }));
  await page.route("**/api/expected-flows?*", (route) =>
    route.fulfill({
      json: [
        {
          id: 51,
          reporting_month_id: 7,
          account_id: 11,
          instrument_id: 21,
          flow_type: "coupon",
          expected_date: "2030-06-15",
          gross_amount: uxMoney("500.00"),
          expected_tax_amount: null,
          expected_net_amount: uxMoney("435.00"),
          currency: "RUB",
          source: "manual",
          forecast_version: "v1",
          is_confirmed: false,
          is_approximate: true,
        },
      ],
    }),
  );
  await page.route("**/api/broker-months*", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/source-intakes*", (route) => route.fulfill({ json: [] }));
  return calls;
}

async function expectNoTableOverflow(page: Page) {
  const geometry = await page
    .locator("main .table-wrap")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({ width: node.clientWidth, scroll: node.scrollWidth })),
    );
  for (const table of geometry) expect(table.scroll).toBeLessThanOrEqual(table.width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  // Numbers must fit their own cells, not merely a hidden outer container.
  const clipped = await page
    .locator("main td.num")
    .evaluateAll((cells) =>
      cells
        .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
        .map((cell) => cell.textContent),
    );
  expect(clipped).toEqual([]);
}

test("ui-v2 Month UX positions payouts property desktop 100 and 125 percent @viewport-owned", async ({
  page,
}, testInfo) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/") && request.method() !== "GET")
      writes.push(request.url());
  });
  await installMonthUx(page);
  for (const width of [1280, 1440, 1920]) {
    for (const zoom of [1, 1.25]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto("/v2/close?month=7&panel=positions");
      // CSS zoom exercises layout/reflow at the requested desktop scale; not native browser chrome.
      await page.evaluate((scale) => {
        document.documentElement.style.zoom = String(scale);
      }, zoom);
      await expect(page.getByRole("heading", { name: "Позиции", exact: true })).toBeVisible();
      await expectNoTableOverflow(page);
      const fullName = page.getByRole("button", { name: `Полное название: ${uxName} (SYN)` });
      await fullName.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("tooltip")).toHaveText(`${uxName} (SYN)`);
      await page.keyboard.press("Escape");
      await page.screenshot({
        path: testInfo.outputPath(`month-positions-${width}-${zoom}.png`),
        fullPage: true,
      });
      const nav = page.getByRole("navigation", { name: "Разделы месяца" });
      await nav.getByRole("link", { name: /Долги, кредитка и недвижимость/ }).click();
      const payment = page.locator("#prop-pay");
      const rate = page.locator("#prop-rate");
      await expect(payment).toBeVisible();
      await expect(rate).toHaveAccessibleDescription(/Пустая ставка — неизвестно/);
      const payBox = await payment.boundingBox();
      const rateBox = await rate.boundingBox();
      expect(payBox).not.toBeNull();
      expect(rateBox).not.toBeNull();
      expect(Math.abs((payBox?.y ?? 0) - (rateBox?.y ?? 0))).toBeLessThan(2);
      expect((payBox?.x ?? 0) + (payBox?.width ?? 0)).toBeLessThan(rateBox?.x ?? 0);
      await page.getByRole("button", { name: /Изменить объект/ }).click();
      const editor = page.getByRole("region", { name: "Изменение объекта недвижимости" });
      await expect(editor.getByLabel("Ежемесячный платёж")).toBeVisible();
      await expectNoTableOverflow(page);
      await page.screenshot({
        path: testInfo.outputPath(`month-property-${width}-${zoom}.png`),
        fullPage: true,
      });
      await page.getByRole("button", { name: "Отмена", exact: true }).click();
      await nav.getByRole("link", { name: /^Выплаты/ }).click();
      await expect(page.getByRole("heading", { name: "Фактические потоки" })).toBeVisible();
      await expect(page.locator("#payout-act-gross")).not.toBeVisible();
      await expectNoTableOverflow(page);
      await page.screenshot({
        path: testInfo.outputPath(`month-payouts-${width}-${zoom}.png`),
        fullPage: true,
      });
    }
  }
  expect(writes).toEqual([]);
});

test("ui-v2 Month payout entry source actual forecast historical date Back Reload and dirty guards @viewport-owned", async ({
  page,
}, testInfo) => {
  const writes: string[] = [];
  const previewBodies: object[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") && request.method() !== "GET") writes.push(url.pathname);
  });
  await installMonthUx(page);
  const sourceRows = ["SYNTH-01", "SYNTH-02"].map((account, i) => ({
    id: i + 1,
    head_seq: 2,
    manifest_digest: "a".repeat(64),
    covered_from: "2030-05-01",
    covered_to: "2030-05-31",
    contract_version: "source_intake_v1",
    generation: 1,
    document_sha256: "a".repeat(64),
    original_required: true,
    financial_authority: "none",
    finance_link: null,
    history: [],
    proposals: [],
    state: {
      reporting_month_id: null,
      account_id: null,
      default_enabled: true,
      account_currency: null,
      policy_revision: 1,
      overrides: {},
      instrument_decisions: [],
      deferred_isins: [],
    },
    document: {
      provider: "mybroker",
      parser: "mybroker-s1-v2",
      document_sha256: "a".repeat(64),
      filename_account: account,
      source_accounts: [`${account}-000`],
      covered_from: "2030-05-01",
      covered_to: "2030-05-31",
      positions: [],
      trades: [],
      money: [],
      rub_money: [],
      section_inventory: {},
    },
    observations: [],
    exceptions: [],
  }));
  await page.route("**/api/broker-months/intakes*", (route) => route.fulfill({ json: sourceRows }));
  await page.route("**/api/source-returns/instruments?*", (route) => {
    const account = new URL(route.request().url()).searchParams.get("source_account") ?? "";
    const data = source(account);
    data.instruments[0].source_name = uxName;
    data.instruments[0].analysis.events = [
      event({ net_payout_kopecks: 86000, native_source_account: `${account}-000` }),
    ];
    return route.fulfill({ json: data });
  });
  await page.route("**/api/source-returns/quantity-bases?*", (route) => {
    const q = new URL(route.request().url()).searchParams;
    const account = q.get("source_account");
    return route.fulfill({
      json: {
        source_account: account,
        native_source_account: `${account}-000`,
        isin: ISIN,
        on_or_before: "2030-05-31",
        authority: "provisional",
        financial_authority: "none",
        bases: [
          {
            as_of: "2030-04-30",
            quantity: "2.5",
            reason_codes: [],
            quantity_references: ["position:1:0:closing"],
          },
        ],
      },
    });
  });
  await page.route("**/api/source-returns/payout-preview", async (route) => {
    const body = route.request().postDataJSON();
    previewBodies.push(body);
    await route.fulfill({
      json: {
        source_account: body.source_account,
        native_source_account: `${body.source_account}-000`,
        isin: ISIN,
        as_of: body.as_of,
        authority: "provisional",
        financial_authority: "none",
        account_id: null,
        instrument_id: 21,
        quantity: "2.5",
        quantity_authority: "source_observed",
        assumptions: ["fixed_source_quantity_not_entitlement"],
        quantity_references: ["position:1:0:closing"],
        source_references: source().instruments[0].analysis.source_references,
        dependency_fingerprint: "synthetic",
        reason_codes: [],
        provider: "t_invest",
        instrument_uid: "synthetic",
        actuals: [event({ net_payout_kopecks: 86000 })],
        reconciliation_reasons: [],
        failures: [],
        rows: [
          {
            identity_key: "future-1",
            event_kind: "coupon",
            payment_date: "2030-07-01",
            provider_status: "ok",
            source_method: "GetBondCoupons",
            per_unit_amount: "1.23",
            currency: "RUB",
            announced_amount_kopecks: "308",
            personal_tax_known: false,
            status: "future",
            countable_future: true,
            actual_event_keys: [],
            reason_codes: [],
          },
        ],
      },
    });
  });
  await page.goto(`/v2/close?month=7&source_account=SYNTH-01&instrument_isin=${ISIN}`);
  const nav = page.getByRole("navigation", { name: "Разделы месяца" });
  await expect(nav).toBeVisible();
  const order = await nav
    .getByRole("link")
    .evaluateAll((links) =>
      links.map((link) => new URL((link as HTMLAnchorElement).href).searchParams.get("panel")),
    );
  expect(order.indexOf("brokers")).toBeLessThan(order.indexOf("positions"));
  await nav.getByRole("link", { name: /^Выплаты/ }).click();
  await expect(page.getByRole("region", { name: "Наблюдения выплат источника" })).toContainText(
    "Налог: неизвестен",
  );
  await expect(page.locator("#month-accepted-payouts .totals-bar").first()).toContainText("860");
  await expect(page.locator("#month-accepted-payouts .totals-bar").first()).not.toContainText(
    "1 720",
  );
  const dates = page.getByLabel("Сохранённая дата количества");
  await dates.selectOption("2030-04-30");
  await expect(page).toHaveURL(/payout_as_of=2030-04-30/);
  await expect(page.getByText(/не заменяет закрывающий EOD 2030-05-31/)).toBeVisible();
  expect(previewBodies).toEqual([]);
  await page.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" }).click();
  await expect(page.getByRole("region", { name: "Будущие кандидаты (future)" })).toBeVisible();
  expect(previewBodies).toHaveLength(1);
  expect(previewBodies[0]).toMatchObject({
    source_account: "SYNTH-01",
    isin: ISIN,
    as_of: "2030-04-30",
  });
  await page.screenshot({
    path: testInfo.outputPath("month-payout-source-actual-future.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(dates).toHaveValue("2030-04-30");
  await expect(page.getByRole("region", { name: "Будущие кандидаты (future)" })).toHaveCount(0);
  expect(previewBodies).toHaveLength(1);
  await nav.getByRole("link", { name: /Брокерские выписки/ }).click();
  await page.getByText("Исправления и сохранение месяца", { exact: true }).click();
  await page.getByLabel("Сохранённый разбор").selectOption("1");
  await page.getByLabel("Валюта предложения счёта").fill("RUB");
  await nav.getByRole("link", { name: /^Выплаты/ }).click();
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.getByLabel("Валюта предложения счёта")).toHaveValue("RUB");
  await nav.getByRole("link", { name: /^Выплаты/ }).click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/panel=payouts/);
  await page.goBack();
  await expect(page).toHaveURL(/panel=brokers/);
  await page.getByText("Исправления и сохранение месяца", { exact: true }).click();
  await expect(page.getByLabel("Валюта предложения счёта")).toHaveValue("");
  await nav.getByRole("link", { name: /^Выплаты/ }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await page.getByText("Добавить фактическую выплату вручную", { exact: true }).click();
  await page.locator("#payout-act-gross").fill("100");
  await nav.getByRole("link", { name: /Счета и позиции/ }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(1);
  await expect(page.getByRole("alertdialog")).toContainText("Несохранённые изменения");
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.locator("#payout-act-gross")).toHaveValue("100");
  await nav.getByRole("link", { name: /Счета и позиции/ }).click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/panel=positions/);
  await page.goBack();
  await expect(page).toHaveURL(/panel=payouts/);
  await expect(dates).toHaveValue("2030-04-30");
  expect(previewBodies).toHaveLength(1);
  expect(writes).toEqual(["/api/source-returns/payout-preview"]);
});

test("ui-v2 Month payout entry keeps CLOSED records read-only without background writes", async ({
  page,
}) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/") && request.method() !== "GET")
      writes.push(request.url());
  });
  await installMonthUx(page, "closed");
  await page.goto("/v2/close?month=7&panel=payouts");
  await expect(page.getByRole("heading", { name: "Фактические потоки" })).toBeVisible();
  await expect(page.locator("#month-accepted-payouts")).toContainText("860");
  await expect(page.locator("#payout-act-gross")).toHaveCount(0);
  await expect(page.locator("#payout-exp-gross")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Добавить выплату", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Фактические потоки" })).toBeVisible();
  expect(writes).toEqual([]);
});

test("ui-v2 Month UX legacy same-panel discard resets the manual draft and guard", async ({
  page,
}) => {
  await installMonthUx(page);
  await page.goto("/v2/close?month=7&section=payouts");
  await page.getByText("Добавить фактическую выплату вручную", { exact: true }).click();
  await page.locator("#payout-act-gross").fill("123");
  const nav = page.getByRole("navigation", { name: "Разделы месяца" });
  await nav.getByRole("link", { name: /^Выплаты/ }).click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/panel=payouts/);
  await page.getByText("Добавить фактическую выплату вручную", { exact: true }).click();
  await expect(page.locator("#payout-act-gross")).toHaveValue("");
  await page.locator("#payout-act-gross").fill("456");
  await nav.getByRole("link", { name: /Счета и позиции/ }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(1);
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.locator("#payout-act-gross")).toHaveValue("456");
});
