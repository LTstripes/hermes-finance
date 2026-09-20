import { onlineManager, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Suspense } from "react";

import { createQueryClient, queryKeys } from "../queryClient";
import {
  makeUiV2CapitalHistory,
  makeUiV2Comparison,
  makeUiV2Goals,
  makeUiV2PassiveHistory,
  makeUiV2Workflow,
  uiV2Months,
} from "../test/uiV2Fixtures";
import { UiV2ErrorBoundary, UiV2LoadingFallback } from "../ui-v2/UiV2Entry";
import UiV2Page from "../ui-v2/UiV2Page";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function setup(path = "/v2") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    comparison: makeUiV2Comparison(),
    capital: makeUiV2CapitalHistory(),
    passive: makeUiV2PassiveHistory(),
    goals: makeUiV2Goals(),
    workflow: makeUiV2Workflow(),
    monthsError: false,
    comparisonError: false,
    capitalError: false,
    passiveError: false,
    goalsError: false,
    workflowError: false,
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
      } else if (url.pathname === "/api/analytics/closed-report-comparison") {
        data = state.comparison;
        failed = state.comparisonError;
      } else if (url.pathname === "/api/analytics/capital-composition") {
        data = state.capital;
        failed = state.capitalError;
      } else if (url.pathname === "/api/analytics/passive-income") {
        expect(url.searchParams.get("reporting_month_id")).toBe("91");
        data = state.passive;
        failed = state.passiveError;
      } else if (url.pathname === "/api/goals/summary") {
        expect(url.searchParams.get("reporting_month_id")).toBe("91");
        data = state.goals;
        failed = state.goalsError;
      } else if (url.pathname === "/api/months/12/close-workflow") {
        data = state.workflow;
        failed = state.workflowError;
      } else throw new Error(`Unexpected API: ${url.pathname}`);
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
            <Route path="v2" element={<UiV2Page />} />
            <Route path="months/:monthId/close" element={<h1>Monthly Close</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { client, reads, state, mount };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  onlineManager.setOnline(true);
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("renders the latest CLOSED report as a quiet Home with exactly three canonical KPIs", async () => {
  const { mount, reads } = setup();
  mount();

  expect(await screen.findByRole("heading", { name: "Мои финансы" })).toBeVisible();
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
  expect(screen.getAllByText(/Июль\s+2031/).length).toBeGreaterThan(0);
  expect(screen.getByText("Снимок 31.07.2031")).toBeVisible();
  const kpis = screen.getByRole("region", { name: "Главные показатели" });
  expect(within(kpis).getAllByRole("article")).toHaveLength(3);
  expect(screen.getByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByTestId("v2-capital-change")).toHaveTextContent("+42 600 ₽");
  expect(screen.getByTestId("v2-passive-actual")).toHaveTextContent("17 500 ₽");
  const changePanel = screen
    .getByRole("heading", { name: "Где изменились суммы" })
    .closest("section");
  if (!changePanel) throw new Error("Change panel is missing");
  expect(
    within(changePanel).getByText("Включённые обязательства").nextElementSibling,
  ).toHaveAttribute("data-tone", "negative");
  expect(screen.queryByText(/готовност|провайдер|сверк/i)).toBeNull();
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
});

it("keeps a newer draft separate and routes its single CTA to the server recommendation", async () => {
  const { mount } = setup();
  mount();
  expect(await screen.findByTestId("v2-draft-action")).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=alfa_baseline",
  );
  expect(screen.getByTestId("v2-draft-action")).toHaveTextContent("Август 2031 ещё не закрыт");
  expect(screen.getByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
});

it("shows no financial snapshot when there is no closed report yet", async () => {
  const { mount, state, reads } = setup();
  state.months = [uiV2Months[1]];
  mount();
  expect(await screen.findByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
  expect(screen.queryByTestId("v2-capital")).toBeNull();
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  expect(await screen.findByTestId("v2-draft-action")).toBeVisible();
  expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute("href", "/v1");
});

it("distinguishes an unavailable previous CLOSED base from a genuine zero", async () => {
  const { mount, state } = setup();
  state.months = [uiV2Months[0], uiV2Months[1]];
  state.comparison = makeUiV2Comparison({ firstClosed: true, zero: true });
  state.capital = makeUiV2CapitalHistory({ firstClosed: true, zero: true });
  state.passive = makeUiV2PassiveHistory({ firstClosed: true, zero: true });
  state.goals = makeUiV2Goals({ firstClosed: true, zero: true });
  mount();
  expect(await screen.findByTestId("v2-capital")).toHaveTextContent("0 ₽");
  expect(screen.getByText("Пока нет базы сравнения")).toBeVisible();
  expect(screen.getByTestId("v2-passive-actual")).toHaveTextContent("0 ₽");
  expect(screen.getByTestId("v2-passive-history")).toHaveAttribute("data-point-count", "1");
  expect(screen.getAllByText(/Среднее 0 ₽ · 1 из 12 закрытых отчётов/i)).toHaveLength(2);
  expect(screen.getAllByText("0,00%")).toHaveLength(2);
  expect(screen.getByText("Нужны два закрытых отчёта для сравнения")).toBeVisible();
});

it("uses last 3/12/all CLOSED report records without manufacturing calendar months", async () => {
  const { mount } = setup();
  mount();
  expect(await screen.findByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "2");
  expect(screen.getByText(/последние 4 закрытых отчёта/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "3 месяца" }));
  expect(screen.getByRole("button", { name: "12 месяцев" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Всё время" })).toBeInTheDocument();
  expect(screen.getByText(/последние 3 закрытых отчёта/i)).toBeVisible();
  expect(screen.getByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "1");
  expect(
    screen.getByText(/Пропуски показаны разрывами; значения не интерполируются/i),
  ).toBeVisible();
});

it("keeps liabilities and negative net visible when every asset slice is zero", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Synthetic comparison has no current report");
  for (const item of state.comparison.current.allocation) item.amount.amount = "0.00";
  state.comparison.current.liquid_assets_total.amount = "0.00";
  state.comparison.current.included_debts.amount = "400000.00";
  state.comparison.current.liquid_capital_net.amount = "-400000.00";
  mount();
  const title = await screen.findByRole("heading", { name: "Структура активов" });
  const panel = title.closest("section");
  if (!panel) throw new Error("Composition panel is missing");
  expect(
    await within(panel).findByText("В закрытом снимке нет положительных ликвидных активов"),
  ).toBeVisible();
  expect(within(panel).getByText("− 400 000 ₽")).toBeVisible();
  expect(within(panel).getByText("−400 000 ₽")).toBeVisible();
});

it("does not present an empty passive-income window as a measured zero average", async () => {
  const { mount, state } = setup();
  state.passive.average.average.amount = "0.00";
  state.passive.average.count_months = 0;
  state.passive.average.configured_start_month = "2031-08";
  state.passive.average.months_used = [];
  for (const point of state.passive.points) point.included_in_average_window = false;
  const passiveGoal = state.goals.find((goal) => goal.goal_type === "passive_income");
  if (!passiveGoal) throw new Error("Synthetic passive-income goal is missing");
  passiveGoal.achievement_forecast.current_value = {
    amount: "0.00",
    currency: "RUB",
  };
  passiveGoal.achievement_forecast.progress_pct = "0.00";
  passiveGoal.achievement_forecast.passive_income_months_count = 0;
  passiveGoal.achievement_forecast.passive_income_months_used = [];
  mount();
  expect(await screen.findByTestId("v2-passive-actual")).toHaveTextContent("17 500 ₽");
  expect(
    screen.getAllByText(/Среднее пока недоступно · 0 из 12 закрытых отчётов · учёт с Август 2031/i),
  ).toHaveLength(2);
  expect(screen.queryByText(/^Среднее 0 ₽/)).toBeNull();
  expect(screen.queryByText("Пассивный доход", { selector: "h3" })).toBeNull();
  expect(screen.getByText("Резервный капитал")).toBeVisible();
});

it("plots only passive-income records included by the backend average window", async () => {
  const { mount, state } = setup();
  state.passive.points[0].included_in_average_window = false;
  state.passive.points[1].included_in_average_window = false;
  state.passive.average.average.amount = "16550.00";
  state.passive.average.count_months = 2;
  state.passive.average.configured_start_month = "2031-05";
  state.passive.average.months_used = ["2031-05", "2031-07"];
  const passiveGoal = state.goals.find((goal) => goal.goal_type === "passive_income");
  if (!passiveGoal) throw new Error("Synthetic passive-income goal is missing");
  passiveGoal.achievement_forecast.current_value = { amount: "16550.00", currency: "RUB" };
  passiveGoal.achievement_forecast.progress_pct = "33.10";
  passiveGoal.achievement_forecast.remaining_amount = { amount: "33450.00", currency: "RUB" };
  passiveGoal.achievement_forecast.passive_income_history_start_month = "2031-05";
  passiveGoal.achievement_forecast.passive_income_months_count = 2;
  passiveGoal.achievement_forecast.passive_income_months_used = ["2031-05", "2031-07"];
  mount();
  expect(await screen.findByTestId("v2-passive-history")).toHaveAttribute("data-point-count", "2");
  expect(screen.getByText("На графике только отчёты, вошедшие в среднее: 2.")).toBeVisible();
});

it("keeps other Home blocks usable when one financial widget fails", async () => {
  const { mount, state } = setup();
  state.passiveError = true;
  mount();
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
  expect(screen.getByTestId("v2-capital-history")).toBeVisible();
  expect(screen.queryByTestId("v2-passive-actual")).toBeNull();
  expect(screen.getByRole("heading", { level: 2, name: "Пассивный доход" })).toBeVisible();
  expect(screen.getAllByText("Данные временно недоступны").length).toBeGreaterThan(0);
});

it("fails only the mismatched read model closed instead of relabelling another report", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Synthetic comparison has no current report");
  state.comparison.current.reporting_month_id = 999;
  mount();
  expect(await screen.findByTestId("v2-passive-actual")).toBeVisible();
  expect(screen.queryByTestId("v2-capital")).toBeNull();
  expect(screen.queryByTestId("v2-capital-change")).toBeNull();
});

it("hides cached widget values while offline revalidation is paused", async () => {
  const { mount, client, reads } = setup();
  mount();
  await screen.findByTestId("v2-passive-actual");
  const readCount = reads.length;
  act(() => {
    onlineManager.setOnline(false);
    void client.invalidateQueries({ queryKey: queryKeys.passiveIncomeHistory(91) });
  });
  await waitFor(() => expect(screen.queryByTestId("v2-passive-actual")).toBeNull());
  expect(screen.getByTestId("v2-capital")).toBeVisible();
  expect(reads).toHaveLength(readCount);
  await act(async () => onlineManager.setOnline(true));
  expect(await screen.findByTestId("v2-passive-actual")).toBeVisible();
});

it("renders only active goals with backend-supported progress and no invented ETA", async () => {
  const { mount, state } = setup();
  state.goals.push({
    ...state.goals[0],
    id: 99,
    name: "Неподдерживаемая цель",
    achievement_forecast: {
      ...state.goals[0].achievement_forecast,
      goal_id: 99,
      current_value: null,
      progress_pct: null,
      status: "unsupported",
    },
  });
  mount();
  expect(await screen.findByText("Резервный капитал")).toBeVisible();
  expect(screen.getByText("Пассивный доход", { selector: "h3" })).toBeVisible();
  expect(screen.queryByText("Неподдерживаемая цель")).toBeNull();
  expect(screen.queryByText(/достигн|ETA|прогноз.*дата/i)).toBeNull();
});

it("fails the whole goals widget closed on goal identity or version mismatch", async () => {
  const { mount, state } = setup();
  state.goals[0].achievement_forecast.goal_id = 999;
  (state.goals[1].achievement_forecast as { method_version: string }).method_version =
    "goal_achievement_v2";
  mount();
  await screen.findByTestId("v2-capital");
  const title = screen.getByRole("heading", { name: "Ключевые цели" });
  const panel = title.closest("section");
  if (!panel) throw new Error("Goals panel is missing");
  expect(within(panel).getByText("Данные временно недоступны")).toBeVisible();
  expect(within(panel).queryByText("Резервный капитал")).toBeNull();
  expect(within(panel).queryByText("Пассивный доход")).toBeNull();
});

it("fails the goals widget closed on forecast-sourced progress provenance", async () => {
  const { mount, state } = setup();
  state.goals[0].achievement_forecast.source_forecast_version = "forecast_v2";
  mount();
  await screen.findByTestId("v2-capital");
  const title = screen.getByRole("heading", { name: "Ключевые цели" });
  const panel = title.closest("section");
  if (!panel) throw new Error("Goals panel is missing");
  expect(within(panel).getByText("Данные временно недоступны")).toBeVisible();
  expect(within(panel).queryByText("Резервный капитал")).toBeNull();
});

it("preserves a valid legacy month/step only in the explicit v1 escape", async () => {
  const { mount } = setup("/v2?month=12&step=actual_payouts");
  mount();
  expect(await screen.findByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute("href", "/months/12/close#actual_payouts");
  expect(screen.getByTestId("test-location")).toHaveTextContent("/v2?month=12&step=actual_payouts");
});

it.each(["/v2?month=012&step=actual_payouts", "/v2?month=12&month=91&step=actual_payouts"])(
  "rejects malformed or duplicate month context in the v1 escape: %s",
  async (path) => {
    const { mount } = setup(path);
    mount();
    await screen.findByTestId("v2-capital");
    expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute("href", "/months/91");
  },
);

it("rejects duplicate step context without discarding the valid month", async () => {
  const { mount } = setup("/v2?month=12&step=actual_payouts&step=review");
  mount();
  await screen.findByTestId("v2-capital");
  expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute(
    "href",
    "/months/12",
  );
});

it("recovers the root report list without querying a guessed report", async () => {
  const { mount, state, reads } = setup();
  state.monthsError = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить отчёты");
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  state.monthsError = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
});

it("links the report-context line to the contextual archive", async () => {
  const { mount } = setup();
  mount();

  await screen.findByTestId("v2-capital");
  expect(screen.getByRole("link", { name: "История отчётов →" })).toHaveAttribute(
    "href",
    "/v2/reports",
  );
});

describe("UI v2 isolation", () => {
  it("keeps the v1 escape in the initial lazy-loading fallback", () => {
    const pending = new Promise<never>(() => undefined);
    function Pending(): never {
      throw pending;
    }

    render(
      <MemoryRouter>
        <Suspense fallback={<UiV2LoadingFallback />}>
          <Pending />
        </Suspense>
      </MemoryRouter>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Загружаем новый интерфейс");
    expect(screen.getByRole("link", { name: "Перейти в UI v1" })).toHaveAttribute("href", "/v1");
  });

  it("keeps the v1 rollback path when the lazy Home crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Broken(): never {
      throw new Error("synthetic component failure");
    }
    render(
      <MemoryRouter>
        <UiV2ErrorBoundary>
          <Broken />
        </UiV2ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Новый интерфейс не загрузился");
    expect(screen.getByRole("link", { name: "Перейти в UI v1" })).toHaveAttribute("href", "/v1");
  });
});
