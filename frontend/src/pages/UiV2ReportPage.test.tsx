import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import {
  makeUiV2CapitalHistory,
  makeUiV2Cash,
  makeUiV2Deposits,
  makeUiV2Positions,
  makeUiV2RiskAllocation,
  uiV2Accounts,
  uiV2CapitalMonthId,
  uiV2CapitalPreviousMonthId,
  uiV2Instruments,
  uiV2Months,
} from "../test/uiV2Fixtures";
import UiV2ReportPage from "../ui-v2/UiV2ReportPage";

const historicalId = uiV2CapitalPreviousMonthId;

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function setup(path = `/v2/reports/${historicalId}`) {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    composition: makeUiV2CapitalHistory(),
    risk: makeUiV2RiskAllocation({ monthId: historicalId }),
    cash: makeUiV2Cash({ monthId: historicalId }),
    deposits: makeUiV2Deposits({ monthId: historicalId }),
    positions: makeUiV2Positions({ monthId: historicalId }),
    accounts: uiV2Accounts,
    instruments: uiV2Instruments,
    monthsError: false,
    compositionError: false,
    riskError: false,
    cashError: false,
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
        case "/api/analytics/capital-composition":
          data = state.composition;
          failed = state.compositionError;
          break;
        case "/api/analytics/risk-allocation":
          expect(url.searchParams.get("month_id")).toBe(String(historicalId));
          expect(url.searchParams.get("top_n")).toBe("5");
          data = state.risk;
          failed = state.riskError;
          break;
        case "/api/cash-balances":
          expect(url.searchParams.get("month_id")).toBe(String(historicalId));
          data = state.cash;
          failed = state.cashError;
          break;
        case "/api/deposits":
          expect(url.searchParams.get("month_id")).toBe(String(historicalId));
          data = state.deposits;
          break;
        case "/api/positions":
          expect(url.searchParams.get("month_id")).toBe(String(historicalId));
          data = state.positions;
          break;
        case "/api/accounts":
          data = state.accounts;
          break;
        case "/api/instruments":
          data = state.instruments;
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
            <Route path="v2/reports/:monthId" element={<UiV2ReportPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { client, mount, reads, state };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("UI v2 historical report", () => {
  it("shows the historical context, canonical values, composition and neighbours", async () => {
    const { mount, reads } = setup();
    const view = mount();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Исторический отчёт" }),
    ).toBeVisible();
    await screen.findByTestId("report-net");
    const context = screen.getByTestId("v2-report-context");
    expect(context).toHaveAttribute("data-context", "historical");
    expect(context).toHaveTextContent("Исторический отчёт");
    expect(context).toHaveTextContent("Закрыт · Утверждён");
    expect(context).toHaveTextContent("Май 2031");
    expect(context).toHaveTextContent("Снимок 31.05.2031");
    expect(context).toHaveTextContent("Источник: Вручную");
    expect(within(context).getByRole("link", { name: /^Текущий отчёт: Июль/ })).toHaveAttribute(
      "href",
      "/v2",
    );
    expect(within(context).getByRole("link", { name: "Капитал" })).toHaveAttribute(
      "href",
      "/v2/capital",
    );

    expect(screen.getByTestId("report-net")).toHaveTextContent("2 761 300 ₽");
    expect(screen.getByTestId("report-assets")).toHaveTextContent("3 151 300 ₽");
    expect(screen.getByTestId("report-debts")).toHaveTextContent("− 390 000 ₽");

    const composition = screen.getByTestId("report-composition");
    expect(within(composition).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByTestId("report-class-cash")).toHaveTextContent("751 300 ₽");
    expect(screen.getByTestId("report-class-gold_other")).toHaveTextContent("Золото и прочее");
    const compositionPanel = screen.getByTestId("report-panel-report-composition-title");
    fireEvent.click(within(compositionPanel).getByRole("button", { name: "Доли" }));
    expect(screen.getByTestId("report-class-cash")).toHaveTextContent("%");
    expect(screen.queryByTestId("report-composition-empty")).toBeNull();

    expect(screen.getByTestId("report-history")).toHaveAttribute("data-point-count", "4");
    expect(view.container.querySelector('[data-highlight-key="2031-05"]')).not.toBeNull();
    expect(screen.getByText(/Пропуски остаются пропусками/)).toBeVisible();
    expect(screen.getByTestId("report-neighbour-previous")).toHaveAttribute(
      "href",
      "/v2/reports/89",
    );
    expect(screen.getByTestId("report-neighbour-next")).toHaveAttribute("href", "/v2/reports/91");

    expect(
      screen.getByText(/Поздние цены, остатки и позиции никогда не подставляются/),
    ).toBeVisible();

    expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
    expect(reads.map((read) => read.split(" ")[1]).sort()).toEqual([
      "/api/accounts",
      "/api/analytics/capital-composition",
      "/api/analytics/risk-allocation?month_id=90&top_n=5&forecast_version=v1",
      "/api/cash-balances?month_id=90",
      "/api/deposits?month_id=90",
      "/api/instruments",
      "/api/months",
      "/api/positions?month_id=90",
    ]);
  });

  it("never shows a historical delta or historical performance", async () => {
    const { mount, reads } = setup();
    mount();

    expect(await screen.findByTestId("report-change-unavailable")).toHaveTextContent(
      "Изменение между отчётами показывается только для двух последних закрытых отчётов.",
    );
    expect(screen.queryByText(/XIRR/)).toBeNull();
    expect(screen.queryByText(/TWRR/)).toBeNull();
    expect(reads.some((read) => read.includes("/api/performance/"))).toBe(false);
    expect(screen.getByRole("link", { name: "Мои финансы →" })).toHaveAttribute("href", "/v2");
    expect(screen.getByRole("link", { name: "Капитал →" })).toHaveAttribute("href", "/v2/capital");
  });

  it("shows the report rows of that month with the excluded-row label", async () => {
    const { mount } = setup();
    mount();

    expect(await screen.findByTestId("report-holding-deposit-601")).toHaveTextContent(
      "Синтетический вклад",
    );
    expect(screen.getByTestId("report-holding-deposit-601")).toHaveAttribute(
      "data-included",
      "true",
    );
    const excluded = screen.getByTestId("report-holding-cash-702");
    expect(excluded).toHaveAttribute("data-included", "false");
    expect(within(excluded).getByText("не входит в ликвидный капитал")).toBeVisible();
    expect(screen.getByTestId("report-holding-position-501")).toHaveTextContent(
      "Синтетическая акция",
    );
    expect(
      screen.getByText(/Итоги берутся из подтверждённой сводки, а не из суммы строк/),
    ).toBeVisible();
    expect(screen.getByTestId("report-top-positions")).toBeVisible();
    expect(screen.getByTestId("report-top-positions")).toHaveTextContent("Синтетическая облигация");
  });

  it("hides the linked-pair block when there are no pairs and shows only the aggregate otherwise", async () => {
    const { mount } = setup();
    mount();

    await screen.findByTestId("report-net");
    expect(screen.queryByTestId("report-linked-pairs")).toBeNull();

    cleanup();
    const second = setup();
    const may = second.state.composition.points.find(
      (point) => point.reporting_month_id === historicalId,
    );
    if (!may) throw new Error("Synthetic May point is missing");
    may.linked_pair_assets.amount = "1400000.00";
    may.linked_pair_debts.amount = "400000.00";
    may.linked_pair_net_contribution.amount = "1000000.00";
    second.mount();

    const pairs = await screen.findByTestId("report-linked-pairs");
    expect(pairs).toHaveTextContent("1 400 000 ₽");
    expect(pairs).toHaveTextContent("400 000 ₽");
    expect(pairs).toHaveTextContent("1 000 000 ₽");
    // Aggregate context only: no per-pair detail and no second subtraction.
    expect(pairs.querySelectorAll("li")).toHaveLength(3);
    expect(
      screen.getByText(/уже входят в ликвидные активы и включённые обязательства/),
    ).toBeVisible();
  });

  it("labels the v1 handoff explicitly", async () => {
    const { mount } = setup();
    mount();

    const handoff = await screen.findByTestId("report-v1-handoff");
    expect(
      within(handoff).getByRole("link", { name: "Отчёт месяца в текущем интерфейсе →" }),
    ).toHaveAttribute("href", `/months/${historicalId}`);
    expect(
      within(handoff).getByRole("link", { name: "Все расчёты в текущем интерфейсе →" }),
    ).toHaveAttribute("href", "/analytics");
    expect(
      within(handoff).getByRole("link", { name: "Месяцы в текущем интерфейсе →" }),
    ).toHaveAttribute("href", "/months");
    expect(screen.getByRole("link", { name: "Вернуться к текущему интерфейсу →" })).toHaveAttribute(
      "href",
      `/months/${historicalId}`,
    );
    expect(
      within(screen.getByTestId("v2-report-context")).getByRole("link", { name: "Капитал" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("moves focus to the report heading and stays reachable from the archive", async () => {
    const { mount } = setup();
    mount();

    const heading = await screen.findByRole("heading", { level: 1, name: "Исторический отчёт" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.getByRole("link", { name: "← Все отчёты" })).toHaveAttribute(
      "href",
      "/v2/reports",
    );
  });

  it("treats the draft deep link as a draft, not as history", async () => {
    const { mount, reads } = setup("/v2/reports/12");
    mount();

    expect(await screen.findByRole("heading", { name: "Этот месяц ещё не закрыт" })).toBeVisible();
    expect(screen.getByText(/черновик, не исторический отчёт/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Закрытие месяца →" })).toHaveAttribute(
      "href",
      "/months/12/close",
    );
    expect(screen.queryByTestId("report-net")).toBeNull();
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  });

  it("treats the latest closed deep link as the current report, not as history", async () => {
    const { mount, reads } = setup(`/v2/reports/${uiV2CapitalMonthId}`);
    mount();

    expect(await screen.findByRole("heading", { name: "Это текущий отчёт" })).toBeVisible();
    expect(screen.getByText(/не показывается как история/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Все отчёты →" })).toHaveAttribute(
      "href",
      "/v2/reports",
    );
    expect(screen.queryByTestId("report-net")).toBeNull();
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  });

  it("answers an unknown and a malformed id without inventing a report", async () => {
    const { mount, reads } = setup("/v2/reports/999");
    mount();
    expect(await screen.findByRole("heading", { name: "Отчёт не найден" })).toBeVisible();

    cleanup();
    const malformed = setup("/v2/reports/012");
    malformed.mount();
    expect(await screen.findByRole("heading", { name: "Отчёт не найден" })).toBeVisible();
    expect(malformed.reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  });

  it("fails the report closed when its own snapshot is not confirmed", async () => {
    const { mount, state } = setup();
    state.composition = {
      asset_classes: state.composition.asset_classes,
      points: state.composition.points.filter((point) => point.reporting_month_id !== historicalId),
    };
    mount();

    expect(
      await screen.findByRole("heading", { name: "Отчёт не подтверждён в истории" }),
    ).toBeVisible();
    expect(screen.queryByTestId("report-net")).toBeNull();
  });

  it("hides money and offers a retry when the composition series fails", async () => {
    const { mount, state } = setup();
    state.compositionError = true;
    mount();

    expect(
      await screen.findByRole("heading", { name: "Данные отчёта не подтверждены" }),
    ).toBeVisible();
    expect(screen.queryByTestId("report-net")).toBeNull();
    state.compositionError = false;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByTestId("report-net")).toHaveTextContent("2 761 300 ₽");
  });

  it("keeps unrelated blocks alive when one widget fails", async () => {
    const { mount, state } = setup();
    state.riskError = true;
    mount();

    expect(await screen.findByTestId("report-net")).toHaveTextContent("2 761 300 ₽");
    expect(screen.getByTestId("report-composition")).toBeVisible();
    expect(screen.getByTestId("report-holding-deposit-601")).toBeVisible();
    const positionsPanel = screen.getByRole("heading", { name: "Топ позиций" }).closest("section");
    if (!positionsPanel) throw new Error("Top-positions panel is missing");
    await waitFor(() =>
      expect(within(positionsPanel).getByText("Данные временно недоступны")).toBeVisible(),
    );
    expect(screen.queryByTestId("report-top-positions")).toBeNull();
  });

  it("fails the concentration closed when the risk read model is unsupported", async () => {
    const { mount, state } = setup();
    state.risk = makeUiV2RiskAllocation({ monthId: historicalId, unsupportedPositions: true });
    mount();

    expect(await screen.findByText(/оценка позиции непригодна для расчёта/i)).toBeVisible();
    expect(screen.queryByTestId("report-top-positions")).toBeNull();
    expect(screen.getByTestId("report-net")).toHaveTextContent("2 761 300 ₽");
  });

  it("fails only the failed row list closed and never re-sums rows into the totals", async () => {
    const { mount, state } = setup();
    state.cashError = true;
    mount();

    expect(await screen.findByTestId("report-net")).toHaveTextContent("2 761 300 ₽");
    expect(screen.queryByTestId("report-holding-cash-701")).toBeNull();
    expect(screen.getByTestId("report-holding-deposit-601")).toBeVisible();
    const cashSection = screen.getByRole("heading", { name: "Денежные строки" }).closest("div");
    if (!cashSection) throw new Error("Cash sub-block is missing");
    expect(within(cashSection).getByText("Данные временно недоступны")).toBeVisible();
  });

  it("shows a genuine zero report as zero without inventing shares", async () => {
    const { mount, state } = setup();
    const may = state.composition.points.find((point) => point.reporting_month_id === historicalId);
    if (!may) throw new Error("Synthetic May point is missing");
    may.liquid_assets_total.amount = "0.00";
    may.included_debts.amount = "0.00";
    may.liquid_capital_net.amount = "0.00";
    may.allocation = may.allocation.map((item) => ({
      ...item,
      amount: { ...item.amount, amount: "0.00" },
    }));
    mount();

    expect(await screen.findByTestId("report-net")).toHaveTextContent("0 ₽");
    expect(screen.getByTestId("report-class-cash")).toHaveTextContent("0 ₽");
    expect(screen.getByTestId("report-composition-empty")).toBeVisible();
    fireEvent.click(
      within(screen.getByTestId("report-panel-report-composition-title")).getByRole("button", {
        name: "Доли",
      }),
    );
    expect(screen.getByTestId("report-class-cash")).toHaveTextContent("—");
  });

  it("switches the history window over closed reports only", async () => {
    const { mount } = setup();
    mount();

    expect(await screen.findByTestId("report-history")).toHaveAttribute("data-point-count", "4");
    fireEvent.click(
      within(screen.getByTestId("report-panel-report-history-title")).getByRole("button", {
        name: "3 месяца",
      }),
    );
    expect(screen.getByTestId("report-history")).toHaveAttribute("data-point-count", "3");
    expect(screen.getByText(/Показаны последние 3 закрытых отчёта/)).toBeVisible();
  });
});
