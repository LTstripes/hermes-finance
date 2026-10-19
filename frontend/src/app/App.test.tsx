import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

vi.mock("../ui-v2/UiV2ScenarioLabPage", () => ({
  default: function BrokenScenarioLabPage() {
    throw new Error("synthetic Scenario Lab chunk failure");
  },
}));

const sampleMonths = [
  {
    id: 2,
    year: 2026,
    month: 7,
    status: "draft",
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  {
    id: 1,
    year: 2026,
    month: 6,
    status: "closed",
    snapshot_date: "2026-06-30",
    source: "manual",
  },
];

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return new Response(
        JSON.stringify({
          error: { code: "not_found", message: `no mock for ${key}`, details: [] },
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
    return handler(init);
  });
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("uses the UI v2 entry at / and a native home link while loading", () => {
    window.history.pushState({}, "", "/");

    render(<App />);

    expect(screen.getByText("Загружаем основной интерфейс…")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Мои финансы" })).toHaveAttribute("href", "/v2");
  });

  it("registers the native Capital allocation deep-link route with its selected report month", async () => {
    window.history.pushState({}, "", "/v2/capital/allocation?month=1");
    const zero = { amount: "0.00", currency: "RUB" };
    const supported = { status: "supported", reason_codes: [] };
    const allocation = {
      support: supported,
      denominator: zero,
      covered_amount: zero,
      unallocated_amount: zero,
      coverage_pct: null,
      items: [],
      excluded: [],
    };
    const concentration = {
      support: supported,
      denominator: zero,
      top_n: 5,
      top_amount: zero,
      top_share_pct: null,
      items: [],
      excluded: [],
      is_approximate: false,
    };
    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/months": () => jsonResponse(sampleMonths),
        "GET /api/analytics/risk-allocation?month_id=1&top_n=5&forecast_version=v1": () =>
          jsonResponse({
            reporting_month_id: 1,
            as_of_date: "2026-06-30",
            base_currency: "RUB",
            liquid_assets_total: zero,
            allocation_by_asset_class: allocation,
            allocation_by_account: allocation,
            top_positions: concentration,
            payout_concentration: concentration,
            redemption_concentration: concentration,
            support: {},
          }),
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Распределение и концентрация" }),
    ).toBeVisible();
    expect(await screen.findByLabelText("Отчётный месяц")).toHaveValue("1");
    expect(screen.getByRole("link", { name: "← Капитал" })).toHaveAttribute("href", "/v2/capital");
  });

  it.each([
    ["/v2/capital/monthly-result?month=1&view=classes", "Денежный результат"],
    ["/v2/capital/performance?start=invalid&scope=account", "Доходность"],
  ])("keeps the aggregate Capital detail route %s registered", async (path, heading) => {
    window.history.pushState({}, "", path);
    vi.stubGlobal(
      "fetch",
      mockFetchRouter({ "GET /api/months": () => jsonResponse(sampleMonths) }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeVisible();
    expect(window.location.pathname + window.location.search).toBe(path);
    expect(screen.getByRole("link", { name: "← Капитал" })).toHaveAttribute("href", "/v2/capital");
  });

  it("registers the native goals deep-link route with its selected report month", async () => {
    window.history.pushState({}, "", "/v2/income/goals?month=1");
    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/goals?include_inactive=true": () => jsonResponse([]),
        "GET /api/goals/summary?reporting_month_id=1&include_inactive=true": () => jsonResponse([]),
        "GET /api/months": () => jsonResponse(sampleMonths),
      }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "Цели" })).toBeVisible();
    expect(screen.getByRole("link", { name: "← Доход и планы" })).toHaveAttribute(
      "href",
      "/v2/income?month=1",
    );
  });

  it("registers the native Tax/IIS deep-link route with its selected report month", async () => {
    window.history.pushState({}, "", "/v2/income/tax-iis?month=1");
    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/months": () => jsonResponse(sampleMonths),
        "GET /api/tax-iis-planner?reporting_month_id=1": () =>
          jsonResponse({
            contract_version: "tax_iis_planner_v1",
            tax_year: 2026,
            as_of: {
              reporting_month: sampleMonths[1],
              selection_reason: "requested",
            },
            salary_tax: {
              tax_year: 2026,
              history_complete: true,
              history_coverage: "complete",
              available: true,
              opening_context_available: false,
              taxable_gross_ytd: { amount: "100000.00", currency: "RUB" },
              current_marginal_bracket: {
                threshold_from: { amount: "0.00", currency: "RUB" },
                threshold_to: { amount: "2400000.00", currency: "RUB" },
                rate_bps: 1300,
              },
              current_marginal_rate_bps: 1300,
              next_threshold: { amount: "2400000.00", currency: "RUB" },
              distance_to_next_threshold: { amount: "2300000.00", currency: "RUB" },
              tax_bracket_source: "official_default",
              warning_codes: [],
            },
            iis_accounts: [],
            warnings: [],
          }),
      }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "Налоги и ИИС" })).toBeVisible();
    expect(screen.getByRole("link", { name: "← Доход и планы" })).toHaveAttribute(
      "href",
      "/v2/income?month=1",
    );
  });

  it("loads Scenario Lab through the shared lazy fallback and error boundary", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    window.history.pushState({}, "", "/v2/income/scenario-lab");

    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Загружаем основной интерфейс");
    expect(screen.getByRole("link", { name: "Мои финансы" })).toHaveAttribute("href", "/v2");

    expect(await screen.findByRole("alert")).toHaveTextContent("Основной интерфейс не загрузился");
    expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /UI v1/ })).not.toBeInTheDocument();
  });
});
