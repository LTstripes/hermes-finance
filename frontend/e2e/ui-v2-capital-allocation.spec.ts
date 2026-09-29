import { expect, type Page, test } from "@playwright/test";

const cash = (amount: string) => ({ amount, currency: "RUB" });
const supported = { status: "supported", reason_codes: [] };

async function syntheticApi(page: Page) {
  await page.route(/\/api\/(?:months|analytics\/risk-allocation)(?:\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") throw new Error("Unexpected write request");
    if (url.pathname === "/api/months") {
      await route.fulfill({
        json: [
          {
            id: 2,
            year: 2031,
            month: 2,
            status: "draft",
            snapshot_date: "2031-02-28",
            source: "manual",
          },
          {
            id: 1,
            year: 2031,
            month: 1,
            status: "closed",
            snapshot_date: "2031-01-31",
            source: "manual",
          },
        ],
      });
      return;
    }
    if (url.pathname === "/api/analytics/risk-allocation") {
      const monthId = Number(url.searchParams.get("month_id"));
      const allocation = {
        support: { status: "unknown", reason_codes: ["instrument_type_not_authoritative"] },
        denominator: cash("100000.00"),
        covered_amount: cash("80000.00"),
        unallocated_amount: cash("20000.00"),
        coverage_pct: "80.00",
        items: [
          {
            key: "bond",
            label: "bond",
            amount: cash("80000.00"),
            share_pct: "80.00",
            account_id: null,
            instrument_id: null,
            instrument_type: "bond",
          },
          {
            key: "unknown_asset_class",
            label: "Unknown asset class",
            amount: cash("20000.00"),
            share_pct: "20.00",
            account_id: null,
            instrument_id: null,
            instrument_type: null,
          },
        ],
        excluded: [],
      };
      const account = {
        ...allocation,
        support: supported,
        coverage_pct: "100.00",
        covered_amount: cash("100000.00"),
        unallocated_amount: cash("0.00"),
        items: [
          {
            key: "account:1",
            label: "Счёт А",
            amount: cash("80000.00"),
            share_pct: "80.00",
            account_id: 1,
            instrument_id: null,
            instrument_type: null,
          },
          {
            key: "account:2",
            label: "Счёт Б",
            amount: cash("20000.00"),
            share_pct: "20.00",
            account_id: 2,
            instrument_id: null,
            instrument_type: null,
          },
        ],
      };
      const concentration = {
        support: supported,
        denominator: cash("100000.00"),
        top_n: 5,
        top_amount: cash("80000.00"),
        top_share_pct: "80.00",
        items: [
          {
            key: "position:1",
            label: "Счёт А / Облигация",
            amount: cash("80000.00"),
            share_pct: "80.00",
            account_id: 1,
            account_name: "Счёт А",
            instrument_id: 1,
            instrument_name: "Облигация",
            instrument_type: "bond",
            position_id: 1,
            event_count: null,
            is_approximate: false,
          },
        ],
        excluded: [],
        is_approximate: false,
      };
      const payout = {
        ...concentration,
        denominator: cash("1200.00"),
        top_amount: cash("900.00"),
        top_share_pct: "75.00",
        items: [
          {
            ...concentration.items[0],
            key: "payout:1",
            label: "Купон",
            amount: cash("900.00"),
            share_pct: "75.00",
            event_count: 2,
          },
        ],
      };
      const redemption = {
        ...concentration,
        denominator: cash("5000.00"),
        top_amount: cash("5000.00"),
        top_share_pct: "100.00",
        items: [
          {
            ...concentration.items[0],
            key: "redemption:1",
            label: "Погашение облигации",
            amount: cash("5000.00"),
            share_pct: "100.00",
            event_count: 1,
          },
        ],
      };
      await route.fulfill({
        json: {
          reporting_month_id: monthId,
          as_of_date: monthId === 2 ? "2031-02-28" : "2031-01-31",
          base_currency: "RUB",
          liquid_assets_total: cash("100000.00"),
          allocation_by_asset_class: allocation,
          allocation_by_account: account,
          top_positions: concentration,
          payout_concentration: payout,
          redemption_concentration: redemption,
          support: {
            issuer: { status: "unavailable", reason_codes: ["issuer_not_persisted"] },
            currency: { status: "unknown", reason_codes: ["currency_not_persisted"] },
          },
        },
      });
      return;
    }
    throw new Error(`Unexpected API: ${url.pathname}`);
  });
}

for (const viewport of [
  { name: "desktop", width: 1366, height: 900 },
  { name: "390px", width: 390, height: 844 },
]) {
  test(`allocation leaf ${viewport.name}: deep link, coverage, keyboard and contained layout`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await syntheticApi(page);
    await page.goto("/e2e/fixtures/capital-allocation.html?month=2");
    await expect(
      page.getByRole("heading", { level: 1, name: "Распределение и концентрация" }),
    ).toBeVisible();
    await expect(page.getByLabel("Отчётный месяц")).toHaveValue("2");
    const classes = page
      .locator("details")
      .filter({ has: page.locator("summary", { hasText: "По классам активов" }) })
      .first();
    await classes.locator("summary").focus();
    await expect(classes.locator("summary")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(classes.getByRole("table", { name: "По классам активов" })).toBeVisible();
    await expect(classes.getByText("Неизвестный класс активов")).toBeVisible();
    await expect(classes.getByText(/Охват неполный или не подтверждён/)).toBeVisible();
    const redemptions = page
      .locator("details")
      .filter({ has: page.locator("summary", { hasText: "Погашения" }) })
      .first();
    await redemptions.locator("summary").click();
    await expect(redemptions.getByText("Погашение облигации")).toBeVisible();
    await expect(
      page.getByText(/Погашение основного долга не является пассивным доходом/),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-allocation-expanded.png`),
      fullPage: true,
    });
    await page.getByLabel("Отчётный месяц").selectOption("1");
    await expect(page.getByLabel("Отчётный месяц")).toHaveValue("1");
    await expect(page.getByText("31.01.2031", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-allocation.png`),
      fullPage: true,
    });
  });
}
