import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import { makeCapitalDraft } from "../test/capitalDraftFixtures";
import type { BrokerMonthReadback } from "../api/brokerMonths";
import {
  makeUiV2Cash,
  makeUiV2CapitalHistory,
  makeUiV2Comparison,
  makeUiV2Dashboard,
  makeUiV2Debts,
  makeUiV2Deposits,
  makeUiV2Performance,
  makeUiV2Positions,
  makeUiV2Properties,
  makeUiV2RiskAllocation,
  uiV2Accounts,
  uiV2CapitalMonthId,
  uiV2CapitalPreviousMonthId,
  uiV2Instruments,
  uiV2Months,
} from "../test/uiV2Fixtures";
import UiV2CapitalPage from "./UiV2CapitalPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

const EMPTY_REFS = {
  account_ids: [],
  reporting_month_ids: [],
  external_flow_ids: [],
  legacy_flow_ids: [],
  movement_ids: [],
  boundary_group_ids: [],
  dates: [],
};

/** Readiness projection mirroring the performance fixture state (synthetic only). */
function makeReadiness(performance: ReturnType<typeof makeUiV2Performance>) {
  const available = performance.xirr.availability === "available";
  return {
    schema_version: 1,
    scope: "portfolio",
    account_id: null,
    start_date: "2031-05-31",
    end_date: "2031-07-31",
    performance_currency: "RUB",
    xirr: { ...performance.xirr, account_id: null },
    twrr: performance.twrr,
    evidence: {
      scope: "portfolio",
      account_id: null,
      start_date: "2031-05-31",
      end_date: "2031-07-31",
      performance_currency: "RUB",
      availability: available ? "available" : "not_computable",
      reason_codes: [],
      scope_membership: {
        status: "complete",
        account_ids: [3],
        missing_or_ambiguous_account_ids: [],
        reason_codes: [],
      },
      cash_boundary_coverage: {
        status: "complete",
        account_ids: [3],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
      in_kind_boundary_coverage: {
        status: "complete",
        account_ids: [],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
    },
    diagnostics: available
      ? []
      : [
          {
            key: "valuation_boundary",
            reason_codes: ["valuation_boundary_unavailable"],
            affected_metrics: ["twrr"],
            category: "limitation",
            refs: { ...EMPTY_REFS },
            action: {
              kind: "review_observations",
              capability: "not_implemented",
              params: { ...EMPTY_REFS },
              verify: "reread_readiness",
            },
          },
          {
            key: "xirr_ambiguous",
            reason_codes: ["not_computable_xirr_root_ambiguity"],
            affected_metrics: ["xirr"],
            category: "limitation",
            refs: { ...EMPTY_REFS },
            action: {
              kind: "inspect_result",
              capability: "unsupported",
              params: { ...EMPTY_REFS },
              verify: "reread_readiness",
            },
          },
        ],
  };
}

function setup(path = "/v2/capital") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    brokerMonths: [] as BrokerMonthReadback[],
    comparison: makeUiV2Comparison(),
    composition: makeUiV2CapitalHistory(),
    risk: makeUiV2RiskAllocation(),
    dashboard: makeUiV2Dashboard(),
    cash: makeUiV2Cash(),
    deposits: makeUiV2Deposits(),
    positions: makeUiV2Positions(),
    debts: makeUiV2Debts(),
    properties: makeUiV2Properties(),
    accounts: uiV2Accounts,
    instruments: uiV2Instruments,
    instrumentsError: false,
    performance: makeUiV2Performance(),
    monthsError: false,
    riskError: false,
    propertiesError: false,
    performanceError: false,
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
      switch (url.pathname) {
        case "/api/months":
          data = state.months;
          failed = state.monthsError;
          break;
        case "/api/broker-months":
          expect(url.searchParams.get("reporting_month_id")).toBe("12");
          data = state.brokerMonths;
          break;
        case "/api/analytics/closed-report-comparison":
          data = state.comparison;
          break;
        case "/api/analytics/capital-composition":
          data = state.composition;
          break;
        case "/api/analytics/risk-allocation":
          expect(url.searchParams.get("month_id")).toBe(String(uiV2CapitalMonthId));
          expect(url.searchParams.get("top_n")).toBe("5");
          data = state.risk;
          failed = state.riskError;
          break;
        case "/api/months/91/dashboard":
          data = state.dashboard;
          break;
        case "/api/cash-balances":
          data = state.cash;
          break;
        case "/api/deposits":
          data = state.deposits;
          break;
        case "/api/positions":
          data = state.positions;
          break;
        case "/api/debts":
          data = state.debts;
          break;
        case "/api/properties":
          data = state.properties;
          failed = state.propertiesError;
          break;
        case "/api/accounts":
          data = state.accounts;
          break;
        case "/api/instruments":
          data = state.instruments;
          failed = state.instrumentsError;
          break;
        case "/api/performance/attribution":
          expect(url.searchParams.get("scope")).toBe("portfolio");
          data = state.performance.attribution;
          failed = state.performanceError;
          break;
        case "/api/performance/readiness":
          expect(url.searchParams.get("scope")).toBe("portfolio");
          data = makeReadiness(state.performance);
          failed = state.performanceError;
          break;
        default:
          throw new Error(`Unexpected API: ${url.pathname}${url.search}`);
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
            <Route path="v2/capital" element={<UiV2CapitalPage />} />
            <Route
              path="v2/capital/performance"
              element={<h1>Диагностика принятого портфеля</h1>}
            />
            <Route path="months/:monthId" element={<h1>Month detail</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { client, mount, reads, state };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows the three capital headlines in the frozen order and reads only GET", async () => {
  const { mount, reads } = setup();
  mount();

  expect(await screen.findByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();
  await screen.findByTestId("capital-net");
  const headlines = screen.getByRole("region", { name: "Главные показатели капитала" });
  const cards = within(headlines).getAllByRole("article");
  expect(cards).toHaveLength(3);
  expect(within(cards[0]).getByText("Ликвидный капитал")).toBeVisible();
  expect(within(cards[1]).getByText("Ликвидные активы")).toBeVisible();
  expect(within(cards[2]).getByText("Включённые обязательства")).toBeVisible();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByTestId("capital-assets")).toHaveTextContent("3 203 900 ₽");
  expect(screen.getByTestId("capital-debts")).toHaveTextContent("− 400 000 ₽");
  expect(
    screen.getByText(/Ликвидные активы минус включённые обязательства = ликвидный капитал/i),
  ).toBeVisible();
  expect(reads.some((read) => read.includes("/api/performance"))).toBe(false);
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
});

it("places existing allocation after the chart, property before holdings and removes duplicate panels and reads", async () => {
  const { mount, reads } = setup();
  mount();
  await screen.findByRole("heading", { name: "Распределение и концентрация" });
  await screen.findByRole("heading", { name: "Недвижимость" });
  const chart = screen.getByTestId("capital-composition").closest("section");
  const allocation = screen
    .getByRole("heading", { name: "Распределение и концентрация" })
    .closest("section");
  const property = screen.getByRole("heading", { name: "Недвижимость" }).closest("section");
  const holdings = screen.getByRole("heading", { name: "Где лежит капитал" }).closest("section");
  if (!chart || !allocation || !property || !holdings) throw new Error("missing Capital sections");
  expect(chart.compareDocumentPosition(allocation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(
    allocation.compareDocumentPosition(property) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    property.compareDocumentPosition(holdings) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(within(allocation).getByRole("table", { name: "По классам активов" })).toBeVisible();
  expect(within(allocation).getByRole("table", { name: "По счетам" })).toBeVisible();
  expect(within(allocation).getByRole("table", { name: "Крупнейшие позиции" })).toBeVisible();
  for (const name of ["Доходность портфеля", "Связанные пары", "Где изменились суммы", "Сейчас"])
    expect(screen.queryByRole("heading", { name })).toBeNull();
  expect(
    reads.some((read) => read.includes("/api/performance") || read.includes("/api/debts")),
  ).toBe(false);
  expect(screen.queryByRole("link", { name: "Доходность инструмента" })).toBeNull();
});

it("keeps the known capital and marks partial source support", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Missing current comparison fixture");
  state.comparison.current.portfolio_source_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  mount();
  expect(await screen.findByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByText("Частично: нет снимка счёта")).toBeVisible();
});

it("keeps the closed snapshot while a newer draft exists and never duplicates the Home CTA", async () => {
  const { mount } = setup();
  mount();

  const note = await screen.findByTestId("capital-draft-note");
  expect(note).toHaveTextContent("Август 2031 ещё не закрыт");
  expect(note.querySelector("a")).toHaveAttribute("href", "/v2");
  await screen.findByTestId("capital-net");
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.queryByTestId("v2-draft-action")).toBeNull();
  expect(screen.queryByText(/Продолжить/)).toBeNull();
});

it("shows no capital numbers when there is no closed report yet", async () => {
  const { mount, reads, state } = setup();
  state.months = [uiV2Months[1]];
  mount();

  expect(await screen.findByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Перейти к закрытию месяца →" })).toHaveAttribute(
    "href",
    "/v2/close",
  );
  expect(screen.queryByTestId("capital-net")).toBeNull();
  expect(screen.queryByTestId("capital-composition")).toBeNull();
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
});

it("shows source DRAFT facts beside unchanged CLOSED capital without writes", async () => {
  const { mount, reads, state } = setup();
  state.brokerMonths = [makeCapitalDraft()];
  mount();
  const preview = await screen.findByRole("region", {
    name: "Черновик / предварительная оценка, не закрытый месяц",
  });
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(within(preview).getByText("1 234,56 ₽")).toBeVisible();
  expect(within(preview).getByText("789,01 ₽")).toBeVisible();
  expect(within(preview).getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
  expect(reads.every((r) => r.startsWith("GET "))).toBe(true);
});

it("keeps canonical capital unavailable in DRAFT-only while exposing source facts", async () => {
  const { mount, reads, state } = setup();
  state.months = [uiV2Months[1]];
  state.brokerMonths = [makeCapitalDraft()];
  mount();
  await screen.findByRole("region", {
    name: "Черновик / предварительная оценка, не закрытый месяц",
  });
  expect(screen.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
  expect(screen.queryByTestId("capital-net")).toBeNull();
  expect(reads.some((r) => r.includes("/api/analytics/"))).toBe(false);
});

it("does not read or show DRAFT sources in CLOSED-only", async () => {
  const { mount, reads, state } = setup();
  state.months = uiV2Months.filter((m) => m.status === "closed");
  mount();
  await screen.findByTestId("capital-net");
  expect(
    screen.queryByRole("region", { name: "Черновик / предварительная оценка, не закрытый месяц" }),
  ).toBeNull();
  expect(reads.some((r) => r.includes("/api/broker-months"))).toBe(false);
});

it("retains current facts without a previous comparison and does not recreate removed comparison UI", async () => {
  const { mount, state } = setup();
  state.months = [uiV2Months[0], uiV2Months[1]];
  state.comparison = makeUiV2Comparison({ firstClosed: true });
  state.composition = makeUiV2CapitalHistory({ firstClosed: true });
  mount();

  expect(await screen.findByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.queryByTestId("capital-change-list")).toBeNull();
  expect(screen.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "1");
  expect(screen.queryByText("Доходность портфеля")).toBeNull();
});

it("shows a genuine zero as zero and not as an unavailable share", async () => {
  const { mount, state } = setup();
  state.comparison = makeUiV2Comparison({ zero: true });
  state.composition = makeUiV2CapitalHistory({ zero: true });
  for (const item of state.risk.allocation_by_asset_class.items) {
    item.amount.amount = "0.00";
    item.share_pct = null;
  }
  state.risk.allocation_by_asset_class.denominator.amount = "0.00";
  state.risk.allocation_by_asset_class.covered_amount.amount = "0.00";
  state.risk.allocation_by_asset_class.coverage_pct = null;
  mount();

  expect(await screen.findByTestId("capital-net")).toHaveTextContent("0 ₽");
  const cashRow = screen.getByTestId("capital-class-cash");
  expect(cashRow).toHaveTextContent("0 ₽");
  expect(cashRow).toHaveTextContent("—");
});

it("switches the composition window and mode over closed reports with visible gaps", async () => {
  const { mount } = setup();
  mount();

  expect(await screen.findByTestId("capital-composition")).toHaveAttribute("data-point-count", "4");
  expect(screen.getByText(/Пропуски означают неизвестную историю/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "3 месяца" }));
  expect(screen.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "3");
  fireEvent.click(screen.getByRole("button", { name: "Доли" }));
  expect(screen.getByRole("button", { name: "Доли" })).toHaveAttribute("aria-pressed", "true");
});

it("presents account buckets, rows and exclusion labels without summing rows", async () => {
  const { mount } = setup();
  mount();

  expect(await screen.findByTestId("capital-bucket-unassigned_cash")).toHaveTextContent(
    "Наличные без привязки к счёту",
  );
  expect(await screen.findByTestId("capital-holding-cash-701")).toHaveTextContent(
    "Синтетический кошелёк",
  );
  const excluded = screen.getByTestId("capital-holding-cash-702");
  expect(excluded).toHaveAttribute("data-included", "false");
  expect(within(excluded).getByText("не входит в ликвидный капитал")).toBeVisible();
  expect(screen.getByTestId("capital-holding-position-503")).toHaveTextContent(
    "Синтетический фонд",
  );
  expect(
    screen.getByText(/Итоги берутся из подтверждённой сводки, а не из суммы строк/i),
  ).toBeVisible();
});

it("filters the holdings by a class row and an account bucket as presentation only", async () => {
  const { mount } = setup();
  mount();

  await screen.findByTestId("capital-holding-position-501");
  fireEvent.click(within(screen.getByTestId("capital-class-stock")).getByRole("button"));
  expect(screen.getByText("Фильтр: Акции")).toBeVisible();
  expect(screen.getByTestId("capital-holding-position-501")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");

  fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
  expect(screen.queryByText("Фильтр: Акции")).toBeNull();

  fireEvent.click(await screen.findByTestId("capital-bucket-account:3"));
  expect(screen.getByText("Фильтр: Синтетический брокерский счёт")).toBeVisible();
  expect(screen.getByTestId("capital-holding-position-502")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-cash-701")).toBeNull();
  expect(screen.queryByTestId("capital-holding-deposit-601")).toBeNull();

  fireEvent.click(screen.getByTestId("capital-bucket-account:1"));
  expect(screen.getByTestId("capital-holding-deposit-601")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  expect(screen.queryByTestId("capital-holding-cash-701")).toBeNull();
});

it("does not blank unrelated widgets when a single widget fails", async () => {
  const { mount, state } = setup();
  state.riskError = true;
  mount();

  const nowPanel = (
    await screen.findByRole("heading", { name: "Распределение и концентрация" })
  ).closest("section");
  if (!nowPanel) throw new Error("Capital «Сейчас» panel is missing");
  await waitFor(() =>
    expect(within(nowPanel).getByText("Данные временно недоступны")).toBeVisible(),
  );
  await waitFor(() => expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽"));
  expect(screen.getByTestId("capital-composition")).toBeVisible();
  expect(screen.queryByTestId("capital-change-list")).toBeNull();
});

it("fails the concentration closed when the risk read model is unsupported", async () => {
  const { mount, state } = setup();
  state.risk = makeUiV2RiskAllocation({ unsupportedPositions: true });
  mount();

  expect(await screen.findByText(/оценка позиции непригодна для расчёта/i)).toBeVisible();
  const nowPanel = screen
    .getByRole("heading", { name: "Распределение и концентрация" })
    .closest("section");
  if (!nowPanel) throw new Error("Capital «Сейчас» panel is missing");
  expect(within(nowPanel).queryByTestId("capital-top-positions")).toBeNull();
});

it("fails the row lists closed when a requested month no longer matches the closed snapshot", async () => {
  const { mount, state } = setup();
  for (const row of state.cash) row.reporting_month_id = 999;
  mount();

  expect(await screen.findByTestId("capital-holding-deposit-601")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-cash-701")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
});

it("shows real estate separately and hides the block when there are no property rows", async () => {
  const { mount } = setup();
  mount();

  expect(await screen.findByRole("heading", { name: "Недвижимость" })).toBeVisible();
  expect(screen.getByText("Синтетическая квартира")).toBeVisible();
  expect(screen.getByText("164,9%", { exact: false })).toBeVisible();
  expect(
    screen.getByText(/не входят в ликвидный капитал и не смешиваются с составом/i),
  ).toBeVisible();

  cleanup();
  const second = setup();
  second.state.properties = [];
  second.mount();
  await screen.findByTestId("capital-net");
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Недвижимость" })).toBeNull());
});

it("shows a closed mortgage without dividing by zero", async () => {
  const { mount, state } = setup();
  state.dashboard = makeUiV2Dashboard({ mortgageClosed: true });
  mount();

  expect(await screen.findByText("ипотека закрыта")).toBeVisible();
  expect(screen.queryByText("NaN")).toBeNull();
});

it("fails the property block closed on a properties read error", async () => {
  const { mount, state } = setup();
  state.propertiesError = true;
  mount();

  const panel = (await screen.findByRole("heading", { name: "Недвижимость" })).closest("section");
  if (!panel) throw new Error("Property panel is missing");
  expect(within(panel).getByText("Данные временно недоступны")).toBeVisible();
});

it("keeps current capital facts without a legacy escape for month and step context", async () => {
  const { mount } = setup(`/v2/capital?month=${uiV2CapitalPreviousMonthId}&step=actual_payouts`);
  mount();

  expect(await screen.findByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(
    screen.queryByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /← Мои финансы/ })).toHaveAttribute("href", "/v2");
  expect(screen.getByRole("link", { name: "Капитал" })).toHaveAttribute("aria-current", "page");
});

it("recovers the report list without querying a guessed snapshot", async () => {
  const { mount, reads, state } = setup();
  state.monthsError = true;
  mount();

  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить отчёты");
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  state.monthsError = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByTestId("capital-net")).toBeVisible();
});

it("labels the mortgage difference with a truthful sign instead of a shortfall", async () => {
  const { mount } = setup();
  mount();
  await screen.findByTestId("capital-net");

  const surplus = screen.getByText("Разница: капитал − ипотека").parentElement;
  if (!surplus) throw new Error("Mortgage difference row is missing");
  expect(surplus).toHaveTextContent("+1 103 900 ₽");
  expect(surplus).not.toHaveTextContent(/Не хватает/);
  expect(screen.queryByText(/Не хватает до полного покрытия/)).toBeNull();
  expect(screen.getByText(/положительная — капитала больше остатка ипотеки/)).toBeVisible();

  cleanup();
  const under = setup();
  under.state.dashboard = makeUiV2Dashboard({ coveragePct: "60.0", gapAmount: "-680000.00" });
  under.mount();
  await screen.findByTestId("capital-net");

  const shortfall = screen.getByText("Разница: капитал − ипотека").parentElement;
  if (!shortfall) throw new Error("Mortgage difference row is missing");
  expect(shortfall).toHaveTextContent("680 000 ₽");
  expect(shortfall).toHaveTextContent(/[−-]/);
  expect(shortfall).not.toHaveTextContent(/\+/);

  cleanup();
  const closed = setup();
  closed.state.dashboard = makeUiV2Dashboard({ mortgageClosed: true });
  closed.mount();
  expect(await screen.findByText("ипотека закрыта")).toBeVisible();
  expect(screen.queryByText("Разница: капитал − ипотека")).toBeNull();
});

it("keeps cash, deposits and property when only the instrument catalog fails", async () => {
  const { mount, state } = setup();
  state.instrumentsError = true;
  mount();

  await screen.findByTestId("capital-net");
  expect(await screen.findByTestId("capital-holding-cash-701")).toBeVisible();
  expect(screen.getByTestId("capital-holding-deposit-601")).toBeVisible();
  expect(screen.queryByTestId("capital-pair-21")).toBeNull();
  expect(screen.queryByTestId("capital-holding-position-501")).toBeNull();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();

  const positions = screen.getByRole("heading", { name: "Позиции" }).closest("div");
  if (!positions) throw new Error("Positions sub-block is missing");
  expect(within(positions).getByText("Данные временно недоступны")).toBeVisible();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
});

it("fails the account slice closed when its support status is not supported", async () => {
  const { mount, state } = setup();
  state.risk = makeUiV2RiskAllocation({ accountSupport: "unknown" });
  mount();

  await screen.findByTestId("capital-net");
  expect(
    await screen.findByText("Этот срез нельзя построить: банк не указан для этих данных."),
  ).toBeVisible();
  expect(screen.queryByTestId("capital-bucket-account:1")).toBeNull();
  expect(screen.queryByTestId("capital-bucket-unassigned_cash")).toBeNull();
  expect(screen.getByTestId("capital-holding-cash-701")).toBeVisible();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");

  cleanup();
  const supported = setup();
  supported.mount();
  expect(await screen.findByTestId("capital-bucket-account:1")).toHaveTextContent(
    "Синтетический депозитный счёт",
  );
});

it("links current capital to its native month data and archive", async () => {
  const { mount } = setup();
  mount();

  await screen.findByTestId("capital-net");
  expect(screen.getByRole("link", { name: "Все отчёты →" })).toHaveAttribute("href", "/v2/reports");
  expect(
    within(screen.getByTestId("v2-report-context")).queryByRole("link", {
      name: "Данные отчётного месяца →",
    }),
  ).toBeNull();
  expect(screen.queryByRole("link", { name: "Распределение и концентрация →" })).toBeNull();
});

describe("UI v2 Capital isolation", () => {
  it("offers a reload when the lazy page crashes", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { UiV2ErrorBoundary } = await import("../ui-v2/UiV2Entry");
    function Broken(): never {
      throw new Error("synthetic capital failure");
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

it("links exact catalogue instruments from Capital and gives unsupported rows an explicit reason", async () => {
  const { mount, state } = setup();
  state.instruments = state.instruments.map((instrument) => ({
    ...instrument,
    isin: instrument.id === 10 ? "RU000A000010" : null,
  }));
  mount();
  const position = await screen.findByTestId("capital-holding-position-501");
  expect(within(position).getByRole("link", { name: "Синтетическая акция" })).toHaveAttribute(
    "href",
    "/v2/returns/instrument/RU000A000010?capital_account=3&back=%2Fv2%2Fcapital",
  );
  const noIsin = screen.getByTestId("capital-holding-position-502");
  expect(within(noIsin).queryByRole("link")).toBeNull();
  expect(noIsin).toHaveTextContent("Точный ISIN не подтверждён");
});

it("restores the Capital holding filter from a safe card Back target without changing totals", async () => {
  const { mount, state } = setup(
    "/v2/capital?holding_kind=class&holding_value=stocks&holding_label=Акции",
  );
  state.instruments = state.instruments.map((instrument) => ({
    ...instrument,
    isin: instrument.id === 10 ? "RU000A000010" : null,
  }));
  mount();
  await screen.findByTestId("capital-holding-position-501");
  expect(screen.getByText("Фильтр: Акции")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  const href =
    within(screen.getByTestId("capital-holding-position-501"))
      .getByRole("link", { name: "Синтетическая акция" })
      .getAttribute("href") ?? "";
  const back = new URL(href, "http://localhost").searchParams.get("back") ?? "";
  expect(back).toContain("holding_kind=class");
  expect(back).toContain("holding_value=stocks");
});

it("restores exact raw risk-class Back context and clears it after reset", async () => {
  const { mount, state } = setup(
    "/v2/capital?holding_kind=risk_class&holding_value=stock&holding_label=MisleadingGold",
  );
  state.instruments = state.instruments.map((instrument) => ({
    ...instrument,
    isin: instrument.id === 10 ? "RU000A000010" : null,
  }));
  mount();
  const stock = await screen.findByTestId("capital-holding-position-501");
  expect(screen.getByText("Фильтр: Акции")).toBeVisible();
  expect(screen.queryByText("Фильтр: MisleadingGold")).toBeNull();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  const href =
    within(stock).getByRole("link", { name: "Синтетическая акция" }).getAttribute("href") ?? "";
  const back = new URL(href, "http://localhost").searchParams.get("back") ?? "";
  expect(back).toContain("holding_kind=risk_class");
  expect(back).toContain("holding_value=stock");
  fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
  const top = screen.getByRole("table", { name: "Крупнейшие позиции" });
  const topHref =
    within(top).getByRole("link", { name: "Синтетическая акция" }).getAttribute("href") ?? "";
  expect(new URL(topHref, "http://localhost").searchParams.get("back")).toBe("/v2/capital");
});

it.each(["position", "account", "instrument"])(
  "does not link a top position by its name when exact %s identity mismatches",
  async (mismatch) => {
    const { mount, state } = setup();
    state.instruments = state.instruments.map((instrument) => ({
      ...instrument,
      isin: instrument.id === 10 ? "RU000A000010" : null,
    }));
    const top = state.risk.top_positions.items.find((item) => item.instrument_id === 10);
    if (!top) throw new Error("missing synthetic top position");
    if (mismatch === "position") top.position_id = 9999;
    else if (mismatch === "account") top.account_id = 9999;
    else top.instrument_id = 9999;
    mount();
    const table = await screen.findByRole("table", { name: "Крупнейшие позиции" });
    expect(within(table).getByText("Синтетическая акция")).toBeVisible();
    expect(within(table).queryByRole("link", { name: "Синтетическая акция" })).toBeNull();
    expect(
      within(await screen.findByTestId("capital-holding-position-501")).getByRole("link", {
        name: "Синтетическая акция",
      }),
    ).toBeVisible();
  },
);
