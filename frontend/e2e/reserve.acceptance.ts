import { expect, test } from "@playwright/test";

test("reserve saves a category budget, reads the calendar, and returns to the selected month", async ({
  page,
}) => {
  await page.goto("/v2/spending?month=2026-10");
  await page.getByRole("link", { name: "Подушка", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Подушка безопасности" })).toBeVisible();
  await page.getByLabel("С", { exact: true }).fill("2027-01-01");
  await page.getByLabel("До", { exact: true }).fill("2027-06-30");
  await page.getByRole("checkbox", { name: "Продукты", exact: true }).check();
  await page.getByRole("textbox", { name: "Оценка · Продукты" }).fill("38000");
  await page.getByRole("button", { name: "Сохранить план" }).click();
  await expect(page.getByRole("status").filter({ hasText: "План сохранён" })).toBeVisible();
  const goal = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Цель до 30.06.2027" }) });
  await expect(goal).toContainText(/228\s000/);
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Оценка · Продукты" })).toHaveValue("38000");
  await expect(goal).toContainText(/228\s000/);
  await page.getByRole("link", { name: "Операции", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/spending\?month=2026-10$/);
});
