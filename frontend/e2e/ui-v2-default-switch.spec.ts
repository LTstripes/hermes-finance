import { expect, type Page, test } from "@playwright/test";

async function installReadOnlyApiFixtures(page: Page) {
  const requests: Array<{ method: string; url: string }> = [];
  await page.route(/^http:\/\/127\.0\.0\.1:5173\/api\//, async (route) => {
    const request = route.request();
    requests.push({ method: request.method(), url: request.url() });
    if (request.method() !== "GET") {
      await route.abort();
      return;
    }
    const url = new URL(request.url());
    const body = url.pathname === "/api/health" ? { status: "ok", version: "synthetic" } : [];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  return requests;
}

test("switches between v2 default and explicit v1 without passive writes", async ({ page }) => {
  const requests = await installReadOnlyApiFixtures(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("link", { name: /UI v1/ }).first()).toBeVisible();

  await page.getByRole("link", { name: /UI v1/ }).first().click();
  await expect(page).toHaveURL(/\/v1$/);
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Дашборд", exact: true })).toHaveAttribute(
    "href",
    "/v1",
  );

  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/\/v1$/);

  expect(requests.filter((request) => request.method !== "GET")).toEqual([]);
  expect(
    requests.some((request) => /provider|refresh|backup|restore|close/i.test(request.url)),
  ).toBe(false);
});

test("retains v2 deep-link query and fragment on hard reload", async ({ page }) => {
  await installReadOnlyApiFixtures(page);
  const deepLink = "/v2?month=12&step=actual_payouts#context";

  await page.goto(deepLink);
  await expect(page).toHaveURL(`http://127.0.0.1:5173${deepLink}`);
  await expect(page.getByRole("link", { name: /UI v1/ }).first()).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(`http://127.0.0.1:5173${deepLink}`);
});

test("failed v2 lazy load still exposes a working v1 escape", async ({ page }) => {
  await installReadOnlyApiFixtures(page);
  await page.route("**/src/ui-v2/UiV2Page.tsx*", (route) => route.abort());
  await page.goto("/v2");

  await expect(page.getByRole("alert")).toContainText("Новый интерфейс не загрузился");
  await expect(page.getByRole("link", { name: "Перейти в UI v1" })).toHaveAttribute("href", "/v1");
  await page.getByRole("link", { name: "Перейти в UI v1" }).click();
  await expect(page).toHaveURL(/\/v1$/);
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();
});

test("keeps the UI v1 rollback visible and keyboard-operable at narrow width", async ({ page }) => {
  await installReadOnlyApiFixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const rollback = page.getByRole("link", { name: /UI v1/ }).first();
  await expect(rollback).toBeVisible();
  await rollback.focus();
  await expect(rollback).toBeFocused();
  await rollback.press("Enter");
  await expect(page).toHaveURL(/\/v1$/);
});
