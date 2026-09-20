import fs from "node:fs";
import path from "node:path";

import { expect, type Page, test, type TestInfo } from "@playwright/test";

import type {
  CashFlowLadder,
  IncomePlanSummary,
  PlanVsActualRow,
  SavingAllocation,
} from "../src/api/types";
import { makeUiV2Goals, makeUiV2PassiveHistory, uiV2Months } from "../src/test/uiV2Fixtures";

type IncomeScene = "normal" | "no-closed" | "first-closed" | "zero" | "partial";

const money = (amount: string) => ({ amount, currency: "RUB" });

function makeSummary({ zero = false }: { zero?: boolean } = {}): IncomePlanSummary {
  const amount = (value: string) => money(zero ? "0.00" : value);
  return {
    month: { ...uiV2Months[0], status: "closed" },
    forecast_version: "v1",
    forecast: {
      annual_total: amount("252000.00"),
      monthly_total: amount("21000.00"),
      breakdown: {
        expected_deposit_interest: amount("6750.00"),
        expected_coupon_net: amount("5000.00"),
        expected_dividend_component: amount("4000.00"),
        other_expected_capital_income: amount("0.00"),
      },
      is_approximate: true,
      warnings: ["Дивиденды оценены по подтверждённому среднему."],
      dividend_average: amount("4000.00"),
      configured_start_month: null,
      dividend_month_keys_used: ["2031-02", "2031-04", "2031-05", "2031-07"],
    },
    coverage: {
      forecast_monthly: amount("21000.00"),
      actual_average: amount("15300.00"),
      mandatory_expenses: amount("60000.00"),
      coverage_pct: zero ? "0.00" : "35.00",
      actual_mandatory_expense_coverage_pct: zero ? "0.00" : "25.50",
      passive_income_minus_mandatory_expenses: zero ? amount("0.00") : money("-39000.00"),
      goal_target: money("50000.00"),
      goal_progress_pct: zero ? "0.00" : "30.60",
      is_approximate: true,
      warnings: [],
    },
    cash_balance: {
      total: amount("803900.00"),
      breakdown: { saving_allocations: amount("25000.00") },
    },
    warnings: [],
  };
}

function makeLadder(zero = false): CashFlowLadder {
  const passive = money(zero ? "0.00" : "8500.00");
  const principal = money(zero ? "0.00" : "100000.00");
  const coupon = {
    source_kind: "provider" as const,
    source_id: 701,
    expected_date: "2031-08-15",
    flow_type: "income",
    component: "coupon" as const,
    account_id: 3,
    account_name: "Синтетический брокерский счёт",
    instrument_id: 11,
    instrument_name: "Синтетическая облигация",
    expected_net_amount: passive,
    is_approximate: false,
    source: "synthetic",
    provider: "synthetic",
    provider_instrument_uid: null,
    provider_identity_key: null,
    reconciliation_id: null,
    counting_decision: null,
    linked_manual_id: null,
    linked_provider_payout_id: null,
    source_as_of_date: "2031-07-31",
  };
  const redemption = {
    ...coupon,
    source_id: 702,
    component: "redemption_principal" as const,
    expected_net_amount: principal,
  };
  const month = {
    year: 2031,
    month: 8,
    coupon: passive,
    dividend: money("0.00"),
    deposit_interest: money("0.00"),
    other_capital_income: money("0.00"),
    redemption_principal: principal,
    passive_income: passive,
    total_cash_flow: money(zero ? "0.00" : "108500.00"),
    is_approximate: false,
    items: [coupon, redemption],
  };
  return {
    as_of_date: "2031-07-31",
    forecast_version: "v1",
    months: [month],
    upcoming_14_days: {
      days: 14,
      from_date: "2031-08-01",
      to_date: "2031-08-14",
      passive_income: passive,
      redemption_principal: money("0.00"),
      total_cash_flow: passive,
      items: [coupon],
    },
    upcoming_30_days: {
      days: 30,
      from_date: "2031-08-01",
      to_date: "2031-08-30",
      passive_income: passive,
      redemption_principal: principal,
      total_cash_flow: money(zero ? "0.00" : "108500.00"),
      items: [coupon, redemption],
    },
    warnings: [],
  };
}

const budget: PlanVsActualRow[] = [
  {
    category: "Жильё",
    expense_type: "mandatory",
    planned: money("50000.00"),
    actual: money("48000.00"),
  },
];

const savings: SavingAllocation[] = [
  {
    id: 801,
    reporting_month_id: 91,
    destination: "Резерв",
    amount: money("25000.00"),
    notes: null,
  },
];

async function installIncomeApi(page: Page, scene: IncomeScene = "normal") {
  const firstClosed = scene === "first-closed";
  const zero = scene === "zero";
  const state = {
    summary: makeSummary({ zero }),
    history: makeUiV2PassiveHistory({ firstClosed, zero }),
    ladder: makeLadder(zero),
    goals: makeUiV2Goals({ firstClosed, zero }),
    ladderError: scene === "partial",
    budgetError: scene === "partial",
  };
  if (zero) {
    for (const point of state.history.points) point.passive_income_actual.amount = "0.00";
    state.history.average.average.amount = "0.00";
    state.history.selected_report?.breakdown &&
      Object.values(state.history.selected_report.breakdown).forEach((value) => {
        value.amount = "0.00";
      });
  }
  const unexpected: string[] = [];
  const reads: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
      unexpected.push(`external: ${url.origin}`);
    }
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    reads.push(`${request.method()} ${url.pathname}${url.search}`);
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    let json: unknown;
    let status = 200;
    if (url.pathname === "/api/months") {
      json =
        scene === "no-closed"
          ? [uiV2Months[1]]
          : scene === "first-closed"
            ? [uiV2Months[0], uiV2Months[1]]
            : uiV2Months;
    } else if (url.pathname === "/api/months/91/income-plan-summary") {
      expect(url.searchParams.get("forecast_version")).toBe("v1");
      json = state.summary;
    } else if (url.pathname === "/api/analytics/passive-income") {
      json = state.history;
    } else if (url.pathname === "/api/months/91/cash-flow-ladder") {
      expect(url.searchParams.get("forecast_version")).toBe("v1");
      json = state.ladder;
      status = state.ladderError ? 503 : 200;
    } else if (url.pathname === "/api/goals/summary") {
      expect(url.searchParams.get("reporting_month_id")).toBe("91");
      expect(url.searchParams.get("forecast_version")).toBe("v1");
      json = state.goals;
    } else if (url.pathname === "/api/planned-budget/comparison") {
      json = budget;
      status = state.budgetError ? 503 : 200;
    } else if (url.pathname === "/api/savings") {
      json = savings;
    } else {
      unexpected.push(`${request.method()} ${url.pathname}`);
      status = 404;
      json = { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } };
    }
    await route.fulfill({
      status,
      json:
        status === 200
          ? json
          : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
    });
  });
  return { errors, reads, unexpected };
}

async function assertBounded(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  const clipped = await page.locator("#v2-main button, #v2-main a").evaluateAll((elements) =>
    elements
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1);
      })
      .map((element) => element.textContent),
  );
  expect(clipped).toEqual([]);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  const dir = path.resolve(".visual-audit", testInfo.project.name);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({
    path: path.join(dir, `${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}

test("ui-v2 Income and plans desktop: canonical headlines, ladder and secondary planning stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installIncomeApi(page);
  await page.goto("/v2/income");
  expect(evidence.errors, evidence.errors.join(" | ")).toEqual([]);
  await expect(page.getByRole("heading", { level: 1, name: "Доход и планы" })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Главные показатели дохода" }).getByRole("article"),
  ).toHaveCount(3);
  await expect(page.getByTestId("income-average")).toHaveText("15 300 ₽");
  await expect(page.getByTestId("income-forecast")).toContainText("21 000 ₽");
  await expect(page.getByTestId("income-upcoming-passive")).toHaveText("8 500 ₽");
  await expect(
    page.getByText("Возврат основной суммы: 100 000 ₽", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByTestId("income-history-panel")).toContainText("Купоны");
  await expect(page.getByTestId("income-goals-panel")).toContainText("Нет прогноза срока");
  await expect(page.getByTestId("income-plan-panel")).toBeVisible();
  await expect(page.getByRole("group", { name: "Окно ожидаемых выплат" })).toHaveAttribute(
    "aria-controls",
    "income-ladder-content",
  );
  await expect(
    page
      .getByTestId("income-window-30")
      .getByTestId("income-event-provider-701")
      .locator(":scope > *"),
  ).toHaveCount(3);
  expect(
    await page
      .locator('[data-testid$="-panel"]')
      .evaluateAll((panels) => panels.map((panel) => panel.getAttribute("data-testid"))),
  ).toEqual([
    "income-history-panel",
    "income-forecast-panel",
    "income-goals-panel",
    "income-plan-panel",
    "income-ladder-panel",
    "income-handoffs-panel",
  ]);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-income-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Income and plans narrow: secondary plan handoffs collapse and no page overflow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored once");
  const evidence = await installIncomeApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/income");
  await expect(page.getByTestId("income-average")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Главные показатели дохода" }).getByRole("article"),
  ).toHaveCount(3);
  await expect(page.getByTestId("income-plan-panel").locator("details")).not.toHaveAttribute(
    "open",
  );
  await expect(
    page.getByTestId("income-window-30").getByTestId("income-event-provider-701"),
  ).toBeVisible();
  await expect(page.getByRole("group", { name: "Окно ожидаемых выплат" })).toBeVisible();
  await expect(page.getByTestId("income-handoffs-panel").locator("details")).not.toHaveAttribute(
    "open",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-income-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

for (const scene of ["no-closed", "first-closed", "zero", "partial"] as const) {
  test(`ui-v2 Income and plans state ${scene}: honest partial result`, async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installIncomeApi(page, scene);
    await page.goto("/v2/income");
    if (scene === "no-closed") {
      await expect(page.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
      await expect(page.getByTestId("income-average")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("income-average")).toBeVisible();
      if (scene === "first-closed") {
        await expect(page.locator('button[data-testid^="income-history-"]')).toHaveCount(1);
      }
      if (scene === "zero") {
        await expect(page.getByTestId("income-average")).toHaveText("0 ₽");
        await expect(page.getByTestId("income-upcoming-passive")).toHaveText("0 ₽");
      }
      if (scene === "partial") {
        await expect(page.getByTestId("income-ladder-panel")).toContainText(
          "Данные временно недоступны",
        );
        await expect(page.getByTestId("income-average")).toHaveText("15 300 ₽");
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-income-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}
