import { expect, test, type Page } from "@playwright/test";

const closed = {
  id: 7,
  year: 2030,
  month: 4,
  status: "closed",
  snapshot_date: "2030-04-30",
  source: "manual",
};

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

for (const width of [1280, 390]) {
  test(`#650 debt stacked editor ${width}px keeps Save/Cancel reachable without page scroll`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const longAccount = `Синтетический очень длинный накопительный счёт ${"· подразделение ".repeat(6)}`;
    // Specific routes first: first matching route handles the request.
    await page.route("**/api/debts", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await route.fulfill({
        json: [
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
      });
    });
    await page.route("**/api/accounts", async (route) => {
      await route.fulfill({
        json: [
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
      });
    });
    await page.route("**/api/properties", async (route) => {
      if (route.request().method() === "GET") await route.fulfill({ json: [] });
      else await route.continue();
    });
    await installApi(page);

    await page.goto("/v2/data/months/7?section=liabilities");
    await page.getByRole("button", { name: "Открыть для редактирования" }).click();
    await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
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

    // Save/Cancel are reachable without page-level horizontal scrolling.
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ).toBe(true);
    for (const label of ["Название долга", "Текущий баланс долга", "Годовая ставка, %"]) {
      await expect(editor.getByLabel(label)).toBeInViewport();
    }
    await expect(editor.getByRole("button", { name: "Сохранить", exact: true })).toBeInViewport();
    await expect(editor.getByRole("button", { name: "Отмена" })).toBeInViewport();

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
    await expect(linkEditor.getByLabel("Счёт для связи с долгом")).toBeVisible();
    await expect(linkEditor.getByRole("button", { name: "Сохранить связь" })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`debt-link-editor-${width}.png`),
      fullPage: true,
    });
  });
}
