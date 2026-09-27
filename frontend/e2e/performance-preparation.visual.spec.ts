import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

for (const width of [390, 1366]) {
  test(`Owner preparation keyboard and layout ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const start = "2030-05-01";
    const end = "2030-05-31";
    const metric = (kind: string) => ({
      metric: kind,
      scope: "account",
      account_id: 1,
      performance_currency: "RUB",
      value: null,
      value_unit: "percentage_points",
      annualized: kind === "xirr",
      availability: "not_computable",
      quality: "not_computable",
      reason_codes: [],
      period: { start_date: start, end_date: end },
    });
    const writes: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }
      if (route.request().method() !== "GET") {
        writes.push(url.pathname);
        await route.fulfill({ status: 409, json: { detail: "synthetic stale save" } });
        return;
      }
      let json: unknown = [];
      if (url.pathname === "/api/accounts")
        json = [
          {
            id: 1,
            name: "Синтетический инвестиционный счёт для проверки длинного названия",
            account_type: "brokerage",
            status: "active",
            include_in_returns: false,
          },
        ];
      if (url.pathname === "/api/months") json = [];
      if (url.pathname === "/api/performance/readiness")
        json = {
          schema_version: 1,
          scope: "account",
          account_id: 1,
          start_date: start,
          end_date: end,
          performance_currency: "RUB",
          xirr: metric("xirr"),
          twrr: metric("twrr"),
          diagnostics: [],
          evidence: {
            scope_membership: { account_ids: [1], missing_or_ambiguous_account_ids: [1] },
            cash_boundary_coverage: { account_ids: [], missing_or_incomplete_account_ids: [] },
            in_kind_boundary_coverage: { account_ids: [] },
          },
        };
      if (url.pathname === "/api/performance/preparation")
        json = {
          account_id: 1,
          start_date: start,
          end_date: end,
          evidence_token: "synthetic",
          flows: [],
          transfer_links: [],
          cash_coverages: [],
          in_kind_coverages: [],
          movements: [],
          cash_balances: [],
          months: [{ id: 4, period_start: start, period_end: end, status: "draft" }],
        };
      await route.fulfill({ json });
    });
    await page.goto(
      `/v2/capital/performance?start=${start}&end=${end}&scope=account&account_id=1&prepare_account=1&prepare_reason=cash_history#performance-preparation`,
    );
    const add = page.getByRole("button", { name: "Добавить операцию" });
    await expect(add).toBeVisible();
    await add.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Сумма операции")).toBeVisible();
    await page.getByLabel("Отчёт операции").selectOption("4");
    await page.getByLabel("Дата операции").fill("2030-05-12");
    await page.getByLabel("Сумма операции").fill("123.45");
    await expect(page.getByRole("button", { name: "Сохранить операцию" })).toBeDisabled();
    await page.getByLabel(/Я проверил.*дату, счёт, сумму/).check();
    await expect(page.getByRole("button", { name: "Сохранить операцию" })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
    const dir = path.resolve(".visual-audit", testInfo.project.name);
    fs.mkdirSync(dir, { recursive: true });
    await page.screenshot({
      path: path.join(dir, `performance-preparation-${width}.png`),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Сохранить операцию" }).click();
    await expect(page.getByText(/Форма устарела/)).toBeVisible();
    expect(writes).toEqual(["/api/external-flows"]);
  });
}
