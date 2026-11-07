import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GoalSummary } from "../api/goals";
import type {
  CashFlowLadder,
  IncomePlanSummary,
  PlanVsActualRow,
  SavingAllocation,
} from "../api/types";
import { createQueryClient } from "../queryClient";
import { makeUiV2Goals, makeUiV2PassiveHistory, uiV2Months } from "../test/uiV2Fixtures";
import UiV2IncomePage from "./UiV2IncomePage";

const money = (amount: string) => ({ amount, currency: "RUB" });

function makeIncomeSummary({ zero = false }: { zero?: boolean } = {}): IncomePlanSummary {
  const amount = (value: string) => money(zero ? "0.00" : value);
  return {
    month: {
      id: 91,
      year: 2031,
      month: 7,
      status: "closed",
      snapshot_date: "2031-07-31",
      source: "manual",
    },
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
  const eventAmount = money(zero ? "0.00" : "8500.00");
  const principal = money(zero ? "0.00" : "100000.00");
  const event = {
    source_kind: "provider" as const,
    source_id: 701,
    expected_date: "2031-08-15",
    flow_type: "income",
    component: "coupon" as const,
    account_id: 3,
    account_name: "Синтетический брокерский счёт",
    instrument_id: 11,
    instrument_name: "Синтетическая облигация",
    expected_net_amount: eventAmount,
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
    ...event,
    source_id: 702,
    component: "redemption_principal" as const,
    expected_net_amount: principal,
  };
  const window = {
    days: 30,
    from_date: "2031-08-01",
    to_date: "2031-08-30",
    passive_income: eventAmount,
    redemption_principal: principal,
    total_cash_flow: money(zero ? "0.00" : "108500.00"),
    items: [event, redemption],
  };
  return {
    as_of_date: "2031-07-31",
    forecast_version: "v1",
    months: [
      {
        year: 2031,
        month: 8,
        coupon: eventAmount,
        dividend: money("0.00"),
        deposit_interest: money("0.00"),
        other_capital_income: money("0.00"),
        redemption_principal: principal,
        passive_income: eventAmount,
        total_cash_flow: money(zero ? "0.00" : "108500.00"),
        is_approximate: false,
        items: [event, redemption],
      },
    ],
    upcoming_14_days: { ...window, days: 14, to_date: "2031-08-14", items: [event] },
    upcoming_30_days: window,
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
  { category: "Связь", expense_type: "mandatory", planned: null, actual: money("3000.00") },
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

function selectedHistory(monthId: number, history = makeUiV2PassiveHistory()) {
  const month = uiV2Months.find((candidate) => candidate.id === monthId);
  const point = history.points.find((candidate) => candidate.reporting_month_id === monthId);
  if (!month || !point || !history.selected_report)
    throw new Error("Synthetic history is incomplete");
  return {
    ...history,
    selected_report: {
      ...history.selected_report,
      reporting_month_id: month.id,
      year: month.year,
      month: month.month,
      snapshot_date: month.snapshot_date,
      passive_income_actual: point.passive_income_actual,
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function setup(path = "/v2/income") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state: {
    months: typeof uiV2Months;
    summary: IncomePlanSummary;
    history: ReturnType<typeof makeUiV2PassiveHistory>;
    ladder: CashFlowLadder;
    goals: GoalSummary[];
    budget: PlanVsActualRow[];
    savings: SavingAllocation[];
    monthsError: boolean;
    summaryError: boolean;
    historyError: boolean;
    ladderError: boolean;
    goalsError: boolean;
    budgetError: boolean;
    savingsError: boolean;
  } = {
    months: uiV2Months,
    summary: makeIncomeSummary(),
    history: makeUiV2PassiveHistory(),
    ladder: makeLadder(),
    goals: makeUiV2Goals(),
    budget,
    savings,
    monthsError: false,
    summaryError: false,
    historyError: false,
    ladderError: false,
    goalsError: false,
    budgetError: false,
    savingsError: false,
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = options?.method ?? "GET";
      reads.push(`${method} ${url.pathname}${url.search}`);
      if (method !== "GET") throw new Error(`Unexpected write: ${method}`);
      let data: unknown;
      let failed = false;
      if (url.pathname === "/api/months") {
        data = state.months;
        failed = state.monthsError;
      } else if (url.pathname === "/api/months/91/income-plan-summary") {
        expect(url.searchParams.get("forecast_version")).toBe("v1");
        data = state.summary;
        failed = state.summaryError;
      } else if (url.pathname === "/api/analytics/passive-income") {
        const monthId = Number(url.searchParams.get("reporting_month_id"));
        data = selectedHistory(monthId, state.history);
        failed = state.historyError;
      } else if (url.pathname === "/api/months/91/cash-flow-ladder") {
        expect(url.searchParams.get("forecast_version")).toBe("v1");
        data = state.ladder;
        failed = state.ladderError;
      } else if (url.pathname === "/api/goals/summary") {
        expect(url.searchParams.get("reporting_month_id")).toBe("91");
        expect(url.searchParams.get("forecast_version")).toBe("v1");
        data = state.goals;
        failed = state.goalsError;
      } else if (url.pathname === "/api/planned-budget/comparison") {
        expect(url.searchParams.get("month_id")).toBe("91");
        data = state.budget;
        failed = state.budgetError;
      } else if (url.pathname === "/api/savings") {
        expect(url.searchParams.get("month_id")).toBe("91");
        data = state.savings;
        failed = state.savingsError;
      } else {
        throw new Error(`Unexpected API: ${url.pathname}`);
      }
      return new Response(
        JSON.stringify(
          failed
            ? { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } }
            : data,
        ),
        { status: failed ? 503 : 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );

  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <Routes>
            <Route path="v2/income" element={<UiV2IncomePage />} />
            <Route path="monthly-close" element={<h1>Monthly Close</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { mount, reads, state };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("UI v2 Income and plans", () => {
  it("renders the passive income figures, removes forecast/goals and keeps principal separate", async () => {
    const { mount, reads } = setup();
    mount();

    expect(await screen.findByRole("heading", { name: "Доход и планы" })).toBeVisible();
    await screen.findByTestId("income-average");
    const headlines = screen.getByRole("region", { name: "Главные показатели дохода" });
    expect(within(headlines).getByTestId("income-average")).toBeVisible();
    expect(within(headlines).getByTestId("income-upcoming-passive")).toBeVisible();
    expect(await within(headlines).findByTestId("income-selected-actual")).toHaveTextContent(
      "17 500 ₽",
    );
    expect(screen.getByTestId("income-average")).toHaveTextContent("15 300 ₽");
    expect(screen.getByTestId("income-upcoming-passive")).toHaveTextContent("8 500 ₽");
    expect(screen.getByTestId("income-upcoming-passive").parentElement).toHaveTextContent(
      "Возврат основной суммы: 100 000 ₽ · не доход",
    );
    expect(screen.queryByTestId("income-forecast-panel")).toBeNull();
    expect(screen.queryByTestId("income-goals-panel")).toBeNull();
    expect(reads.some((read) => read.includes("/api/goals/summary"))).toBe(false);
    expect(screen.getByRole("link", { name: "Доход и планы" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
  });

  it("includes the server period estimate once and leaves dated and monthly amounts intact", async () => {
    const { mount, state } = setup();
    state.ladder.upcoming_30_days = {
      ...state.ladder.upcoming_30_days,
      deposit_interest_estimate: money("1234.56"),
      forecast_passive_income: money("9734.56"),
      forecast_total_cash_flow: money("109734.56"),
      deposit_estimates: [
        {
          deposit_id: 99,
          included_in_forecast: true,
          name: "Синтетический вклад",
          account_name: "Банк",
          amount: money("1234.56"),
        },
      ],
    };
    mount();
    // Overview figures read in whole rubles (P 12.2); the exact sum stays on hover.
    expect(await screen.findByTestId("income-upcoming-passive")).toHaveTextContent("9 735 ₽");
    expect(
      screen.getByTestId("income-upcoming-passive").getAttribute("title")?.replaceAll(" ", " "),
    ).toBe("9 734,56 ₽");
    const table = await screen.findByRole("region", { name: "Ожидаемые проценты по вкладам" });
    expect(table).toHaveTextContent("Синтетический вклад · Банк");
    expect(table).toHaveTextContent("1 234,56 ₽");
    expect(table).toHaveTextContent("дата выплаты неизвестна");
    expect(table.querySelector("time")).toBeNull();
    expect(screen.getByTestId("income-window-30")).toHaveTextContent("8 500 ₽ пассивно");
    fireEvent.click(screen.getByRole("button", { name: "14 дней" }));
    expect(screen.getByTestId("income-upcoming-passive")).toHaveTextContent("9 735 ₽");
    expect(table).toHaveTextContent("30 дней");
    expect(screen.getByTestId("income-coverage")).toHaveTextContent("По прогнозу");
    expect(screen.getByTestId("income-coverage")).toHaveTextContent("прогнозный остаток");
  });

  it("puts the payout ladder before the plan, ends with handoffs and keeps event columns semantic", async () => {
    const { mount } = setup();
    mount();

    await screen.findByTestId("income-history-91");
    const panelOrder = Array.from(
      document.querySelectorAll<HTMLElement>('[data-testid$="-panel"]'),
    ).map((panel) => panel.dataset.testid);
    expect(panelOrder).toEqual([
      "income-history-panel",
      "income-ladder-panel",
      "income-plan-panel",
      "income-handoffs-panel",
    ]);

    const handoffs = within(screen.getByTestId("income-handoffs-panel"));
    expect(handoffs.getByText("НДФЛ и ИИС по выбранному отчётному срезу.")).toBeVisible();
    expect(handoffs.getByRole("link", { name: "Налоги и ИИС →" })).toHaveAttribute(
      "href",
      "/v2/income/tax-iis?month=91",
    );

    const ladder = screen.getByTestId("income-ladder-panel");
    const controls = within(ladder).getByRole("group", { name: "Окно ожидаемых выплат" });
    expect(controls).toHaveAttribute("aria-controls", "income-ladder-content");

    const selectedWindow = within(ladder).getByTestId("income-window-30");
    const coupon = within(selectedWindow).getByTestId("income-event-provider-701");
    expect(coupon.children).toHaveLength(3);
    expect(coupon.children[0]).toHaveTextContent("Купон");
    expect(coupon.children[1]).toHaveTextContent("Синтетическая облигация");
    expect(coupon.children[1]).toHaveTextContent("Синтетический брокерский счёт");
    expect(coupon.children[2]).toHaveTextContent("8 500 ₽");
    // The source is named once for the window, not in every row.
    expect(coupon).not.toHaveTextContent("внешний источник");
    expect(within(selectedWindow).getByText("Источник: внешний источник")).toBeVisible();

    const principal = within(selectedWindow).getByTestId("income-event-provider-702");
    expect(within(principal).getByTitle("Возврат основной суммы")).toHaveTextContent("Погашение");
    expect(principal.children[2]).toHaveTextContent("100 000 ₽ · не доход");
  });

  it("names the source in each row when manual and external payouts share a window", async () => {
    const { mount, state } = setup();
    const window = state.ladder.upcoming_30_days;
    window.items = window.items.map((event) =>
      event.component === "coupon" ? event : { ...event, source_kind: "manual", source_id: 703 },
    );
    mount();

    const selectedWindow = await screen.findByTestId("income-window-30");
    const external = within(selectedWindow).getByTestId("income-event-provider-701");
    const manual = within(selectedWindow).getByTestId("income-event-manual-703");
    expect(external.children[1]).toHaveTextContent(
      "Синтетический брокерский счёт · внешний источник",
    );
    expect(manual.children[1]).toHaveTextContent("Синтетический брокерский счёт · введено вручную");
    // No shared "Источник: …" line that would name both without saying which row is which.
    expect(within(selectedWindow).queryByText(/^Источник:/)).toBeNull();
  });

  it("keeps planning context on latest CLOSED while history selection changes the factual breakdown", async () => {
    const { mount, reads } = setup();
    mount();

    await screen.findByTestId("income-history-91");
    fireEvent.change(
      screen.getByRole("combobox", { name: "Отчёт для разбивки фактического дохода" }),
      {
        target: { value: "90" },
      },
    );

    expect(await screen.findByTestId("test-location")).toHaveTextContent("/v2/income?month=90");
    expect(screen.getByText("Апрель 2031", { exact: false })).toBeVisible();
    await screen.findByTestId("income-average");
    expect(screen.getByTestId("income-average")).toHaveTextContent("15 300 ₽");
    expect(reads.filter((read) => read.includes("/api/months/91/income-plan-summary")).length).toBe(
      1,
    );
    expect(reads.filter((read) => read.includes("/api/months/91/cash-flow-ladder")).length).toBe(1);
    expect(reads.some((read) => read.includes("reporting_month_id=90"))).toBe(true);
  });

  it.each(["12", "999"])(
    "keeps the latest historical average when factual month %s is invalid or not CLOSED",
    async (monthId) => {
      const { mount, reads } = setup(`/v2/income?month=${monthId}`);
      mount();

      expect(await screen.findByTestId("income-average")).toHaveTextContent("15 300 ₽");
      expect(screen.getByTestId("income-history-panel")).toHaveTextContent(
        "Выберите только закрытый отчёт для фактической разбивки",
      );
      expect(
        reads.some((read) =>
          read.includes(`/api/analytics/passive-income?reporting_month_id=${monthId}`),
        ),
      ).toBe(false);
    },
  );

  it("does not turn an empty average window into a measured zero", async () => {
    const { mount, state } = setup();
    state.summary = makeIncomeSummary({ zero: true });
    state.history = makeUiV2PassiveHistory({ zero: true });
    state.history.average.average.amount = "0.00";
    state.history.average.count_months = 0;
    state.history.average.months_used = [];
    state.goals = makeUiV2Goals({ zero: true });
    state.ladder = makeLadder(true);
    mount();

    expect(await screen.findByTestId("income-average")).toHaveTextContent("Недоступно");
    expect(screen.getByText(/Пока нет данных/)).toBeVisible();
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Период среднего дохода" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("0 из 12 закрытых отчётов");
    expect(screen.getByTestId("income-average")).not.toHaveTextContent("0 ₽");
    expect(screen.getByTestId("income-upcoming-passive")).toHaveTextContent("0 ₽");
  });

  it("fails planning or one secondary read closed without blanking confirmed siblings", async () => {
    const planningUnavailable = setup();
    planningUnavailable.state.summaryError = true;
    planningUnavailable.mount();
    expect(await screen.findByTestId("income-average")).toHaveTextContent("15 300 ₽");
    expect(
      within(screen.getByTestId("income-plan-panel")).getByText("Данные временно недоступны"),
    ).toBeVisible();
    cleanup();
    vi.unstubAllGlobals();

    const partial = setup();
    partial.state.ladderError = true;
    partial.state.budgetError = true;
    partial.mount();
    expect(await screen.findByTestId("income-average")).toHaveTextContent("15 300 ₽");
    expect(
      within(screen.getByTestId("income-ladder-panel")).getByText("Данные временно недоступны"),
    ).toBeVisible();
    expect(
      within(screen.getByTestId("income-plan-panel")).getByText("Данные временно недоступны"),
    ).toBeVisible();
  });

  it("draws closed factual months oldest-first as bars and keeps the dropdown newest-first", async () => {
    const user = userEvent.setup();
    const { mount, state } = setup();
    mount();

    const list = await screen.findByRole("region", {
      name: "История фактического пассивного дохода",
    });
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((button) => button.dataset.testid)).toEqual([
      "income-history-88",
      "income-history-89",
      "income-history-90",
      "income-history-91",
    ]);
    expect(state.history.points.map((point) => point.reporting_month_id)).toEqual([88, 89, 90, 91]);
    expect(buttons[3]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[3]).toHaveAccessibleName(/^Июль\s2031:\s17\s500\s₽$/);

    const select = screen.getByRole("combobox", {
      name: "Отчёт для разбивки фактического дохода",
    });
    const options = within(select).getAllByRole("option");
    expect(options.map((option) => option.textContent?.replaceAll("\u00a0", " "))).toEqual([
      "Июль 2031",
      "Май 2031",
      "Апрель 2031",
      "Февраль 2031",
    ]);
    expect(options.map((option) => option.getAttribute("value"))).toEqual(["91", "90", "89", "88"]);
    expect(screen.queryByRole("option", { name: /Август/ })).toBeNull();

    screen.getByTestId("income-history-89").focus();
    await user.tab();
    expect(screen.getByTestId("income-history-90")).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("test-location")).toHaveTextContent("/v2/income?month=90");
    expect(await screen.findByTestId("income-history-90")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Источники\s+·\s+Май\s+2031/)).toBeVisible();
    expect(screen.getByTestId("income-average")).toHaveTextContent("15 300 ₽");
  });

  it("states plan and fact without calling a missing plan unset", async () => {
    const { mount, state } = setup();
    state.budget = [
      {
        category: "Жильё",
        expense_type: "mandatory",
        planned: money("50000.00"),
        actual: money("48000.00"),
      },
      { category: "Связь", expense_type: "mandatory", planned: null, actual: money("3000.00") },
      {
        category: "Подарки",
        expense_type: "discretionary",
        planned: money("1000.00"),
        actual: null,
      },
      {
        category: "Нулевой план",
        expense_type: "discretionary",
        planned: money("0.00"),
        actual: money("250.00"),
      },
      {
        category: "Нулевой план без факта",
        expense_type: "discretionary",
        planned: money("0.00"),
        actual: null,
      },
    ];
    mount();

    expect(await screen.findByText("Жильё")).toBeVisible();
    expect(screen.queryByText(/Отдельный план показывается/)).toBeNull();
    const plan = screen.getByTestId("income-plan-panel");
    const table = within(plan).getByRole("table", { name: "План и факт расходов" });
    expect(within(table).getByRole("columnheader", { name: "Факт" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "План" })).toBeVisible();
    const cells = (category: string) =>
      within(within(table).getByRole("rowheader", { name: category }).closest("tr") as HTMLElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent?.replaceAll(" ", " "));
    // Fact then plan; an absent value is a dash, never "not set" or zero.
    expect(cells("Жильё")).toEqual(["48 000 ₽", "50 000 ₽"]);
    expect(cells("Связь")).toEqual(["3 000 ₽", "—"]);
    expect(cells("Подарки")).toEqual(["—", "1 000 ₽"]);
    expect(cells("Нулевой план")).toEqual(["250 ₽", "0 ₽"]);
    expect(cells("Нулевой план без факта")).toEqual(["—", "0 ₽"]);
    // Mandatory rows are grouped apart from the rest, so the coverage figure is not mistaken for this list.
    expect(within(table).getByRole("columnheader", { name: "Обязательные" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "Остальные" })).toBeVisible();
    expect(plan).not.toHaveTextContent("Не задано");
  });

  it("stops planning reads when there is no CLOSED report", async () => {
    const { mount, state, reads } = setup();
    state.months = [uiV2Months[1]];
    mount();

    expect(await screen.findByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Закрой первый месяц →" })).toHaveAttribute(
      "href",
      "/v2/close",
    );
    expect(screen.queryByTestId("income-average")).toBeNull();
    expect(reads).toEqual(["GET /api/months"]);
  });
});

it("keeps average-period and passive-income explanations behind help buttons", async () => {
  const user = userEvent.setup();
  const { mount, state } = setup();
  state.history.average.configured_start_month = "2031-04";
  mount();

  expect(await screen.findByTestId("income-average")).toHaveTextContent("15 300 ₽");
  expect(screen.queryByRole("tooltip")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Период среднего дохода" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("учёт с апреля 2031");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Что входит в пассивный доход" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("возврат основной суммы сюда не входят");
});
