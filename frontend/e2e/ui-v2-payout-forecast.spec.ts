import { expect, type Page, test } from "@playwright/test";

import {
  makeUiV2Workflow,
  uiV2Accounts,
  uiV2Instruments,
  uiV2Months,
} from "../src/test/uiV2Fixtures";

const payoutMonth = uiV2Months.find((row) => row.id === 12);
if (!payoutMonth) throw new Error("Synthetic payout month is missing");
const payoutPosition = {
  id: 701,
  reporting_month_id: 12,
  account_id: 3,
  instrument_id: 11,
  quantity: "10",
};

function money(amount: string) {
  return { amount, currency: "RUB" };
}

const payoutCalendar = [
  {
    year: 2031,
    month: 9,
    coupon: money("100.00"),
    dividend: money("200.00"),
    interest: money("0.00"),
    redemption: money("1000.00"),
    other: money("0.00"),
    passive_net: money("300.00"),
    total_net: money("1300.00"),
    items: [
      {
        source_kind: "manual",
        source_id: 1,
        expected_date: "2031-09-10",
        flow_type: "coupon",
        account_id: 3,
        account_name: "Синтетический брокерский счёт",
        instrument_id: 11,
        instrument_name: "Синтетическая облигация",
        expected_net_amount: money("100.00"),
        is_confirmed: false,
        is_approximate: false,
        manual_source: "manual",
        provider: null,
        provider_instrument_uid: null,
        provider_identity_key: null,
        provider_lifecycle: null,
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: null,
      },
      {
        source_kind: "manual",
        source_id: 2,
        expected_date: "2031-09-10",
        flow_type: "redemption",
        account_id: 3,
        account_name: "Синтетический брокерский счёт",
        instrument_id: 11,
        instrument_name: "Синтетическая облигация",
        expected_net_amount: money("1000.00"),
        is_confirmed: false,
        is_approximate: false,
        manual_source: "manual",
        provider: null,
        provider_instrument_uid: null,
        provider_identity_key: null,
        provider_lifecycle: null,
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: null,
      },
      {
        source_kind: "provider",
        source_id: 501,
        expected_date: "2031-09-10",
        flow_type: "coupon",
        account_id: 3,
        account_name: "Синтетический брокерский счёт",
        instrument_id: 11,
        instrument_name: "Синтетическая облигация",
        expected_net_amount: money("100.00"),
        is_confirmed: null,
        is_approximate: false,
        manual_source: null,
        provider: "t_invest",
        provider_instrument_uid: "SYNTHETIC-UID-001",
        provider_identity_key: "SYNTHETIC-K-1",
        provider_lifecycle: "active",
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: null,
      },
    ],
  },
];

const payoutPreview = {
  reporting_month_id: 12,
  account_id: 3,
  instrument_id: 11,
  position_snapshot_id: 701,
  quantity: "10",
  provider: "t_invest",
  instrument_uid: "SYNTHETIC-UID-001",
  rows: [
    {
      status: "new",
      reporting_month_id: 12,
      account_id: 3,
      instrument_id: 11,
      position_snapshot_id: 701,
      quantity: "10",
      provider: "t_invest",
      instrument_uid: "SYNTHETIC-UID-001",
      event_kind: "coupon",
      identity_key: "SYNTHETIC-K-1",
      payment_date: "2031-09-10",
      per_unit_amount: "10.00",
      currency: "RUB",
      total_amount: money("100.00"),
      provider_status: "ok",
      source_method: "GetBondCoupons",
      applied_payout_id: null,
      applied_lifecycle: null,
      manual_candidate_ids: [],
      reconciliation: null,
      selectable: true,
      default_selected: true,
      fingerprint: "synthetic-fp-1",
      message: null,
    },
  ],
};

async function installPayoutApi(page: Page) {
  const posts: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const pathname = url.pathname;
      if (request.method() === "POST") posts.push(`POST ${pathname}`);
      if (request.method() === "GET" && pathname === "/api/months") {
        await route.fulfill({ json: uiV2Months });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12") {
        await route.fulfill({ json: payoutMonth });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/accounts") {
        await route.fulfill({ json: uiV2Accounts });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/instruments") {
        await route.fulfill({ json: uiV2Instruments });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/positions") {
        await route.fulfill({
          json: url.searchParams.get("month_id") === "12" ? [payoutPosition] : [],
        });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/payouts/calendar") {
        await route.fulfill({ json: payoutCalendar });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12/payout-refresh-status") {
        await route.fulfill({
          json: { reporting_month_id: 12, positions_changed: 0, items: [] },
        });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/expected-flows") {
        await route.fulfill({ json: [] });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12/close-readiness") {
        await route.fulfill({
          json: {
            year: 2031,
            month: 8,
            status: "draft",
            snapshot_date: "2031-08-30",
            source: "manual",
            can_close: false,
            items: [],
          },
        });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12/close-workflow") {
        await route.fulfill({ json: makeUiV2Workflow({ monthId: 12 }) });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/months/12/payout-preview") {
        await route.fulfill({ json: payoutPreview });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/months/12/payout-batch-preview") {
        await route.fulfill({
          json: {
            reporting_month_id: 12,
            forecast_version: "v1",
            summary: {
              total_positions: 1,
              eligible_positions: 1,
              with_events: 1,
              without_events: 0,
              errors: 0,
              skipped: 0,
            },
            items: [
              {
                account_id: 3,
                instrument_id: 11,
                position_snapshot_id: 701,
                provider: "t_invest",
                instrument_uid: "SYNTHETIC-UID-001",
                status: "previewed",
                message: null,
                preview: payoutPreview,
              },
            ],
          },
        });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/months/12/payout-apply") {
        await route.fulfill({
          json: {
            success: true,
            selected_count: 1,
            items: [
              {
                payout_id: 501,
                revision_id: 1,
                revision_kind: "APPLY",
                provider: "t_invest",
                instrument_uid: "SYNTHETIC-UID-001",
                event_kind: "coupon",
                identity_key: "SYNTHETIC-K-1",
                lifecycle: "active",
                total_amount: money("100.00"),
                reconciliation_id: null,
                counting_decision: null,
                expected_cash_flow_id: null,
              },
            ],
            error_code: null,
            message: null,
          },
        });
        return;
      }
      await route.fulfill({
        status: 404,
        json: {
          error: { code: "fixture_missing", message: "Synthetic route missing", details: [] },
        },
      });
    },
  );
  return { errors, posts };
}

async function assertNoPageOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
}

for (const viewport of [
  { name: "desktop", width: 1366, height: 900 },
  { name: "390px", width: 390, height: 844 },
]) {
  test(`native payout forecast ${viewport.name}: preview/apply, keyboard, contained scroll`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installPayoutApi(page);
    await page.goto("/v2/data/payouts?month=12");
    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
    // No provider request on mount: only local reads happened.
    expect(api.posts).toEqual([]);
    // Calendar month rows render collapsed; expand to prove principal
    // stays distinct from passive income/fact.
    await expect(page.locator(".payments-calendar__month summary").first()).toBeVisible();
    await page.locator(".payments-calendar__month summary").first().click();
    await expect(page.getByText("возврат капитала, не доход").first()).toBeVisible();
    await assertNoPageOverflow(page);
    // Contained horizontal table scroll lives inside the calendar section.
    const scrollOverflowX = await page
      .locator('section[aria-label="Календарь выплат: горизонтальная прокрутка таблицы"]')
      .evaluate((element) => getComputedStyle(element).overflowX);
    expect(scrollOverflowX).toBe("auto");
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-payout-calendar.png`),
      fullPage: true,
    });

    // Explicit preview behind a button.
    await page.getByRole("button", { name: "Проверить выплаты T-Invest" }).click();
    await expect(page.getByText("Новая").first()).toBeVisible();
    expect(api.posts).toEqual(["POST /api/months/12/payout-preview"]);

    // Keyboard: focus apply, confirm with Enter, cancel with Escape (no write).
    const applyButton = page.getByRole("button", { name: /Применить выбранные \(1\)/ });
    await applyButton.focus();
    await expect(applyButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    expect(api.posts.filter((call) => call === "POST /api/months/12/payout-apply")).toHaveLength(0);

    // Keyboard confirm: Enter opens, Tab reaches confirm, Enter applies.
    await applyButton.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: /Применить \(1\)/ });
    await confirmButton.focus();
    await expect(confirmButton).toBeFocused();
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-payout-confirm.png`),
      fullPage: true,
    });
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Применено выплат: 1/)).toBeVisible();
    expect(api.posts.filter((call) => call === "POST /api/months/12/payout-apply")).toHaveLength(1);
    await assertNoPageOverflow(page);
    await expect(api.errors).toEqual([]);
  });

  test(`native payout forecast ${viewport.name}: v2 Close round-trip keeps the month`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installPayoutApi(page);
    await page.goto("/v2/close?month=12&step=future_payouts");
    const openCalendar = page.getByRole("link", { name: "Открыть календарь выплат" });
    await expect(openCalendar).toHaveAttribute(
      "href",
      "/v2/data/payouts?month=12&from=monthly-close-v2&step=future_payouts&monthId=12",
    );
    await openCalendar.focus();
    await expect(openCalendar).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(
      /\/v2\/data\/payouts\?month=12&from=monthly-close-v2&step=future_payouts&monthId=12$/,
    );
    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    const backToClose = page.getByRole("link", { name: "Вернуться к закрытию" });
    await expect(backToClose).toHaveAttribute("href", "/v2/close?month=12&step=future_payouts");
    await backToClose.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/v2\/close\?month=12&step=future_payouts$/);
    await expect(page.getByRole("heading", { level: 1, name: /Закрытие месяца/ })).toBeVisible();
    await assertNoPageOverflow(page);
    await expect(api.errors).toEqual([]);
  });
}
