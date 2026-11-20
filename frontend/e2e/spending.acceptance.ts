import { expect, test } from "@playwright/test";

const month = "2026-10";
const header =
  "operationDate transactionDate accountName accountNumber cardName cardNumber merchant amount currency status category mcc type comment bonusValue bonusTitle".split(
    " ",
  );
function bankRow(
  day: string,
  description: string,
  amount: string,
  category = "Продукты",
  direction = "Списание",
  currency = "RUR",
) {
  return [
    `${day}.10.2026`,
    "",
    "Тестовый счёт",
    "SYNTHETIC-0001",
    "",
    "SYNTHETIC-CARD",
    description,
    amount,
    currency,
    "Выполнен",
    category,
    "",
    direction,
    "",
    "",
    "",
  ].join(",");
}
const statement = Buffer.from(
  [
    header.join(","),
    bankRow("01", "Начало месяца", "150"),
    bankRow("20", "Тестовый магазин", "500"),
    bankRow("21", "СБП Тестовый получатель", "350", "Переводы СБП"),
    bankRow("22", "Тестовый возврат", "30", "Продукты", "Пополнение"),
    bankRow("23", "Тестовая валюта", "12", "Продукты", "Списание", "EUR"),
  ].join("\n"),
);
const manual = Buffer.from(`---
finance_expenses: 1
month: ${month}
---

| Дата | Сумма | Категория | Описание | Оплата |
| --- | --- | --- | --- | --- |
| 20.10 | 500 | Продукты | Повтор из файла | альфа |
| 20.10 | 200 | Продукты | Рынок | нал |
| 20.10 | 80 | Продукты | Аптека | сбер |
`);

test("spending: CSV and Markdown, disappearance, manual decision, saved review and charts", async ({
  page,
}) => {
  await page.goto("/v2/spending");
  const nav = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(nav.getByRole("link", { name: "Расходы", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByTestId("spending-history")).toBeVisible();
  await page.getByRole("link", { name: "Загрузить траты" }).click();

  const uploads = page.getByLabel("Выписка Альфа-Банка (CSV)", { exact: true });
  await uploads.setInputFiles({
    name: "fixture.xlsx",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("fixture"),
  });
  await expect(page.getByRole("alert")).toContainText("Это файл Excel.");
  await expect(page.getByRole("button", { name: "Проверить" })).toBeDisabled();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать шаблон ручного файла" }).click();
  expect((await download).suggestedFilename()).toBe("finance-expenses-2026-10.md");

  await uploads.setInputFiles({
    name: "Statement 01.10.2026 - 31.10.2026.csv",
    mimeType: "text/csv",
    buffer: statement,
  });
  await page
    .getByLabel("Ручной файл (.md)", { exact: true })
    .setInputFiles({ name: "expenses.md", mimeType: "text/markdown", buffer: manual });
  await page.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByRole("heading", { name: "Что изменится в октябре 2026" })).toBeVisible();
  await expect(
    page.getByText("Исчезнет 1 ранее загруженная операция", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Старая покупка", { exact: false })).toBeVisible();
  const apply = page.getByRole("button", { name: "Применить", exact: true });
  await expect(apply).toBeDisabled();
  const duplicate = page.getByText("Пока ручная строка не входит в траты");
  await expect(duplicate).toHaveCount(1);
  await expect(page.locator('input[type="radio"]:checked')).toHaveCount(0);
  await expect(page.getByText("Тестовая валюта", { exact: false })).toBeVisible();
  const row = page
    .getByRole("radiogroup", { name: "Решение" })
    .filter({ has: page.getByRole("radio", { name: "Отдельная трата" }) })
    .locator("..");
  await row.getByRole("radio", { name: "Отдельная трата" }).click();
  await expect(page.getByText("✓ Отдельная трата")).toBeVisible();
  await expect(page.getByText("1 430 ₽", { exact: true }).first()).toBeVisible();
  const consent = page.getByRole("checkbox", {
    name: "Понимаю, эти операции будут удалены из трат",
  });
  await expect(consent).not.toBeChecked();
  await consent.check();
  await expect(apply).toBeEnabled();

  await page.getByRole("link", { name: "← К расходам" }).click();
  await expect(page.getByRole("alertdialog", { name: "Выйти без применения?" })).toBeVisible();
  await page.getByRole("button", { name: "Остаться" }).click();
  const ack = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().endsWith("/apply"),
  );
  const read = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith("/api/spending/months/2026-10"),
  );
  await apply.click();
  expect((await ack).ok()).toBe(true);
  expect((await read).ok()).toBe(true);
  await expect(page).toHaveURL(/\/v2\/spending\?month=2026-10$/);
  await expect(page.getByRole("status").filter({ hasText: /Октябрь.*обновлён/ })).toBeVisible();
  await expect(page.getByTestId("spending-history")).toBeVisible();
  await expect(page.getByTestId("spending-daily")).toBeVisible();
  await expect(page.getByText("Выписка + ручной файл", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Таблица" }).click();
  await expect(page.getByRole("columnheader", { name: "Обязательные" })).toBeVisible();
  await page.getByRole("button", { name: /Сентябрь.*220.*только выписка/i }).click();
  await expect(page).toHaveURL(/month=2026-09/);
  await page.goBack();
  await expect(page).toHaveURL(/month=2026-10/);
  const category = page.getByRole("button", { name: /^Продукты/ });
  await category.click();
  await expect(category).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("spending-category-history")).toBeVisible();
  await page.goBack();
  await expect(category).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("combobox", { name: "Источник", exact: true }).selectOption("cash");
  await expect(page).toHaveURL(/source=cash/);
  await expect(page.getByText(/Показано 1 операция на/)).toBeVisible();

  await page.getByRole("link", { name: "Разобрать" }).click();
  await expect(page).toHaveURL(/review=1/);
  await expect(page.getByRole("heading", { name: "Переводы" })).toBeVisible();
  const transfer = page
    .getByRole("radiogroup", { name: "Решение" })
    .filter({ has: page.getByRole("radio", { name: "Трата…" }) })
    .locator("..");
  await transfer.getByRole("radio", { name: "Не трата" }).click();
  await expect(page.getByText(/✓ Не трата · запомнится/)).toBeVisible();
  await page.getByRole("link", { name: "← К расходам" }).click();
  await page.getByRole("link", { name: "Категории и правила" }).click();
  await expect(page.getByRole("heading", { name: "Правила по продавцу" })).toBeVisible();
  const categoryType = page.getByRole("combobox", { name: "Тип: Продукты" });
  await categoryType.selectOption("mandatory");
  await expect(categoryType).toHaveValue("mandatory");
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Правила по продавцу" })).toHaveCount(0);
});

test("annual payment note persists, projects a monthly amount and can stop renewing", async ({
  page,
}) => {
  await page.goto("/v2/spending?month=2026-09");
  const purchase = page.getByRole("button", { name: "Сентябрьская покупка", exact: true });
  await purchase.focus();
  await page.keyboard.press("Enter");
  const card = page.getByRole("dialog", { name: "Карточка покупки" });
  await card.getByLabel("Моя заметка").fill("Проезд на работу");
  await card.getByLabel("Обязательность для бюджета").selectOption("true");
  await card.getByLabel("Планирую повторять").check();
  await card.getByLabel("Интервал, месяцев").fill("12");
  await card.getByLabel("Следующая оплата").fill("2027-09-01");
  await card.getByLabel("Ожидаемая сумма, ₽").fill("24000,00");
  await card.getByRole("button", { name: "Сохранить" }).click();
  await expect(card.getByRole("status")).toHaveText("Сохранено");
  await expect(card.getByText(/В среднем за месяц/)).toContainText("2 000");
  await card.getByRole("button", { name: "Закрыть" }).click();
  await page.reload();
  await purchase.click();
  await expect(card.getByLabel("Моя заметка")).toHaveValue("Проезд на работу");
  await expect(card.getByLabel("Следующая оплата")).toHaveValue("2027-09-01");
  await card.getByLabel("Планирую повторять").uncheck();
  await card.getByRole("button", { name: "Сохранить" }).click();
  await expect(card.getByRole("status")).toHaveText("Сохранено");
  await expect(card.getByLabel("Моя заметка")).toHaveValue("Проезд на работу");
  await expect(card.getByLabel("Следующая оплата")).toHaveCount(0);
});

test("record next rent against the existing schedule and undo the selection", async ({
  page,
  request,
}) => {
  async function rent(month: number) {
    const report = await request.post("/api/months", {
      data: { year: 2024, month, snapshot_date: `2024-${month}-28` },
    });
    expect(report.ok()).toBe(true);
    const fact = await request.post("/api/expenses", {
      data: {
        reporting_month_id: (await report.json()).id,
        category: "Аренда жилья",
        expense_type: "mandatory",
        amount: { amount: "30000.00", currency: "RUB" },
      },
    });
    expect(fact.ok()).toBe(true);
  }
  await rent(10);
  await rent(11);
  async function open(month: string) {
    await page.goto(`/v2/spending?month=${month}`);
    await page.getByRole("button", { name: "Аренда жилья", exact: true }).click();
    return page.getByRole("dialog", { name: "Карточка покупки" });
  }
  const first = await open("2024-10");
  await first.getByLabel("Планирую повторять").check();
  await first.getByLabel("Интервал, месяцев").fill("1");
  await first.getByRole("button", { name: "Сохранить" }).click();
  await expect(first.getByRole("status")).toHaveText("Сохранено");
  await first.getByRole("button", { name: "Закрыть" }).click();
  const second = await open("2024-11");
  const pick = second.getByLabel("Существующий график");
  const schedule = pick.getByRole("option", { name: /Аренда жилья · 2024-10/ });
  await expect(schedule).toHaveCount(1);
  const scheduleId = await schedule.getAttribute("value");
  if (!scheduleId) throw new Error("Не найден график октябрьской аренды");
  await pick.selectOption(scheduleId);
  await second.getByRole("button", { name: "Уже оплачено по этому графику" }).click();
  await expect(second.getByText(/Оплачено по графику · Аренда жилья/)).toBeVisible();
  await second.getByRole("button", { name: "Закрыть" }).click();
  await open("2024-11");
  await second.getByRole("button", { name: "Отменить решение" }).click();
  await expect(second.getByText(/Оплачено по графику · Аренда жилья/)).toHaveCount(0);
});

test("report expenses open in the same month before its first upload", async ({
  page,
  request,
}) => {
  const report = await request.post("/api/months", {
    data: { year: 2025, month: 12, snapshot_date: "2026-01-02" },
  });
  expect(report.ok()).toBe(true);
  const { id } = await report.json();
  const expense = await request.post("/api/expenses", {
    data: {
      reporting_month_id: id,
      category: "Тестовый проездной",
      expense_type: "mandatory",
      amount: { amount: "24000.00", currency: "RUB" },
    },
  });
  expect(expense.ok()).toBe(true);
  const source = `/v2/close?month=${id}&panel=budget`;
  await page.goto(source);
  const details = page.getByRole("button", { name: "Записи отчёта и план по категориям" });
  await expect(details).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("link", { name: "Загрузить выписку или Markdown" })).toHaveAttribute(
    "href",
    "/v2/spending/import?month=2025-12",
  );
  await details.click();
  await expect(
    page
      .getByRole("table", { name: "Расходы месяца" })
      .getByRole("cell", { name: "Тестовый проездной" }),
  ).toBeVisible();
  await details.click();
  await page.getByRole("link", { name: "Открыть ленту расходов" }).click();
  await expect(page).toHaveURL(/month=2025-12#spending-operations$/);
  await expect(page.getByRole("heading", { name: "Записи из отчёта месяца" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Тестовый проездной" })).toContainText(
    "24 000",
  );
  await page.goBack();
  await expect(page.getByRole("link", { name: "Открыть ленту расходов" })).toBeVisible();
});
