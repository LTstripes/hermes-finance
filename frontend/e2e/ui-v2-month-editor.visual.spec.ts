import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const closed = {
  id: 7,
  year: 2030,
  month: 4,
  status: "closed",
  snapshot_date: "2030-04-30",
  source: "manual",
};

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

async function installApi(page: Page) {
  let month = { ...closed };
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
    } else if (
      [
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

for (const width of [1280, 390]) {
  test(`native month editor ${width}px and keyboard`, async ({ page }, testInfo) => {
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
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`month-editor-${width}.png`),
      fullPage: true,
    });
  });
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

for (const width of [1280, 390]) {
  test(`aggregate six leaves write readback navigation ${width}px`, async ({ page }, testInfo) => {
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
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    if (width === 390) {
      const scroll = page.locator(".table-wrap").first();
      expect(await scroll.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
      await scroll.evaluate((el) => {
        el.scrollLeft = 100;
      });
      expect(await scroll.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    }
    await page.screenshot({
      path: testInfo.outputPath(`budget-readback-${width}.png`),
      fullPage: true,
    });
    await tabs.getByRole("link", { name: "Активы", exact: true }).click();
    await tabs.getByRole("link", { name: "Бюджет", exact: true }).click();
    await expect(
      page.getByRole("cell", { name: "Синтетический расход", exact: true }),
    ).toBeVisible();
  });
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
