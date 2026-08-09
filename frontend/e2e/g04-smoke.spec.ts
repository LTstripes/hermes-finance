import { expect, test } from "@playwright/test";

test("G04 critical monthly workflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();

  await page.getByRole("link", { name: "Месяцы" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Месяцы" })).toBeVisible();

  await page.getByLabel("Год").fill("2049");
  await page.getByLabel("Месяц").selectOption("12");
  await page.getByLabel("Дата снимка").fill("2049-12-31");
  await page.getByRole("button", { name: "Создать месяц" }).click();

  const monthRow = page.getByRole("row").filter({ hasText: "Декабрь" }).last();
  await expect(monthRow).toContainText("draft");
  await monthRow.getByRole("link", { name: "Открыть" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Декабрь 2049" })).toBeVisible();

  await page.getByLabel("Зарплата gross").fill("100000");
  await page.getByLabel("Фактический net (employer)").fill("87000");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText(/Сохранено/)).toBeVisible();

  await page.getByLabel("Категория расхода").fill("Smoke rent");
  await page.getByLabel("Сумма расхода").fill("20000");
  await page.getByRole("button", { name: "Добавить расход" }).click();
  await expect(page.getByRole("table").filter({ hasText: "Smoke rent" })).toBeVisible();

  await page.getByLabel("Название вклада").fill("Smoke deposit");
  await page.getByLabel("Баланс вклада").fill("100000");
  await page.getByLabel("Годовая ставка %").fill("12");
  await page.getByLabel("Факт. процент").fill("500");
  await page.getByRole("button", { name: "Добавить вклад" }).click();
  await expect(page.getByRole("table").filter({ hasText: "Smoke deposit" })).toBeVisible();

  await page.getByRole("link", { name: "Дашборд" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();
  await expect(page.getByText("Ликвидный капитал")).toBeVisible();
  await expect(page.getByText("Forecast passive")).toBeVisible();

  await page.getByRole("link", { name: "Экспорт" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Экспорт" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать Markdown" })).toBeEnabled();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать Markdown" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("finance_report_2049-12.md");
  await expect(page.getByRole("status")).toContainText("скачан");
});
