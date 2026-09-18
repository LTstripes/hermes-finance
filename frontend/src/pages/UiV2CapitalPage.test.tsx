import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
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
import UiV2CapitalPage from "../ui-v2/UiV2CapitalPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function setup(path = "/v2/capital") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
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
          break;
        case "/api/performance/attribution":
          expect(url.searchParams.get("scope")).toBe("portfolio");
          data = state.performance.attribution;
          failed = state.performanceError;
          break;
        case "/api/performance/xirr":
          data = state.performance.xirr;
          failed = state.performanceError;
          break;
        case "/api/performance/twrr":
          data = state.performance.twrr;
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
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(reads.some((read) => read.includes("scope=portfolio"))).toBe(true);
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
  expect(screen.queryByTestId("capital-net")).toBeNull();
  expect(screen.queryByTestId("capital-composition")).toBeNull();
  expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
});

it("distinguishes a missing comparison base from a genuine zero", async () => {
  const { mount, state } = setup();
  state.months = [uiV2Months[0], uiV2Months[1]];
  state.comparison = makeUiV2Comparison({ firstClosed: true });
  state.composition = makeUiV2CapitalHistory({ firstClosed: true });
  mount();

  expect(await screen.findByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getAllByText("Нужны два закрытых отчёта для сравнения").length).toBeGreaterThan(0);
  expect(screen.getByText(/Нужны два закрытых отчёта для расчёта за период/)).toBeVisible();
});

it("shows a genuine zero as zero and not as an unavailable share", async () => {
  const { mount, state } = setup();
  state.comparison = makeUiV2Comparison({ zero: true });
  state.composition = makeUiV2CapitalHistory({ zero: true });
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
  fireEvent.click(screen.getByTestId("capital-class-stocks"));
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

it("keeps a missing linked-pair fact as a dash instead of zero", async () => {
  const { mount } = setup();
  mount();

  const fact = await screen.findByTestId("capital-pair-21");
  expect(fact).toHaveTextContent("1 400 000 ₽");
  expect(fact).toHaveTextContent("400 000 ₽");
  expect(fact).toHaveTextContent("1 000 000 ₽");
  const fallback = await screen.findByTestId("capital-pair-22");
  expect(fallback).toHaveTextContent("120 000 ₽");
  expect(fallback).toHaveTextContent("—");
  expect(
    within(fallback).getByText(/Связь сохранена, но факт актива за выбранный месяц недоступен/i),
  ).toBeVisible();
  expect(screen.getByTestId("capital-pair-aggregate")).toHaveTextContent(
    /уже входят в ликвидные активы и включённые обязательства/i,
  );
});

it("shows supported performance for the same closed pair and hides raw reason codes", async () => {
  const { mount } = setup();
  mount();

  const pair = await waitFor(() => {
    const element = document.querySelector("details[open]");
    if (!element) throw new Error("performance disclosure is not open");
    return element as HTMLElement;
  });
  await waitFor(() =>
    expect(within(pair).getByTestId("capital-performance-bridge")).toHaveTextContent("+42 600 ₽"),
  );
  expect(within(pair).getByTestId("capital-performance-xirr")).toHaveTextContent("+7,42%");
  expect(within(pair).getByTestId("capital-performance-twrr")).toHaveTextContent("+6,10%");
  expect(screen.getByText(/Это изменение стоимости, а не доходность/i)).toBeVisible();
});

it("starts the performance disclosure collapsed on the narrow layout", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      addEventListener: vi.fn(),
      matches: query === "(max-width: 800px)",
      media: query,
      onchange: null,
      removeEventListener: vi.fn(),
    })),
  );
  const { mount } = setup();
  mount();

  await screen.findByTestId("capital-net");
  const details = document.querySelector("details");
  if (!details) throw new Error("performance disclosure is missing");
  expect(details).not.toHaveAttribute("open");
});

it("reports an unavailable performance metric with an owner-facing reason", async () => {
  const { mount, state } = setup();
  state.performance = makeUiV2Performance({ notComputable: true });
  mount();

  expect(
    await screen.findByText(
      /Расчёт недоступен: однозначность корня для этой истории не подтверждена/i,
    ),
  ).toBeVisible();
  expect(
    screen.getByText(/Не подтверждены оценки стоимости на границах выбранного периода/i),
  ).toBeVisible();
  expect(screen.queryByText(/not_computable_xirr_root_ambiguity/)).toBeNull();
  expect(screen.queryByText(/valuation_boundary_unavailable/)).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
});

it("does not blank unrelated widgets when a single widget fails", async () => {
  const { mount, state } = setup();
  state.riskError = true;
  mount();

  const nowPanel = (await screen.findByRole("heading", { name: "Сейчас" })).closest("section");
  if (!nowPanel) throw new Error("Capital «Сейчас» panel is missing");
  await waitFor(() =>
    expect(within(nowPanel).getByText("Данные временно недоступны")).toBeVisible(),
  );
  await waitFor(() => expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽"));
  expect(screen.getByTestId("capital-composition")).toBeVisible();
  expect(screen.getByTestId("capital-change-list")).toBeVisible();
});

it("fails the concentration closed when the risk read model is unsupported", async () => {
  const { mount, state } = setup();
  state.risk = makeUiV2RiskAllocation({ unsupportedPositions: true });
  mount();

  expect(await screen.findByText(/оценка позиции непригодна для расчёта/i)).toBeVisible();
  const nowPanel = screen.getByRole("heading", { name: "Сейчас" }).closest("section");
  if (!nowPanel) throw new Error("Capital «Сейчас» panel is missing");
  expect(within(nowPanel).queryByTestId("capital-top-positions")).toBeNull();
});

it("fails the whole change list closed when the comparison does not reconcile", async () => {
  const { mount, state } = setup();
  state.comparison.net_liquid_capital_reconciles = false;
  mount();

  expect(
    await screen.findByText("Изменение не подтверждено: строки не сходятся с итогом"),
  ).toBeVisible();
  expect(screen.queryByTestId("capital-change-list")).toBeNull();
  expect(screen.getByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
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

it("preserves a valid legacy month and step only in the labelled v1 escape", async () => {
  const { mount } = setup(`/v2/capital?month=${uiV2CapitalPreviousMonthId}&step=actual_payouts`);
  mount();

  expect(await screen.findByTestId("capital-net")).toHaveTextContent("2 803 900 ₽");
  expect(screen.getByRole("link", { name: "Вернуться к текущему интерфейсу →" })).toHaveAttribute(
    "href",
    `/months/${uiV2CapitalPreviousMonthId}/close#actual_payouts`,
  );
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

describe("UI v2 Capital isolation", () => {
  it("keeps the v1 rollback path when the lazy page crashes", async () => {
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
    expect(screen.getByRole("alert")).toHaveTextContent("Новый интерфейс не загрузился");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/");
  });
});
