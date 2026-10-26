import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it.each([
    ["/v1", "/v2"],
    ["/analytics", "/v2/capital/performance"],
    ["/analytics/risk-allocation", "/v2/capital/allocation"],
    ["/freshness", "/v2/data"],
    ["/reconciliation", "/v2/data/reconciliation"],
    ["/months", "/v2/data/months"],
    ["/months/7", "/v2/data/months/7"],
    ["/monthly-close", "/v2/close"],
    ["/months/7/close", "/v2/close?month=7"],
    ["/payouts", "/v2/data/payouts"],
    ["/accounts", "/v2/data/catalogs"],
    ["/goals", "/v2/income/goals"],
    ["/tax-iis-planner", "/v2/income/tax-iis"],
    ["/scenario-lab", "/v2/income/scenario-lab"],
    ["/export", "/v2/data/files"],
    ["/settings", "/v2/data/app"],
  ])("redirects retired legacy route %s to %s", async (from, to) => {
    window.history.pushState({}, "", from);
    vi.stubGlobal("fetch", mockFetchRouter({}));

    render(<App />);

    await waitFor(() =>
      expect(window.location.pathname + window.location.search + window.location.hash).toBe(to),
    );
  });

  describe("legacy month editor compatibility", () => {
    const month = { ...sampleMonths[0], id: 7 };

    function openLegacyMonth(query = "", status = "draft", id = "7") {
      const fetch = mockFetchRouter({
        "GET /api/months/7": () => jsonResponse({ ...month, status }),
        "GET /api/accounts": () => jsonResponse([]),
        "GET /api/instruments?active=true": () => jsonResponse([]),
        "GET /api/positions?month_id=7": () => jsonResponse([]),
      });
      vi.stubGlobal("fetch", fetch);
      window.history.pushState({}, "", `/months/${id}${query}`);
      return { ...render(<App />), fetch };
    }

    function expectOnlyReads(fetch: ReturnType<typeof mockFetchRouter>) {
      expect(fetch).toHaveBeenCalled();
      expect(fetch.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);
    }

    it("keeps positions, return context, raw query and quotes hash across redirect and reload", async () => {
      const query =
        "?section=positions&from=monthly-close-v2&monthId=7&step=market_quotes&extra=keep&extra=a%20b+%2B&month=2#month-quotes";
      const target = `/v2/data/months/7${query}`;
      const view = openLegacyMonth(query);
      const assertEditor = async () => {
        await waitFor(() =>
          expect(window.location.pathname + window.location.search + window.location.hash).toBe(
            target,
          ),
        );
        expect(
          await screen.findByRole("link", { name: "Позиции", current: "page" }, { timeout: 5_000 }),
        ).toBeVisible();
        expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
          "href",
          "/v2/close?month=7&step=market_quotes",
        );
        await waitFor(() => expect(document.getElementById("month-quotes")).toBeInTheDocument());
        expect(window.location.pathname + window.location.search + window.location.hash).toBe(
          target,
        );
        expect(view.fetch).toHaveBeenCalledWith("/api/months/7", expect.anything());
        expect(view.fetch.mock.calls.some(([url]) => String(url) === "/api/months/2")).toBe(false);
        expectOnlyReads(view.fetch);
      };
      await assertEditor();
      view.unmount();
      // A fresh App/client at the redirected URL models restoring saved state on reload.
      const reloaded = render(<App />);
      await assertEditor();
      reloaded.unmount();
    });

    it("opens the bare legacy URL at General without a write", async () => {
      const { fetch } = openLegacyMonth();
      expect(await screen.findByRole("region", { name: "Общие данные месяца" })).toBeVisible();
      expect(window.location.pathname + window.location.search + window.location.hash).toBe(
        "/v2/data/months/7",
      );
      expectOnlyReads(fetch);
    });

    it("preserves action=reopen as CLOSED confirmation only, including cancellation", async () => {
      const { fetch } = openLegacyMonth("?action=reopen", "closed");
      const dialog = await screen.findByRole("alertdialog", {
        name: "Открыть месяц для редактирования?",
      });
      expectOnlyReads(fetch);
      fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Дата снимка")).toBeDisabled();
      expect(window.location.search).toBe("?action=reopen");
      expectOnlyReads(fetch);
    });

    it.each([
      ["?section=unknown", true],
      ["?section=general&section=general", true],
      ["?action=reopen&action=reopen", false],
      ["?action=unknown", false],
      ["?from=monthly-close-v2&monthId=7&monthId=7&step=month_setup", false],
      ["?from=monthly-close-v2&from=monthly-close-v2&monthId=7&step=month_setup", false],
      ["?from=monthly-close-v2&monthId=7&step=month_setup&step=month_setup", false],
      ["?from=monthly-close-v2&monthId=2&step=month_setup", false],
      ["?from=unknown&monthId=7&step=unknown", false],
    ])(
      "leaves invalid or repeated fields untouched for editor validators: %s",
      async (query, invalidSection) => {
        const { fetch } = openLegacyMonth(`${query}#month-quotes`, "closed");
        await screen.findByRole("heading", { level: 1, name: "Редактор месяца" });
        if (invalidSection) {
          expect(
            await screen.findByText("Неизвестный раздел. Выбери раздел редактора."),
          ).toBeVisible();
          expect(
            screen.queryByRole("region", { name: "Общие данные месяца" }),
          ).not.toBeInTheDocument();
        } else {
          expect(await screen.findByLabelText("Дата снимка")).toBeDisabled();
        }
        expect(
          screen.queryByRole("link", { name: "Вернуться к закрытию" }),
        ).not.toBeInTheDocument();
        expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
        expect(window.location.pathname + window.location.search + window.location.hash).toBe(
          `/v2/data/months/7${query}#month-quotes`,
        );
        expectOnlyReads(fetch);
      },
    );

    it.each([
      ["0", "Некорректный идентификатор месяца."],
      ["8", "Запрошенный месяц не найден. Выбери месяц из списка явно."],
    ])(
      "keeps invalid or missing path ID %s instead of selecting query month",
      async (id, message) => {
        const { fetch } = openLegacyMonth("?month=7", "draft", id);
        expect(await screen.findByText(message)).toBeVisible();
        expect(window.location.pathname + window.location.search).toBe(
          `/v2/data/months/${id}?month=7`,
        );
        expect(fetch.mock.calls.some(([url]) => String(url) === "/api/months/7")).toBe(false);
      },
    );

    it("replaces the legacy entry so Back returns directly to the preceding page", async () => {
      window.history.pushState({}, "", "/v2/income/scenario-lab?before=legacy");
      const { fetch } = openLegacyMonth("?section=general#month-quotes");
      await screen.findByRole("region", { name: "Общие данные месяца" });
      const historyLength = window.history.length;
      await act(async () => window.history.back());
      await waitFor(() =>
        expect(window.location.pathname + window.location.search).toBe(
          "/v2/income/scenario-lab?before=legacy",
        ),
      );
      await act(async () => window.history.forward());
      await screen.findByRole("region", { name: "Общие данные месяца" });
      expect(window.location.pathname + window.location.search + window.location.hash).toBe(
        "/v2/data/months/7?section=general#month-quotes",
      );
      expect(window.history.length).toBe(historyLength);
      expectOnlyReads(fetch);
    });
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
      await screen.findByRole(
        "heading",
        { level: 1, name: "Распределение и концентрация" },
        { timeout: 5_000 },
      ),
    ).toBeVisible();
    expect(await screen.findByLabelText("Отчётный месяц", {}, { timeout: 5_000 })).toHaveValue("1");
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

    const alert = await screen.findByRole("alert", {}, { timeout: 5_000 });
    expect(alert).toHaveTextContent("Основной интерфейс не загрузился");
    expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /UI v1/ })).not.toBeInTheDocument();
  });
});
