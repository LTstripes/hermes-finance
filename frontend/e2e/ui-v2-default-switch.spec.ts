import { expect, type Page, test } from "@playwright/test";

import { syntheticApiResponse } from "./visual-fixtures";

async function installReadOnlyApiFixtures(page: Page) {
  const requests: Array<{ method: string; url: string }> = [];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      requests.push({ method: request.method(), url: request.url() });
      if (request.method() !== "GET") {
        await route.abort();
        return;
      }
      const url = new URL(request.url());
      const response = syntheticApiResponse(url, request.method());
      if (!response) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "missing_synthetic_fixture", details: [] } }),
        });
        return;
      }
      await route.fulfill({
        status: response.status ?? 200,
        json: response.json,
      });
    },
  );
  return requests;
}

async function expectPathAndSearch(page: Page, expectedPathAndSearch: string) {
  await expect
    .poll(() => {
      const url = new URL(page.url());
      return `${url.pathname}${url.search}${url.hash}`;
    })
    .toBe(expectedPathAndSearch);
}

test("ui-v2: switches between default and explicit v1 without passive writes", async ({ page }) => {
  const requests = await installReadOnlyApiFixtures(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible({
    timeout: 20_000,
  });
  const permanentRollback = page.getByRole("link", { name: "UI v1: предыдущий интерфейс →" });
  await expect(permanentRollback).toBeVisible();
  await expect(permanentRollback).toHaveAttribute("href", "/v1");

  await permanentRollback.click();
  await expect(page).toHaveURL(/\/v1$/);
  await page.reload();
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
    requests.some(
      (request) => request.method !== "GET" || /provider|refresh|backup|restore/i.test(request.url),
    ),
  ).toBe(false);
});

test("ui-v2: retains deep-link query and fragment on hard reload", async ({ page }) => {
  await installReadOnlyApiFixtures(page);
  const deepLink = "/v2?month=12&step=actual_payouts#context";

  await page.goto(deepLink);
  await expectPathAndSearch(page, deepLink);
  await expect(page.getByRole("link", { name: "UI v1: предыдущий интерфейс →" })).toBeVisible();
  await page.reload();
  await expectPathAndSearch(page, deepLink);
});

test("ui-v2: failed lazy load still exposes a working v1 escape", async ({ page }) => {
  await installReadOnlyApiFixtures(page);
  await page.route("**/src/ui-v2/UiV2Page.tsx*", (route) => route.abort());
  await page.goto("/v2");

  await expect(page.getByRole("alert")).toContainText("Основной интерфейс не загрузился");
  await expect(
    page.getByRole("link", { name: "Перейти в предыдущий интерфейс (UI v1)" }),
  ).toHaveAttribute("href", "/v1");
  await page.getByRole("link", { name: "Перейти в предыдущий интерфейс (UI v1)" }).click();
  await expect(page).toHaveURL(/\/v1$/);
  await expect(page.getByRole("heading", { level: 1, name: "Дашборд" })).toBeVisible();
});

test("ui-v2: keeps the UI v1 rollback visible and keyboard-operable at narrow width", async ({
  page,
}) => {
  await installReadOnlyApiFixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const rollback = page.getByRole("link", { name: "UI v1: предыдущий интерфейс →" });
  await expect(rollback).toBeVisible();
  await expect(rollback).toHaveAttribute("href", "/v1");
  await rollback.focus();
  await expect(rollback).toBeFocused();
  await rollback.press("Enter");
  await expect(page).toHaveURL(/\/v1$/);
});
