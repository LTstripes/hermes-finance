import { expect, test } from "@playwright/test";

test("G04 smoke: retired v1 entry redirects to the native UI", async ({ page }) => {
  await page.goto("/v1");
  await expect(page).toHaveURL(/\/v2$/);
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();

  await page.getByRole("link", { name: "Капитал", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/capital$/);
  await expect(page.getByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();

  await page.getByRole("link", { name: "Настройки", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/data\/app$/);
  await expect(page.getByRole("heading", { level: 1, name: "Настройки" })).toBeVisible();
});
