import { expect, test } from "@playwright/test";

test("G04 critical monthly workflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();

  await page.getByRole("link", { exact: true, name: "Месяцы" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Месяцы" })).toBeVisible();

  await page.getByRole("button", { name: "Создать другой период" }).click();
  const createDialog = page.getByRole("dialog", { name: "Создать месяц" });
  await createDialog.getByLabel("Год").fill("2049");
  await createDialog.getByLabel("Месяц").selectOption("12");
  await createDialog.getByLabel("Дата снимка").fill("2049-12-31");
  await createDialog.getByRole("button", { name: "Создать месяц" }).click();

  const monthRow = page.getByRole("row").filter({ hasText: "Декабрь" }).last();
  await expect(monthRow).toContainText("Черновик");
  await monthRow.getByRole("link", { name: "Открыть" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Декабрь 2049" })).toBeVisible();

  await page.getByRole("button", { name: "Доходы", exact: true }).click();
  await page.getByLabel("Зарплата до вычета налогов").fill("100000");
  await page.getByLabel("Фактическая зарплата после налогов").fill("87000");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText(/Сохранено/)).toBeVisible();

  await page.getByRole("button", { name: "Бюджет", exact: true }).click();
  await page.getByLabel("Категория расхода").fill("Smoke rent");
  await page.getByLabel("Сумма расхода").fill("20000");
  await page.getByRole("button", { name: "Добавить расход" }).click();
  await expect(page.getByRole("table").filter({ hasText: "Smoke rent" })).toBeVisible();

  await page.getByRole("button", { name: "Активы", exact: true }).click();
  await page.getByLabel("Название вклада").fill("Smoke deposit");
  await page.getByLabel("Баланс вклада").fill("100000");
  await page.getByLabel("Годовая ставка %").fill("12");
  await page.getByLabel("Факт. процент").fill("500");
  await page.getByRole("button", { name: "Добавить вклад" }).click();
  await expect(page.getByRole("table").filter({ hasText: "Smoke deposit" })).toBeVisible();

  await page.getByRole("link", { name: "Дашборд" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();
  await expect(page.getByText("Ликвидный капитал", { exact: true })).toBeVisible();
  await expect(page.getByText("Прогноз", { exact: true }).first()).toBeVisible();

  await page.getByRole("link", { name: "Экспорт" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Экспорт" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать Markdown" })).toBeEnabled();
});
