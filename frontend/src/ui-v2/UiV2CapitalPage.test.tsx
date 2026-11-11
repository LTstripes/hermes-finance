import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BrokerMonthReadback } from "../api/brokerMonths";
import { createQueryClient } from "../queryClient";
import { makeCapitalDraft } from "../test/capitalDraftFixtures";
import {
  makeUiV2CapitalHistory,
  makeUiV2Cash,
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

async function showHolding(testId: string) {
  const row = await screen.findByTestId(testId);
  const group = row.closest("details");
  if (group && !group.open) {
    const summary = group.querySelector("summary");
    if (!summary) throw new Error("Missing account disclosure");
    fireEvent.click(summary);
  }
  return row;
}

function setup(path = "/v2/capital") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    brokerMonths: [] as BrokerMonthReadback[],
    comparison: makeUiV2Comparison(),
    fullComparison: null as ReturnType<typeof makeUiV2Comparison> | null,
    comparisonGate: null as Promise<void> | null,
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
          if (state.comparisonGate) await state.comparisonGate;
          data = !url.search && state.fullComparison ? state.fullComparison : state.comparison;
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
            <Route path="v2/returns" element={<h1>Диагностика принятого портфеля</h1>} />
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

it("shows the capital hero and its two subtotals in the frozen order and reads only GET", async () => {
  const { mount, reads } = setup();
  mount();

  expect(await screen.findByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();
  await screen.findByTestId("capital-net");
  const headlines = screen.getByRole("region", { name: "Главные показатели капитала" });
  expect(within(headlines).getByText("Ликвидный капитал")).toBeVisible();
  expect(within(headlines).getByText("Ликвидные активы")).toBeVisible();
  expect(within(headlines).getByText("Включённые обязательства")).toBeVisible();
  const [net, assets, debts] = ["capital-net", "capital-assets", "capital-debts"].map((id) =>
    within(headlines).getByTestId(id),
  );
  expect(net.compareDocumentPosition(assets) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(assets.compareDocumentPosition(debts) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // The change against the previous closed report comes from the backend delta.
  expect(within(headlines).getByText("+42 600 ₽", { exact: false })).toBeVisible();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByTestId("capital-assets")).toHaveTextContent("3 203 900 ₽");
  expect(screen.getByTestId("capital-debts")).toHaveTextContent("−400 000 ₽");
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(within(headlines).getByRole("button", { name: "Как считается капитал" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "Ликвидные активы минус включённые обязательства = ликвидный капитал",
  );
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "Жильё и ипотека в ликвидный капитал не входят",
  );
  expect(reads.some((read) => read.includes("/api/performance"))).toBe(false);
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
});

it("places the structure after the chart, property before holdings and removes duplicate panels and reads", async () => {
  const { mount, reads } = setup();
  mount();
  await screen.findByTestId("capital-class-cash");
  await screen.findByRole("heading", { name: "Недвижимость" });
  const section = (name: string) => {
    const found = screen.getByRole("heading", { name }).closest("section");
    if (!found) throw new Error(`missing Capital section ${name}`);
    return found;
  };
  const chart = screen.getByTestId("capital-composition").closest("section");
  if (!chart) throw new Error("missing Capital chart");
  const order = [
    chart,
    section("По классам активов"),
    section("Счета и позиции"),
    section("Недвижимость"),
  ];
  for (const [index, current] of order.slice(1).entries())
    expect(
      order[index].compareDocumentPosition(current) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  expect(within(section("По классам активов")).getByTestId("capital-class-cash")).toBeVisible();
  expect(within(section("Счета и позиции")).getByTestId("capital-bucket-account:1")).toBeVisible();
  expect(within(section("Счета и позиции")).getByTestId("capital-top-summary")).toBeVisible();
  // Accounts are listed once, not again above the holdings.
  expect(screen.getAllByTestId("capital-bucket-account:1")).toHaveLength(1);
  expect(
    screen.getAllByTestId("capital-holding-group").filter((group) => group.hasAttribute("open")),
  ).toHaveLength(1);
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
  await waitFor(() =>
    expect(screen.getByTestId("portfolio-coverage-note")).toHaveTextContent(
      "Частично: нет снимка счёта: Синтетический старый вклад",
    ),
  );
});

it("marks a change against an incomplete previous report once, in plain words", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current || !state.comparison.previous)
    throw new Error("Missing comparison fixtures");
  state.comparison.current.portfolio_source_coverage = {
    status: "complete",
    reason_codes: [],
    missing_account_ids: [],
  };
  // The backend combines both reports: the previous one is missing an account snapshot.
  state.comparison.liquid_capital_net_delta_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  state.comparison.previous.portfolio_source_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  mount();
  const note = await screen.findByTestId("capital-delta-partial");
  await waitFor(() =>
    expect(note.textContent?.replaceAll(" ", " ")).toBe(
      "Изменение посчитано по известным записям: в отчёте за Май 2031 не хватает данных; нет снимка счёта: Синтетический старый вклад.",
    ),
  );
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByText("+42 600 ₽", { exact: false })).toBeVisible();
  expect(screen.queryByTestId("portfolio-coverage-note")).toBeNull();
});

it("names both reports once when the current and the previous are incomplete", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current || !state.comparison.previous)
    throw new Error("Missing comparison fixture");
  // Different accounts lack snapshots in the two months.
  state.comparison.current.portfolio_source_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  state.comparison.previous.portfolio_source_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [1],
  };
  state.comparison.liquid_capital_net_delta_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [1, 2],
  };
  mount();
  const note = await screen.findByTestId("capital-delta-partial");
  await waitFor(() =>
    expect(note.textContent?.replaceAll(" ", " ")).toBe(
      "Изменение посчитано по известным записям: не хватает данных в отчётах за Июль 2031 и Май 2031; нет снимка счёта: Синтетический депозитный счёт.",
    ),
  );
  expect(screen.getAllByTestId("capital-delta-partial")).toHaveLength(1);
  await waitFor(() =>
    expect(screen.getByTestId("portfolio-coverage-note")).toHaveTextContent(
      "Частично: нет снимка счёта: Синтетический старый вклад",
    ),
  );
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
});

it("explains a partial current report once when the previous report is complete", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Missing current comparison fixture");
  const partial = {
    status: "partial" as const,
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  state.comparison.current.portfolio_source_coverage = partial;
  if (state.comparison.previous)
    state.comparison.previous.portfolio_source_coverage = {
      status: "complete",
      reason_codes: [],
      missing_account_ids: [],
    };
  state.comparison.liquid_capital_net_delta_coverage = partial;
  mount();
  await waitFor(() =>
    expect(screen.getByTestId("portfolio-coverage-note")).toHaveTextContent(
      "Частично: нет снимка счёта: Синтетический старый вклад",
    ),
  );
  expect(screen.queryByTestId("capital-delta-partial")).toBeNull();
});

it("shows overview sums in whole rubles and keeps kopecks in holdings and on hover", async () => {
  const { mount, state } = setup();
  if (!state.comparison.current) throw new Error("Missing current comparison fixture");
  state.comparison.current.liquid_capital_net.amount = "2803900.45";
  state.comparison.current.liquid_assets_total.amount = "3203900.50";
  state.risk.allocation_by_asset_class.items[0].amount.amount = "803900.60";
  state.cash[0].amount.amount = "803900.60";
  mount();
  const net = await screen.findByTestId("capital-net");
  expect(net).toHaveTextContent("2 803 900 ₽");
  expect(net.getAttribute("title")?.replaceAll(" ", " ")).toBe("2 803 900,45 ₽");
  expect(screen.getByTestId("capital-assets")).toHaveTextContent("3 203 901 ₽");
  expect(await screen.findByTestId("capital-class-cash")).toHaveTextContent("803 901 ₽");
  expect(await showHolding("capital-holding-cash-701")).toHaveTextContent("803 901 ₽");
  expect(
    within(screen.getByTestId("capital-holding-cash-701")).getByTitle("803 900,60 ₽"),
  ).toBeVisible();
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
  expect(screen.getByRole("link", { name: "Закрой первый месяц →" })).toHaveAttribute(
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

it("keeps a genuine zero capital and omits zero allocation rows without inventing shares", async () => {
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
  expect(screen.queryByTestId("capital-class-cash")).toBeNull();
  expect(screen.getByTestId("capital-assets")).toHaveTextContent("0 ₽");
  const classes = screen.getByRole("heading", { name: "По классам активов" }).closest("section");
  if (!classes) throw new Error("Missing class section");
  expect(classes).toHaveTextContent("Ненулевых строк нет.");
  expect(classes).not.toHaveTextContent("0,0%");
});

it("switches the composition window and mode over closed reports with visible gaps", async () => {
  const { mount } = setup();
  mount();

  expect(await screen.findByTestId("capital-composition")).toHaveAttribute("data-point-count", "4");
  expect(screen.getByText(/Пропуски означают неизвестную историю/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "3 мес" }));
  expect(screen.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "3");
  fireEvent.click(screen.getByRole("button", { name: "Доли" }));
  expect(screen.getByRole("button", { name: "Доли" })).toHaveAttribute("aria-pressed", "true");
});

it("presents account buckets, rows and exclusion labels without summing rows", async () => {
  const { mount, state } = setup();
  state.cash[0].amount.amount = "123.00";
  mount();

  expect(await screen.findByTestId("capital-bucket-unassigned_cash")).toHaveTextContent(
    "Деньги без привязки к счёту",
  );
  expect(await showHolding("capital-holding-cash-701")).toHaveTextContent("Синтетический кошелёк");
  const excluded = await showHolding("capital-holding-cash-702");
  expect(excluded).toHaveAttribute("data-included", "false");
  expect(within(excluded).getByText("не входит в ликвидный капитал")).toBeVisible();
  expect(screen.getByTestId("capital-holding-position-503")).toHaveTextContent(
    "Синтетический фонд",
  );
  expect(screen.getByTestId("capital-holding-cash-701")).toHaveTextContent("123 ₽");
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByTestId("capital-assets")).toHaveTextContent("3 203 900 ₽");
  expect(screen.getByRole("link", { name: "Данные отчётного месяца →" })).toHaveAttribute(
    "href",
    `/v2/data/months/${uiV2CapitalMonthId}`,
  );
});

it("filters the holdings by a class row and an account bucket as presentation only", async () => {
  const { mount } = setup();
  mount();

  await showHolding("capital-holding-position-501");
  fireEvent.click(within(screen.getByTestId("capital-class-stock")).getByRole("button"));
  expect(screen.getByText("Фильтр: Акции")).toBeVisible();
  expect(screen.getByTestId("capital-holding-position-501")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");

  fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
  expect(screen.queryByText("Фильтр: Акции")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "По классам" }));
  expect(await showHolding("capital-holding-position-502")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "По счетам" }));
  expect(screen.getByTestId("capital-bucket-account:3").closest("details")).not.toHaveAttribute(
    "open",
  );
  fireEvent.click(screen.getByTestId("capital-bucket-account:3"));
  expect(await showHolding("capital-holding-position-502")).toBeVisible();
  expect(await showHolding("capital-holding-deposit-601")).toBeVisible();
});

it("does not blank unrelated widgets when a single widget fails", async () => {
  const { mount, state } = setup();
  state.riskError = true;
  mount();

  const nowPanel = (await screen.findByRole("heading", { name: "По классам активов" })).closest(
    "section",
  );
  if (!nowPanel) throw new Error("Capital class panel is missing");
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
  const nowPanel = screen.getByTestId("capital-top-summary").closest("section");
  if (!nowPanel) throw new Error("Capital top positions panel is missing");
  expect(within(nowPanel).queryByTestId("capital-top-positions")).toBeNull();
});

it("fails the row lists closed when a requested month no longer matches the closed snapshot", async () => {
  const { mount, state } = setup();
  for (const row of state.cash) row.reporting_month_id = 999;
  mount();

  expect(await showHolding("capital-holding-deposit-601")).toBeVisible();
  expect(screen.queryByTestId("capital-holding-cash-701")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
});

it("shows real estate separately and hides the block when there are no property rows", async () => {
  const { mount } = setup();
  mount();

  expect(await screen.findByRole("heading", { name: "Недвижимость" })).toBeVisible();
  expect(screen.getByText("Синтетическая квартира")).toBeVisible();
  expect(screen.getByText("164,9%", { exact: false })).toBeVisible();
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Сравнение капитала и ипотеки" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "Недвижимость и ипотека не входят в ликвидный капитал",
  );

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
  expect(screen.getByRole("link", { name: "Мои финансы" })).toHaveAttribute("href", "/v2");
  expect(screen.getByRole("link", { name: "Капитал" })).toHaveAttribute("aria-current", "page");
});

it("recovers the report list without querying a guessed snapshot", async () => {
  const { mount, reads, state } = setup();
  state.monthsError = true;
  mount();

  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить");
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
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Сравнение капитала и ипотеки" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "Положительная разница — капитала больше остатка ипотеки, отрицательная — меньше",
  );

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
  expect(await showHolding("capital-holding-cash-701")).toBeVisible();
  expect(await showHolding("capital-holding-deposit-601")).toBeVisible();
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
  expect(await showHolding("capital-holding-cash-701")).toBeVisible();
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
  expect(screen.getByRole("link", { name: /^Распределение$/ })).toHaveAttribute(
    "href",
    "/v2/capital/allocation",
  );
  expect(
    within(screen.getByTestId("v2-report-context")).queryByRole("link", {
      name: "Данные отчётного месяца →",
    }),
  ).toBeNull();
  expect(screen.queryByRole("link", { name: "Распределение и концентрация →" })).toBeNull();
});

it("ranks three nonzero positions once per group and expands the remaining rows without deriving totals", async () => {
  const { mount, state } = setup();
  const original = state.positions[0];
  state.positions = ["0.00", "10.50", "9999999999999.99", "30.00", "20.00"].map(
    (amount, index) => ({
      ...original,
      id: 850 + index,
      market_value: { ...original.market_value, amount },
    }),
  );
  mount();
  await showHolding("capital-holding-position-852");
  const group = screen.getByTestId("capital-bucket-account:3").closest("details");
  if (!group) throw new Error("missing account group");
  expect(within(group).getAllByRole("listitem")).toHaveLength(3);
  expect(within(group).getAllByRole("listitem")[0]).toHaveAttribute(
    "data-testid",
    "capital-holding-position-852",
  );
  expect(screen.queryByTestId("capital-holding-position-850")).toBeNull();
  expect(screen.queryByTestId("capital-holding-position-851")).toBeNull();
  fireEvent.click(within(group).getByRole("button", { name: "ещё 1 позиция" }));
  expect(screen.getAllByTestId("capital-holding-position-851")).toHaveLength(1);
  expect(within(group).getAllByRole("listitem")).toHaveLength(4);
  expect(screen.getByTestId("capital-top-summary")).toHaveTextContent("топ-5");
  expect(screen.getByTestId("capital-bucket-account:3")).not.toHaveTextContent("9 999 999 999 999");
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
  const position = await showHolding("capital-holding-position-501");
  expect(within(position).getByRole("link", { name: "Синтетическая акция" })).toHaveAttribute(
    "href",
    expect.stringContaining("/v2/returns/instrument/RU000A000010?capital_account=3&back="),
  );
  const noIsin = screen.getByTestId("capital-holding-position-502");
  expect(within(noIsin).queryByRole("link")).toBeNull();
  expect(screen.queryByText(/Без ссылки на разбор:/)).toBeNull();
  expect(within(noIsin).getByText("Синтетическая облигация")).toHaveAttribute(
    "title",
    "Точный ISIN не подтверждён; переход к разбору недоступен.",
  );
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
  expect(stock.closest("details")).toHaveAttribute("open");
  expect(stock).toBeVisible();
  expect(screen.getByText("Фильтр: Акции")).toBeVisible();
  expect(screen.queryByText("Фильтр: MisleadingGold")).toBeNull();
  expect(screen.queryByTestId("capital-holding-position-502")).toBeNull();
  const href =
    within(stock).getByRole("link", { name: "Синтетическая акция" }).getAttribute("href") ?? "";
  const back = new URL(href, "http://localhost").searchParams.get("back") ?? "";
  expect(back).toContain("holding_kind=risk_class");
  expect(back).toContain("holding_value=stock");
  fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
  const holding = screen.getByTestId("capital-holding-position-501");
  const nextHref = within(holding).getByRole("link").getAttribute("href") ?? "";
  const restored = new URL(
    new URL(nextHref, "http://localhost").searchParams.get("back") ?? "",
    "http://localhost",
  );
  expect(restored.searchParams.get("holding_kind")).toBe("risk_class");
  expect(restored.searchParams.get("holding_value")).toBe("stock");
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
    const table = await screen.findByTestId("capital-top-summary");
    await waitFor(() => expect(table).toHaveTextContent("топ-5"));
    expect(within(table).queryByRole("link", { name: "Синтетическая акция" })).toBeNull();
    expect(
      within(await showHolding("capital-holding-position-501")).getByRole("link", {
        name: "Синтетическая акция",
      }),
    ).toBeVisible();
  },
);

it("shows the unexplained residual separately from other capital changes", async () => {
  const { state, mount } = setup();
  state.comparison.capital_change = {
    reporting_month_id: uiV2CapitalMonthId,
    previous_reporting_month_id: uiV2CapitalPreviousMonthId,
    period_start: "2026-04-01",
    period_end: "2026-04-30",
    component_basis: "known_subtotals",
    breakdown: {
      start: { amount: "1000.00", currency: "RUB" },
      external_net: { amount: "-100.00", currency: "RUB" },
      investment_result: { amount: "10.00", currency: "RUB" },
      other_changes: { amount: "5.00", currency: "RUB" },
      unexplained: { amount: "7.01", currency: "RUB" },
      end: { amount: "922.01", currency: "RUB" },
    },
    reason_codes: [],
  };
  mount();
  const residual = await screen.findByTestId("capital-unexplained");
  expect(residual).toHaveTextContent("Необъяснённый остаток");
  // The waterfall reads in whole rubles; the exact residual stays on hover.
  expect(residual).toHaveTextContent("+7 ₽");
  expect(residual.getAttribute("title")?.replaceAll(" ", " ")).toBe("+7,01 ₽");
  expect(residual).not.toHaveTextContent("Прочие изменения");
  expect(screen.getByText("Внешние внесения и изъятия")).toBeVisible();
});

it("explains the month through income minus expenses and flags unrecorded card spending", async () => {
  const { state, mount } = setup();
  const rub = (amount: string) => ({ amount, currency: "RUB" });
  state.comparison.capital_change = {
    reporting_month_id: uiV2CapitalMonthId,
    previous_reporting_month_id: uiV2CapitalPreviousMonthId,
    period_start: "2026-04-01",
    period_end: "2026-04-30",
    component_basis: "known_subtotals",
    breakdown: {
      start: rub("1000.00"),
      external_net: rub("0.00"),
      investment_result: rub("0.00"),
      other_changes: rub("-300.00"),
      unexplained: rub("222.00"),
      end: rub("922.00"),
    },
    reason_codes: [],
    flow_breakdown: {
      basis: "monthly_flow_v1",
      start: rub("1000.00"),
      monthly_flow: rub("200.00"),
      investment_market_change: {
        amount: null,
        known_subtotal: rub("0.00"),
        items: [
          {
            account_id: 1,
            instrument_id: null,
            amount: null,
            reason_codes: ["x"],
            unavailable_hint: "Сверьте позиции и деньги в капитале с выписками на 30.09.2026.",
          },
          {
            account_id: 4,
            instrument_id: null,
            amount: null,
            reason_codes: ["x"],
            unavailable_hint: "Сверьте позиции и деньги в капитале с выписками на 30.09.2026.",
          },
        ],
        reason_codes: ["x"],
      },
      physical_gold_revaluation: {
        amount: rub("-30.00"),
        known_subtotal: rub("-30.00"),
        items: [{ account_id: 2, instrument_id: 3, amount: rub("-30.00"), reason_codes: [] }],
        reason_codes: [],
      },
      unexplained: rub("-248.00"),
      end: rub("922.00"),
    },
    context_hints: [
      {
        reason_code: "card_debt_growth_exceeds_recorded_expenses",
        card_debt_growth: rub("300.00"),
        recorded_expenses: rub("50.00"),
      },
    ],
  };
  mount();
  const residual = await screen.findByTestId("capital-unexplained");
  expect(residual).toHaveTextContent("−248 ₽");
  expect(screen.getByText("Доходы минус расходы")).toBeVisible();
  expect(screen.getByText("Переоценка золота")).toBeVisible();
  expect(screen.queryByText("Прочие изменения")).toBeNull();
  expect(screen.queryByText("Рынок: брокерский и ИИС")).toBeNull();
  expect(
    screen.getByText(/не подтверждено и входит в необъяснённый остаток: изменение стоимости/),
  ).toBeVisible();
  const hints = screen.getByTestId("capital-market-hints");
  expect(within(hints).getAllByRole("listitem")).toHaveLength(1);
  expect(hints).toHaveTextContent("Сверьте позиции и деньги в капитале с выписками на 30.09.2026.");
  expect(screen.getByTestId("capital-card-hint")).toHaveTextContent(
    /Долг по кредитке вырос на 300 ₽, а расходов за месяц внесено 50 ₽/,
  );
});

it("does not render a capital explanation for another month", async () => {
  const { state, mount } = setup();
  state.comparison.capital_change = {
    reporting_month_id: 999,
    previous_reporting_month_id: uiV2CapitalPreviousMonthId,
    period_start: "2026-04-01",
    period_end: "2026-04-30",
    component_basis: "known_subtotals",
    breakdown: null,
    reason_codes: [],
  };
  mount();
  await screen.findByTestId("capital-net");
  expect(screen.queryByText("Как изменился капитал за месяц")).not.toBeInTheDocument();
});

it.each([
  ["-11.11", false],
  ["0.00", false],
  [null, false],
  ["-11.11", true],
] as const)(
  "renders the backend valuation difference %s (partial=%s) and residual context",
  async (difference, partial) => {
    const { state, mount } = setup();
    const rub = (amount: string) => ({ amount, currency: "RUB" });
    const component = (amount: string | null) => ({
      amount: amount === null || partial ? null : rub(amount),
      known_subtotal: rub(amount ?? "0.00"),
      items: [
        {
          account_id: 1,
          instrument_id: null,
          amount: amount === null ? null : rub(amount),
          reason_codes: amount === null ? ["capital_investment_flows_unproven"] : [],
        },
        ...(partial
          ? [{ account_id: 2, instrument_id: null, amount: null, reason_codes: ["unknown"] }]
          : []),
      ],
      reason_codes: amount === null ? ["capital_investment_flows_unproven"] : [],
    });
    const hint =
      "Сюда попадают мелкие расходы, которые не вносятся отдельно, и всё неподтверждённое";
    state.comparison.capital_change = {
      reporting_month_id: uiV2CapitalMonthId,
      previous_reporting_month_id: uiV2CapitalPreviousMonthId,
      period_start: "2026-04-01",
      period_end: "2026-04-30",
      component_basis: "known_subtotals",
      breakdown: null,
      reason_codes: [],
      flow_breakdown: {
        basis: "monthly_flow_v1",
        start: rub("1000.00"),
        monthly_flow: rub("0.00"),
        investment_market_change: component(
          difference === null ? null : difference === "0.00" ? "20.00" : "31.11",
        ),
        investment_valuation_difference: component(difference),
        physical_gold_revaluation: component("0.00"),
        unexplained: rub("-30.00"),
        unexplained_hint: hint,
        end: rub(difference === null ? "970.00" : "990.00"),
      },
    };
    mount();
    expect(await screen.findByTestId("capital-unexplained")).toHaveTextContent("−30 ₽");
    expect(screen.getAllByText(hint)).toHaveLength(1);
    if (difference === null) {
      expect(screen.queryByText("Разница оценки капитала и выписок")).toBeNull();
      expect(screen.queryByText("Рынок: брокерский и ИИС")).toBeNull();
      expect(screen.getByText(/Пока не подтверждено/)).toHaveTextContent(
        "разница оценки капитала и выписок",
      );
    } else {
      const label = screen.getByText(
        `Разница оценки капитала и выписок${partial ? " (известная часть)" : ""}`,
      );
      expect(label.parentElement?.getAttribute("title")?.replaceAll(" ", " ")).toBe(
        difference === "0.00" ? "0 ₽" : "−11,11 ₽",
      );
      expect(
        screen.getByText(`Рынок: брокерский и ИИС${partial ? " (известная часть)" : ""}`),
      ).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Как читать изменение капитала" }));
      expect(screen.getByRole("tooltip")).toHaveTextContent(
        "это разница основы оценки, а не прибыль или убыток",
      );
    }
  },
);

it("shows loading rather than a false error while the capital comparison is pending", async () => {
  const { mount, state } = setup();
  let release!: () => void;
  state.comparisonGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  mount();
  expect(await screen.findAllByText("Загружаем показатели…")).toHaveLength(1);
  const headline = screen.getByRole("region", { name: "Главные показатели капитала" });
  expect(within(headline).queryByText("Данные временно недоступны")).toBeNull();
  release();
  expect(await screen.findByTestId("capital-net")).toBeVisible();
});

it.each(["current", "previous"] as const)(
  "does not mix a settled old %s month with current capital cards",
  async (oldPart) => {
    const { state, mount, reads, client } = setup();
    const stale = makeUiV2Comparison();
    if (!stale.current) throw new Error("synthetic current missing");
    if (!stale.previous) throw new Error("synthetic previous missing");
    if (oldPart === "current") stale.current.reporting_month_id = 999;
    else stale.previous.reporting_month_id = 999;
    stale.capital_change = {
      reporting_month_id: oldPart === "current" ? 999 : uiV2CapitalMonthId,
      previous_reporting_month_id: oldPart === "previous" ? 999 : uiV2CapitalPreviousMonthId,
      period_start: "2026-04-01",
      period_end: "2026-04-30",
      component_basis: "known_subtotals",
      breakdown: null,
      reason_codes: [],
    };
    state.fullComparison = stale;
    mount();
    await screen.findByTestId("capital-net");
    await waitFor(() => expect(reads).toContain("GET /api/analytics/closed-report-comparison"));
    await waitFor(() =>
      expect(client.getQueryState(["closed-report-comparison"])?.status).toBe("success"),
    );
    expect(screen.queryByText("Как изменился капитал за месяц")).toBeNull();
  },
);
