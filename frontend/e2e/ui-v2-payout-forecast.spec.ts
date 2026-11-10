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

async function installPayoutApi(page: Page, mode: "normal" | "partial" | "offline" = "normal") {
  let offline = false;
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
      if (request.method() === "GET" && pathname === "/api/instruments/11/market-mapping") {
        await route.fulfill({
          json: {
            instrument_id: 11,
            state: mode === "partial" ? "unmapped" : "mapped",
            identity:
              mode === "partial"
                ? null
                : {
                    provider: "t_invest",
                    provider_instrument_id: "SYNTHETIC-UID-001",
                    provider_venue_id: null,
                  },
            instrument_isin: "RU000SYNTH01",
            legacy_moex_secid: null,
          },
        });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/payouts/calendar") {
        if (offline) {
          await route.abort();
          return;
        }
        await route.fulfill({ json: payoutCalendar });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12/payout-refresh-status") {
        if (offline) {
          await route.abort();
          return;
        }
        await route.fulfill({
          json: {
            reporting_month_id: 12,
            positions_changed: mode === "partial" ? 1 : 0,
            items: [],
            forecast_as_of: "2031-08-30T12:00:00Z",
            automatic_refresh: {
              status: mode === "partial" ? "partial" : mode === "offline" ? "error" : "completed",
              message: "",
              reason_codes:
                mode === "partial"
                  ? ["mapping_ambiguous", "possible_manual_duplicate"]
                  : mode === "offline"
                    ? ["provider_unavailable"]
                    : [],
            },
          },
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
      if (
        request.method() === "GET" &&
        pathname === "/api/broker-months" &&
        url.search === "?reporting_month_id=12"
      ) {
        await route.fulfill({ json: [] });
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
  return {
    errors,
    posts,
    goOffline: () => {
      offline = true;
    },
  };
}

async function assertNoPageOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
}

for (const viewport of [{ name: "desktop", width: 1366, height: 900 }]) {
  test(`native payout forecast ${viewport.name}: preview/apply, keyboard, contained scroll`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installPayoutApi(page);
    await page.goto("/v2/data/payouts?month=12");
    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    const main = page.getByRole("region", { name: "Основной прогноз" });
    await expect(main.getByRole("heading", { name: "Прогноз на 12 месяцев" })).toBeVisible();
    expect(api.posts).toEqual([]);
    await expect(main.getByRole("button")).toHaveCount(2);
    await expect(main.getByText("300 ₽", { exact: true })).toBeVisible();
    await expect(main.locator("dd").nth(1)).toHaveText("1 000 ₽");
    await expect(main).not.toContainText(/t_invest|SYNTHETIC-UID|completed|active/);
    await expect(main.getByRole("table", { name: "Выплаты по датам" })).toBeVisible();
    await expect(main.getByText("возврат капитала, не доход")).toBeVisible();
    await expect(page.getByRole("button", { name: "Проверить выплаты T-Invest" })).toHaveCount(0);
    await assertNoPageOverflow(page);
    const scrollOverflowX = await main
      .getByRole("region", { name: "Выплаты: прокрутка списка" })
      .evaluate((element) => getComputedStyle(element).overflowX);
    expect(scrollOverflowX).toBe("auto");
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-payout-calendar.png`),
      fullPage: true,
    });

    // Keyboard opens the single-click disclosure before an explicit preview.
    await main.getByRole("button", { name: "Подробности" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("button", { name: "Проверить все позиции T-Invest" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Загрузка файлов месяца · PDF выплат" }),
    ).toHaveAttribute("href", "/v2/close?month=12&panel=brokers");
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

  test(`native payout forecast ${viewport.name}: legacy return opens the single Month Close panel`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installPayoutApi(page);
    await page.goto(
      "/v2/data/payouts?month=12&from=monthly-close-v2&step=future_payouts&monthId=12",
    );
    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    const backToClose = page.getByRole("link", { name: "Вернуться к закрытию" });
    await expect(backToClose).toHaveAttribute("href", "/v2/close?month=12&step=future_payouts");
    await backToClose.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/v2\/close\?month=12&step=future_payouts$/);
    await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
    await expect(page.getByRole("list", { name: "Шаги закрытия" })).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1, name: "Август 2031" })).toBeVisible();
    await assertNoPageOverflow(page);
    await expect(api.errors).toEqual([]);
  });
}

for (const mode of ["partial", "offline"] as const) {
  test(`simplified payout forecast desktop: ${mode} retains dated saved payments`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    const api = await installPayoutApi(page, mode);
    await page.goto("/v2/data/payouts?month=12");
    const main = page.getByRole("region", { name: "Основной прогноз" });
    const attention = main.getByRole("status", { name: "Требует внимания" });
    await expect(main.getByRole("table")).toBeVisible();
    await expect(main.getByRole("button")).toHaveCount(2);
    await expect(main).toContainText("Последний прогноз: 30.08.2031");
    await expect(attention).toContainText(
      mode === "partial" ? "Прогноз неполный" : "Обновление недоступно",
    );
    if (mode === "partial") {
      await expect(attention).toContainText("нет сопоставления с T-Invest");
      await expect(attention).toContainText("Есть конфликт выплат");
    } else {
      await expect(attention).toContainText("Показан прежний прогноз");
      api.goOffline();
      await main.getByRole("button", { name: "Обновить" }).click();
      await expect(main.getByRole("button", { name: "Обновить", exact: true })).toBeEnabled();
      await expect(main.getByRole("table")).toBeVisible();
      await expect(attention).toContainText("Последний прогноз: 30.08.2031");
    }
    await expect(main).not.toContainText(
      /mapping_ambiguous|possible_manual_duplicate|provider_unavailable/,
    );
    expect(api.posts).toEqual([]);
    expect(api.errors).toEqual([]);
    await assertNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`payout-${mode}.png`), fullPage: true });
  });
}

test("legacy statement import stays collapsed and expands on hash navigation and reload", async ({
  page,
}) => {
  const api = await installPayoutApi(page);
  await page.goto("/v2/data/payouts?month=12");
  const disclosure = page.locator("details#statement-import");
  const input = page.getByLabel("PDF отчёта Alfa");
  await expect(disclosure).toBeVisible();
  await expect(disclosure).not.toHaveAttribute("open");
  await expect(input).toBeHidden();

  const summary = disclosure.locator("summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveAttribute("open");
  await expect(input).toBeVisible();
  await summary.click();
  await expect(input).toBeHidden();

  await page.evaluate(() => {
    window.location.hash = "statement-import";
  });
  await expect(disclosure).toHaveAttribute("open");
  await expect(input).toBeVisible();
  await expect(page.getByRole("region", { name: "Основной прогноз" })).toBeVisible();

  await page.reload();
  await expect(disclosure).toHaveAttribute("open");
  await expect(input).toBeVisible();
  expect(api.posts).toEqual([]);
  expect(api.errors).toEqual([]);
});
