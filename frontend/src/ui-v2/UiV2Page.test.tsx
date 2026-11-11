import { onlineManager, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Suspense } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient, queryKeys } from "../queryClient";
import {
  makeUiV2CapitalHistory,
  makeUiV2Comparison,
  makeUiV2Goals,
  makeUiV2PassiveHistory,
  makeUiV2Workflow,
  uiV2Accounts,
  uiV2Months,
} from "../test/uiV2Fixtures";
import { UiV2ErrorBoundary, UiV2LoadingFallback } from "./UiV2Entry";
import UiV2Page from "./UiV2Page";
import { shortWholeRub } from "./UiV2HomeCharts";
import { overallFixture } from "./returns/overallFixtures";
import { m } from "./returns/fixtures";
import { brokerageResult } from "./returns/dashboard";
import { displayWhole } from "./returns/model";

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
    overall: overallFixture(),
    returnsWait: null as Promise<void> | null,
    returnsError: false,
    monthsError: false,
    comparisonError: false,
    comparisonWait: null as Promise<void> | null,
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
      } else if (url.pathname === "/api/returns/overall") {
        expect(url.searchParams.get("include_instrument_summaries")).toBe("true");
        await state.returnsWait;
        data = state.overall;
        failed = state.returnsError;
      } else if (url.pathname === "/api/accounts") {
        data = uiV2Accounts;
      } else if (url.pathname === "/api/analytics/closed-report-comparison") {
        data = structuredClone(state.comparison);
        await state.comparisonWait;
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
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    setTimeout(() => callback(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

it("defers Returns until main widgets settle and keeps capital visible during the slow read", async () => {
  const { mount, reads, state } = setup();
  let finishMain = () => {};
  let finishReturns = () => {};
  state.comparisonWait = new Promise<void>((resolve) => {
    finishMain = resolve;
  });
  state.returnsWait = new Promise<void>((resolve) => {
    finishReturns = resolve;
  });
  mount();
  await screen.findByTestId("v2-passive-actual");
  expect(reads.some((read) => read.includes("/returns/overall"))).toBe(false);
  await act(async () => finishMain());
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
  await waitFor(() => expect(reads.some((read) => read.includes("/returns/overall"))).toBe(true));
  expect(screen.getByText("Загружаем доходность бумаг")).toBeInTheDocument();
  await act(async () => finishReturns());
  expect(await screen.findByTestId("v2-home-returns-total")).toHaveTextContent(
    displayWhole(brokerageResult(state.overall, "all").amount, true),
  );
  expect(reads.some((read) => /forecast|payout-calendar/.test(read))).toBe(false);
});

it("ranks three results on each side by instrument, preserves zero/unknown/partial and shares the Returns cache", async () => {
  const { mount, client, state, reads } = setup();
  const template = state.overall.instruments[1];
  state.overall.instruments = [
    "4000",
    "3000",
    "2000",
    "1000",
    "-4000",
    "-3000",
    "-2000",
    "-1000",
    "0",
    null,
    "90000",
  ].map((value, index) => ({
    ...template,
    isin: `SYNTH${index}`,
    name: `Учебная бумага ${index}`,
    accounts: [
      {
        ...template.accounts[0],
        pnl: { ...m(value), reason_codes: index === 10 ? ["clean_partial_result"] : [] },
        account_link: {
          status: "linked",
          financial_account_id: 3,
          account_type: "brokerage",
          source_account_id: "SYNTHETIC-PRIVATE-ID",
          label: "Учебный счёт",
          reason_codes: [],
        },
      },
    ],
  }));
  state.overall.source_accounts[0].account_link =
    state.overall.instruments[0].accounts[0].account_link;
  client.setQueryData(["returns", "overall", "summaries"], state.overall);
  mount();
  const panel = await screen.findByRole("region", { name: "Доходность бумаг" });
  expect(
    await within(panel).findByText(/в плюсе 4 · в минусе 4 · без итога 2 · без изменения 1/),
  ).toBeVisible();
  const chart = within(panel).getByRole("list");
  expect(within(chart).getAllByRole("listitem")).toHaveLength(6);
  expect(
    within(chart)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(
    [0, 1, 2, 4, 5, 6].map((index) => `Учебная бумага ${index}Синтетический брокерский счёт`),
  );
  expect(chart).not.toHaveTextContent("SYNTHETIC-PRIVATE-ID");
  expect(within(panel).getByRole("link", { name: "Все бумаги →" })).toHaveAttribute(
    "href",
    "/v2/returns",
  );
  expect(reads.some((read) => read.includes("/returns/overall"))).toBe(false);
});

it("keeps Returns failure local, retries and hides cached success after invalidation or failure", async () => {
  const { mount, client, state } = setup();
  state.returnsError = true;
  mount();
  const panel = await screen.findByRole("region", { name: "Доходность бумаг" });
  await within(panel).findByText("Доходность временно недоступна.");
  expect(screen.getByTestId("v2-capital")).toBeVisible();
  expect(within(panel).queryByRole("alert")).toBeNull();
  state.returnsError = false;
  fireEvent.click(within(panel).getByRole("button", { name: "Повторить" }));
  await screen.findByTestId("v2-home-returns-total");
  state.returnsWait = new Promise<void>(() => {});
  act(() => {
    void client.invalidateQueries({ queryKey: ["returns", "overall"] });
  });
  await waitFor(() => expect(screen.queryByTestId("v2-home-returns-total")).toBeNull());
  expect(screen.getByTestId("v2-capital")).toBeVisible();
});

afterEach(() => {
  onlineManager.setOnline(true);
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("leads Home with one capital figure, its change and a few secondary facts", async () => {
  const { mount, reads, state } = setup();
  state.comparison.liquid_capital_net_delta_pct = "1.54";
  mount();

  expect(await screen.findByRole("heading", { name: "Мои финансы" })).toBeVisible();
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
  expect(screen.getByTestId("v2-report-context")).toHaveTextContent(
    /Июль\s+2031 · закрыт · снимок 31\.07\.2031/,
  );
  const hero = screen.getByRole("region", { name: "Главные показатели" });
  expect(within(hero).queryAllByRole("article")).toHaveLength(0);
  expect(screen.getByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByTestId("v2-capital-change")).toHaveTextContent("+42 600 ₽");
  expect(screen.getByTestId("v2-capital-change")).toHaveAccessibleDescription("к маю");
  expect(screen.getByTestId("v2-capital-change-pct")).toHaveTextContent("· +1,5%");
  expect(within(hero).getByText("Активы")).toBeVisible();
  expect(within(hero).getByText("Обязательства")).toBeVisible();
  expect(within(hero).getByText(/До цели 5 млн/)).toBeVisible();
  expect(screen.getByTestId("v2-passive-actual")).toHaveTextContent("17 500 ₽");
  expect(screen.getByRole("link", { name: "Все цели →" })).toHaveAttribute(
    "href",
    "/v2/income/goals?month=91",
  );
  const changePanel = screen
    .getByRole("heading", { name: "Что изменило капитал" })
    .closest("section");
  if (!changePanel) throw new Error("Change panel is missing");
  expect(within(changePanel).getByText("Вклад обязательств").nextElementSibling).toHaveAttribute(
    "data-tone",
    "negative",
  );
  expect(screen.queryByText(/готовност|провайдер|сверк/i)).toBeNull();
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
});

it("names affected accounts beside the known subtotal and comparison", async () => {
  const { mount, state } = setup();
  const currentPartial = {
    status: "partial" as const,
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  if (!state.comparison.current || !state.comparison.previous)
    throw new Error("Missing comparison fixtures");
  state.comparison.current.portfolio_source_coverage = currentPartial;
  state.comparison.previous.portfolio_source_coverage = {
    ...currentPartial,
    missing_account_ids: [3],
  };
  // The combined API coverage has no IDs, but each endpoint does.
  state.comparison.liquid_capital_net_delta_coverage = {
    ...currentPartial,
    missing_account_ids: [],
  };
  mount();
  expect(await screen.findByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  const hero = screen.getByRole("region", { name: "Главные показатели" });
  const change = screen.getByRole("heading", { name: "Что изменило капитал" }).closest("section");
  if (!change) throw new Error("Missing change section");
  await waitFor(() =>
    expect(within(hero).getByTestId("portfolio-coverage-note")).toHaveTextContent(
      "Синтетический старый вклад",
    ),
  );
  const note = within(change).getByTestId("portfolio-coverage-note");
  expect(note).toHaveTextContent("Синтетический брокерский счёт, Синтетический старый вклад");
  fireEvent.click(within(note).getByRole("button", { name: "Подробнее" }));
  expect(
    note.textContent?.match(/Синтетический брокерский счёт, Синтетический старый вклад/g),
  ).toHaveLength(2);
});

it("renders a backend pair once, with gross endpoints and a zero net delta", async () => {
  const { mount, state } = setup();
  const explanation = state.comparison.explanation;
  if (!explanation) throw new Error("Missing explanation");
  explanation.pairs = [
    {
      account_id: 7,
      account_name: "Synthetic funded account",
      previous: {
        debt_id: 5,
        debt_name: "Synthetic prior card",
        account_balance: { amount: "100.00", currency: "RUB" },
        debt_balance: { amount: "80.00", currency: "RUB" },
        net_contribution: { amount: "20.00", currency: "RUB" },
      },
      current: {
        debt_id: 6,
        debt_name: "Synthetic current card",
        account_balance: { amount: "40.00", currency: "RUB" },
        debt_balance: { amount: "20.00", currency: "RUB" },
        net_contribution: { amount: "20.00", currency: "RUB" },
      },
      net_contribution_delta: { amount: "0.00", currency: "RUB" },
    },
  ];
  explanation.noncomparable_account_ids = [8];
  explanation.residual_asset_class_deltas[0].amount.amount = "52660.00";
  explanation.residual_debt_contribution_delta.amount = "-10060.00";
  mount();
  const summary = await screen.findByText("Synthetic funded account");
  expect(screen.getAllByText("Synthetic funded account")).toHaveLength(1);
  expect(summary.closest("li")).toHaveTextContent("0 ₽");
  fireEvent.click(summary);
  expect(screen.getByText(/Synthetic prior card/)).toHaveTextContent("счёт 100 ₽");
  expect(screen.getByText(/Synthetic current card/)).toHaveTextContent("счёт 40 ₽");
  expect(screen.getByRole("button", { name: "Почему часть счетов не объединена" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Почему часть счетов не объединена" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Для части счетов нет явной связи");
  expect(screen.queryByText(/Связь не устанавливает источник погашения/)).toBeNull();
});

it("withholds an unavailable or unreconciled explanation", async () => {
  const { mount, state } = setup();
  if (!state.comparison.explanation) throw new Error("Missing explanation");
  state.comparison.explanation.reconciles = false;
  mount();
  expect(await screen.findByText("Разложение изменения недоступно")).toBeVisible();
  expect(screen.queryByText("Вклад обязательств")).toBeNull();
});

it("hides cached pair facts during refetch and shows only the fresh readback", async () => {
  const { mount, client, state } = setup();
  mount();
  await screen.findByText("Вклад обязательств");
  act(() => {
    onlineManager.setOnline(false);
    void client.invalidateQueries({ queryKey: queryKeys.closedReportComparison });
  });
  await waitFor(() => expect(screen.queryByText("Вклад обязательств")).toBeNull());
  if (!state.comparison.explanation) throw new Error("Missing explanation");
  state.comparison.explanation.noncomparable_account_ids = [77];
  await act(async () => onlineManager.setOnline(true));
  expect(
    await screen.findByRole("button", { name: "Почему часть счетов не объединена" }),
  ).toBeVisible();
});

it("rejects a comparison whose previous CLOSED endpoint is stale", async () => {
  const { mount, state } = setup();
  if (!state.comparison.previous) throw new Error("Missing previous endpoint");
  state.comparison.previous.reporting_month_id = 89;
  mount();
  await screen.findByRole("heading", { name: "Мои финансы" });
  await waitFor(() => expect(screen.getByTestId("v2-capital-history")).toBeVisible());
  expect(screen.queryByText("Вклад обязательств")).toBeNull();
  expect(screen.queryByTestId("v2-capital-change")).toBeNull();
});

it("ignores a late old comparison after a corrected readback has settled", async () => {
  const { mount, client, state, reads } = setup();
  mount();
  await screen.findByText("Вклад обязательств");
  let release!: () => void;
  state.comparisonWait = new Promise<void>((resolve) => {
    release = resolve;
  });
  const priorReads = reads.length;
  act(() => {
    void client.invalidateQueries({ queryKey: queryKeys.closedReportComparison });
  });
  await waitFor(() => expect(reads.length).toBeGreaterThan(priorReads));
  await waitFor(() => expect(screen.queryByText("Вклад обязательств")).toBeNull());
  if (!state.comparison.explanation) throw new Error("Missing explanation");
  state.comparison.explanation.noncomparable_account_ids = [77];
  state.comparisonWait = null;
  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.closedReportComparison });
  });
  expect(
    await screen.findByRole("button", { name: "Почему часть счетов не объединена" }),
  ).toBeVisible();
  await act(async () => {
    release();
  });
  expect(screen.getByRole("button", { name: "Почему часть счетов не объединена" })).toBeVisible();
  expect(client.getQueryData(queryKeys.closedReportComparisonBasic)).toEqual(state.comparison);
});

it("keeps a newer draft separate and routes its single CTA to the server recommendation", async () => {
  const { mount } = setup();
  mount();
  expect(await screen.findByTestId("v2-draft-action")).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=market_quotes",
  );
  expect(screen.getByTestId("v2-draft-action")).toHaveTextContent("Август 2031 ещё не закрыт");
  expect(screen.getByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  // The Month checklist is a Month page read; Home keeps the lighter workflow read.
  const workflowUrls = vi
    .mocked(fetch)
    .mock.calls.map(([input]) => String(input))
    .filter((url) => url.includes("/close-workflow"));
  expect(workflowUrls.length).toBeGreaterThan(0);
  expect(workflowUrls.some((url) => url.includes("include_checklist"))).toBe(false);
});

it("shows no financial snapshot when there is no closed report yet", async () => {
  const { mount, state, reads } = setup();
  state.months = [uiV2Months[1]];
  mount();
  expect(await screen.findByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Закрой первый месяц →" })).toHaveAttribute(
    "href",
    "/v2/close",
  );
  expect(screen.queryByTestId("v2-capital")).toBeNull();
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  expect(await screen.findByTestId("v2-draft-action")).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "UI v1: предыдущий интерфейс →" }),
  ).not.toBeInTheDocument();
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
  expect(screen.queryByTestId("v2-capital-change")).toBeNull();
  expect(screen.getByTestId("v2-passive-actual")).toHaveTextContent("0 ₽");
  expect(screen.getByTestId("v2-passive-history")).toHaveAttribute("data-point-count", "1");
  expect(screen.getByTestId("v2-passive-average")).toHaveTextContent("0 ₽");
  fireEvent.click(screen.getByRole("button", { name: "Период среднего дохода" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("1 из 12 закрытых отчётов");
  const goals = screen.getByRole("heading", { name: "Цели" }).closest("section");
  if (!goals) throw new Error("Goals panel is missing");
  expect(within(goals).getAllByText("0%").length).toBeGreaterThan(0);
  expect(within(goals).getByText("Резервный капитал")).toBeVisible();
  expect(screen.getByText("Нужны два закрытых отчёта для сравнения")).toBeVisible();
});

it("uses last 3/12/all CLOSED report records without manufacturing calendar months", async () => {
  const { mount } = setup();
  mount();
  expect(await screen.findByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "2");
  expect(screen.getByTestId("v2-capital-history")).toHaveAttribute("data-point-count", "4");
  fireEvent.click(screen.getByRole("button", { name: "3 месяца" }));
  expect(screen.getByRole("button", { name: "12 месяцев" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Всё время" })).toBeInTheDocument();
  expect(screen.getByTestId("v2-capital-history")).toHaveAttribute("data-point-count", "3");
  expect(screen.getByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "1");
  expect(
    screen.queryByText(/Пропуски показаны разрывами; значения не интерполируются/i),
  ).toBeNull();
});

it("keeps liabilities and negative net visible when every asset slice is zero", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Synthetic comparison has no current report");
  for (const item of state.comparison.current.allocation) item.amount.amount = "0.00";
  state.comparison.current.liquid_assets_total.amount = "0.00";
  state.comparison.current.included_debts.amount = "400000.00";
  state.comparison.current.liquid_capital_net.amount = "-400000.00";
  mount();
  const title = await screen.findByRole("heading", { name: "Где лежат деньги" });
  const panel = title.closest("section");
  if (!panel) throw new Error("Composition panel is missing");
  expect(
    await within(panel).findByText("В закрытом снимке нет положительных ликвидных активов"),
  ).toBeVisible();
  const hero = screen.getByRole("region", { name: "Главные показатели" });
  expect(screen.getByTestId("v2-capital")).toHaveTextContent("−400 000 ₽");
  expect(within(hero).getByText("Обязательства").nextElementSibling).toHaveTextContent(
    "−400 000 ₽",
  );
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
  expect(screen.getByText("Пока нет данных")).toBeVisible();
  expect(screen.queryByTestId("v2-passive-average")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Период среднего дохода" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "0 из 12 закрытых отчётов · учёт с августа 2031",
  );
  expect(screen.queryByText(/^Среднее за 12 мес: 0 ₽/)).toBeNull();
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
  expect(screen.getByTestId("v2-passive-average")).toHaveTextContent("16 550 ₽");
  expect(screen.queryByText(/На графике только отчёты/)).toBeNull();
  fireEvent.click(screen.getAllByRole("button", { name: "Период среднего дохода" })[0]);
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "2 из 12 закрытых отчётов · учёт с мая 2031",
  );
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
  const title = screen.getByRole("heading", { name: "Цели" });
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
  const title = screen.getByRole("heading", { name: "Цели" });
  const panel = title.closest("section");
  if (!panel) throw new Error("Goals panel is missing");
  expect(within(panel).getByText("Данные временно недоступны")).toBeVisible();
  expect(within(panel).queryByText("Резервный капитал")).toBeNull();
});

it("keeps latest closed facts and the URL without rendering a legacy escape", async () => {
  const { mount } = setup("/v2?month=12&step=actual_payouts");
  mount();
  expect(await screen.findByTestId("v2-capital")).toHaveTextContent("2 803 900 ₽");
  expect(
    screen.queryByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).not.toBeInTheDocument();
  expect(screen.getByTestId("test-location")).toHaveTextContent("/v2?month=12&step=actual_payouts");
});

it.each(["/v2?month=012&step=actual_payouts", "/v2?month=12&month=91&step=actual_payouts"])(
  "renders no legacy escape for malformed or duplicate context: %s",
  async (path) => {
    const { mount } = setup(path);
    mount();
    await screen.findByTestId("v2-capital");
    expect(
      screen.queryByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
    ).not.toBeInTheDocument();
  },
);

it("renders no legacy escape for duplicate step context", async () => {
  const { mount } = setup("/v2?month=12&step=actual_payouts&step=review");
  mount();
  await screen.findByTestId("v2-capital");
  expect(
    screen.queryByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).not.toBeInTheDocument();
});

it("recovers the root report list without querying a guessed report", async () => {
  const { mount, state, reads } = setup();
  state.monthsError = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить");
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

    expect(screen.getByRole("status")).toHaveTextContent("Загружаем основной интерфейс");
    expect(screen.getByRole("link", { name: "Мои финансы" })).toHaveAttribute("href", "/v2");
  });

  it("offers a reload when the lazy Home crashes", () => {
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
    expect(screen.getByRole("alert")).toHaveTextContent("Основной интерфейс не загрузился");
    expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /UI v1/ })).not.toBeInTheDocument();
  });
});

it("shows the configured April boundary in genitive only on disclosure", async () => {
  const { mount, state } = setup();
  state.passive.average.configured_start_month = "2031-04";
  mount();

  await screen.findByTestId("v2-passive-actual");
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(screen.getAllByRole("button", { name: "Период среднего дохода" })[0]);
  expect(screen.getByRole("tooltip")).toHaveTextContent("учёт с апреля 2031");
});

it("shows unknown capital totals as a dash, not zero, when the closed month has no snapshots", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Synthetic comparison has no current report");
  state.comparison.current.portfolio_source_coverage = {
    status: "unavailable",
    reason_codes: [],
    missing_account_ids: [],
  };
  state.comparison.current.liquid_assets_total.amount = "0.00";
  state.comparison.current.included_debts.amount = "0.00";
  state.comparison.current.liquid_capital_net.amount = "0.00";
  for (const item of state.comparison.current.allocation) item.amount.amount = "0.00";
  mount();
  expect(await screen.findByTestId("v2-capital")).toHaveTextContent("—");
  const hero = screen.getByRole("region", { name: "Главные показатели" });
  expect(within(hero).getByText("Активы").nextElementSibling).toHaveTextContent(/^—$/);
  expect(within(hero).getByText("Обязательства").nextElementSibling).toHaveTextContent(/^—$/);
  expect(within(hero).queryByText(/^0 ₽$/)).toBeNull();
  const allocation = screen.getByRole("heading", { name: "Где лежат деньги" }).closest("section");
  if (!allocation) throw new Error("Allocation panel is missing");
  expect(within(allocation).getByText("Нет снимков капитала")).toBeVisible();
  expect(
    within(allocation).queryByText("В закрытом снимке нет положительных ликвидных активов"),
  ).toBeNull();
});

it("never shows 100 % for a capital goal that is not reached, in the facts or the ring", async () => {
  const { mount, state } = setup();
  const capitalGoal = state.goals.find((goal) => goal.goal_type === "capital");
  if (!capitalGoal) throw new Error("Synthetic capital goal is missing");
  capitalGoal.achievement_forecast.progress_pct = "99.50";
  capitalGoal.achievement_forecast.remaining_amount = { amount: "25000.00", currency: "RUB" };
  mount();
  await screen.findByTestId("v2-capital");
  const hero = screen.getByRole("region", { name: "Главные показатели" });
  expect(within(hero).getByText(/До цели 5 млн/).nextElementSibling).toHaveTextContent(/· 99%$/);
  expect(screen.queryByText(/100%/)).toBeNull();
  const goals = screen.getByRole("heading", { name: "Цели" }).closest("section");
  if (!goals) throw new Error("Goals panel is missing");
  expect(within(goals).getAllByText("99%").length).toBeGreaterThan(0);
});

it.each(["0.01", "40.00", "99.99"])(
  "keeps a positive share under 0.1 percent visible (%s)",
  async (amount) => {
    const { mount, state } = setup();
    const current = state.comparison.current;
    if (!current) throw new Error("Missing synthetic snapshot");
    current.liquid_assets_total.amount = "100000.00";
    current.allocation = [{ asset_class: "cash", amount: { amount, currency: "RUB" } }];
    mount();
    const panel = (await screen.findByRole("heading", { name: "Где лежат деньги" })).closest(
      "section",
    );
    if (!panel) throw new Error("Missing composition panel");
    expect(await within(panel).findByText("<0,1%")).toBeVisible();
    expect(within(panel).getByText("Деньги")).toBeVisible();
  },
);

it.each([
  ["634.49", "634"],
  ["634.50", "635"],
  ["-634.50", "−635"],
  ["0.01", "0"],
  ["-0.49", "0"],
])("rounds waterfall labels to whole rubles (%s)", (amount, label) => {
  expect(shortWholeRub(amount)).toBe(label);
});
