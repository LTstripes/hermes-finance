import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

const account = {
  id: 7,
  name: "Синтетический ИИС",
  account_type: "iis",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

for (const viewport of [{ width: 1366, height: 768 }]) {
  test(`catalog IIS write forms ${viewport.width}px and keyboard`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    let plannerReads = 0;
    let profile = {
      id: 11,
      account_id: 7,
      iis_type: "type_a",
      opened_at: "2028-01-12",
      eligible_close_at: "2031-01-12",
      notes: "Синтетика",
    };
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route(
      (url) => url.pathname.startsWith("/api/"),
      async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        let body: unknown = null;
        if (url.pathname === "/api/months") {
          body = [
            {
              id: 12,
              year: 2031,
              month: 8,
              status: "closed",
              snapshot_date: "2031-08-31",
              source: "manual",
            },
          ];
        } else if (url.pathname === "/api/accounts") {
          body = [account];
        } else if (
          url.pathname === "/api/instruments" ||
          url.pathname === "/api/broker-identity-mappings"
        ) {
          body = [];
        } else if (url.pathname === "/api/iis/7/profile") {
          if (request.method() === "PUT") profile = { ...profile, ...request.postDataJSON() };
          body = profile;
        } else if (
          url.pathname === "/api/iis/7/contributions" ||
          url.pathname === "/api/iis/7/benefits"
        ) {
          body = [];
        } else if (url.pathname === "/api/tax-iis-planner") {
          plannerReads += 1;
          body = { iis_accounts: [{ account_id: 7 }] };
        } else {
          errors.push(`Unexpected API request: ${request.method()} ${url.pathname}`);
          await route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({
              error: { code: "not_found", message: "Synthetic route missing", details: [] },
            }),
          });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
    );

    await page.goto("/v2/data/catalogs?month=12&account=7");
    await expect(page.getByTestId("catalog-iis-forms")).toBeVisible();
    await expect(page.getByTestId("data-month-context")).toContainText("Август 2031");
    await expect(page.getByRole("link", { name: /Открыть планировщик/ })).toHaveAttribute(
      "href",
      "/v2/income/tax-iis?month=12",
    );

    // The native control accepts keyboard focus and Enter activation.
    const profileButton = page.getByRole("button", { name: "Сохранить профиль" });
    await profileButton.focus();
    await expect(profileButton).toBeFocused();
    await page.getByLabel("Тип ИИС").selectOption("type_b");
    await profileButton.press("Enter");
    await expect(page.getByText(/Профиль ИИС сохранён и подтверждён/)).toBeVisible();
    expect(plannerReads).toBe(1);
    expect(profile).toMatchObject({
      iis_type: "type_b",
      eligible_close_at: "2031-01-12",
      notes: "Синтетика",
    });

    const captureDir = path.join(testInfo.project.outputDir, "screenshots");
    fs.mkdirSync(captureDir, { recursive: true });
    await page.screenshot({
      path: path.join(captureDir, `catalog-iis-${viewport.width}.png`),
      fullPage: true,
    });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}
