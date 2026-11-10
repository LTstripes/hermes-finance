import { expect, type Page, test } from "@playwright/test";

test("G04 smoke: retired v1 entry redirects to the native UI", async ({ page }) => {
  // The shell heading renders before the initial month read completes.
  const months = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/months" && response.request().method() === "GET",
  );
  await page.goto("/v1");
  expect((await months).ok()).toBe(true);
  await expect(page).toHaveURL(/\/v2$/);
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();
  await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");

  await page.getByRole("link", { name: "Капитал", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/capital$/);
  await expect(page.getByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();
  await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");

  const settings = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/settings" && response.request().method() === "GET",
  );
  await page.getByRole("link", { name: "Настройки", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/data\/app$/);
  await expect(page.getByRole("heading", { level: 1, name: "Настройки" })).toBeVisible();
  const response = await settings;
  expect(response.ok()).toBe(true);
  await expect(page.getByLabel("Локаль", { exact: true })).toHaveValue(
    (await response.json()).locale,
  );
});

async function openBrokerReview(page: Page, accountId: number) {
  await expect(
    page.getByRole("region", { name: "Рабочая область: Брокерские выписки", exact: true }),
  ).toBeVisible();
  // The outer disclosure starts open for a month that still needs a source.
  const outer = page.getByText("Подробнее о разборе", { exact: true });
  if (!(await outer.evaluate((element) => element.closest("details")?.open))) await outer.click();
  const summary = page.getByText("Подробности разбора и сохранение месяца", { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
  await expect(summary.locator("..")).toHaveAttribute("open", "");
  const account = page.getByLabel("Брокерский счёт", { exact: true });
  // The label can exist before the accounts query has populated the options.
  await expect(account.locator(`option[value="${accountId}"]`)).toHaveCount(1);
  await expect(account).toBeEnabled();
  return account;
}

test("G04 smoke: broker accounts are ready after returning to the month", async ({
  page,
  request,
}, testInfo) => {
  const year = 2041 + testInfo.repeatEachIndex;
  const monthResponse = await request.post("/api/months", {
    data: { year, month: 3, snapshot_date: `${year}-03-31` },
  });
  expect(monthResponse.status()).toBe(201);
  const month = await monthResponse.json();
  const accountResponse = await request.post("/api/accounts", {
    data: { name: `Synthetic G04 return broker ${year}`, account_type: "brokerage" },
  });
  expect(accountResponse.status()).toBe(201);
  const account = await accountResponse.json();
  const url = `/v2/close?month=${month.id}&panel=brokers`;
  await page.goto(url);
  await openBrokerReview(page, account.id);

  await page.getByRole("link", { name: "Капитал", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/capital$/);
  await page.goBack();
  await expect(page).toHaveURL((value) => value.pathname + value.search === url);
  const picker = await openBrokerReview(page, account.id);
  await picker.selectOption(String(account.id));
  await expect(picker).toHaveValue(String(account.id));
});
