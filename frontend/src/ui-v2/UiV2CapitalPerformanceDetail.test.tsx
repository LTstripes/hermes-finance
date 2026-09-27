import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import UiV2CapitalPerformanceDetail from "./UiV2CapitalPerformanceDetail";

const START = "2031-05-31";
const END = "2031-07-31";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function readinessFixture(options: {
  scope?: "portfolio" | "account";
  accountId?: number | null;
  xirr?: string | null;
  twrr?: string | null;
}) {
  const scope = options.scope ?? "portfolio";
  const accountId = options.accountId ?? null;
  const xirr = options.xirr ?? "7.42";
  const twrr = options.twrr ?? "6.10";
  const forMetric = (kind: "xirr" | "twrr", value: string | null) => ({
    metric: kind,
    scope,
    account_id: accountId,
    performance_currency: "RUB",
    value,
    value_unit: "percentage_points",
    annualized: kind === "xirr",
    period: { start_date: START, end_date: END },
    availability: "available",
    quality: "exact",
    reason_codes: [],
  });
  return {
    schema_version: 1,
    scope,
    account_id: accountId,
    start_date: START,
    end_date: END,
    performance_currency: "RUB",
    xirr: forMetric("xirr", xirr),
    twrr: forMetric("twrr", twrr),
    evidence: {
      scope,
      account_id: accountId,
      start_date: START,
      end_date: END,
      performance_currency: "RUB",
      availability: "available",
      reason_codes: [],
      scope_membership: {
        status: "complete",
        account_ids: [1, 3],
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
    diagnostics: [],
  };
}

function setup(path: string) {
  const client = createQueryClient();
  const reads: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      reads.push(`${options?.method ?? "GET"} ${url.pathname}${url.search}`);
      let data: unknown;
      switch (url.pathname) {
        case "/api/accounts":
          data = [
            { id: 1, name: "Депозитный счёт", account_type: "cash", status: "active" },
            { id: 3, name: "Брокерский счёт", account_type: "brokerage", status: "active" },
          ];
          break;
        case "/api/months":
          data = [
            {
              id: 90,
              year: 2031,
              month: 5,
              status: "closed",
              snapshot_date: START,
              source: "manual",
            },
            {
              id: 91,
              year: 2031,
              month: 7,
              status: "closed",
              snapshot_date: END,
              source: "manual",
            },
          ];
          break;
        case "/api/performance/readiness":
          if (url.searchParams.get("scope") === "account") {
            data = readinessFixture({
              scope: "account",
              accountId: Number(url.searchParams.get("account_id")),
              xirr: "8.00",
              twrr: "7.00",
            });
          } else {
            data = readinessFixture({});
          }
          break;
        case "/api/performance/attribution":
          data = {
            contract: "PERF04A",
            contract_version: 1,
            metric: "value_change_after_external_flows",
            grain: "selected_scope",
            scope: "portfolio",
            account_id: null,
            period: { start_date: START, end_date: END },
            performance_currency: "RUB",
            availability: "available",
            quality: "exact",
            opening_value: { amount: "3151300.00", currency: "RUB" },
            closing_value: { amount: "3203900.00", currency: "RUB" },
            value: { amount: "42600.00", currency: "RUB" },
            external_flow_summary: {
              contributions: { amount: "0.00", currency: "RUB" },
              withdrawals: { amount: "0.00", currency: "RUB" },
              signed_total: { amount: "0.00", currency: "RUB" },
            },
            evidence: {
              opening_valuation: { availability: "available", reason_codes: [] },
              closing_valuation: { availability: "available", reason_codes: [] },
              scope_membership: { status: "complete", reason_codes: [] },
              cash_boundary_coverage: { status: "complete", reason_codes: [] },
              in_kind_boundary_coverage: { status: "complete", reason_codes: [] },
              external_flows: { status: "complete", reason_codes: [] },
            },
            reason_codes: [],
          };
          break;
        default:
          throw new Error(`Unexpected API: ${url.pathname}${url.search}`);
      }
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <Routes>
            <Route path="v2/capital/performance" element={<UiV2CapitalPerformanceDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { mount, reads };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const PORTFOLIO_PATH = `/v2/capital/performance?start=${START}&end=${END}&scope=portfolio`;

describe("UiV2CapitalPerformanceDetail", () => {
  it("shows independent metrics, composition and the accounts table", async () => {
    const { mount, reads } = setup(PORTFOLIO_PATH);
    mount();

    expect(await screen.findByTestId("performance-detail-xirr")).toHaveTextContent("+7,42%");
    expect(screen.getByTestId("performance-detail-twrr")).toHaveTextContent("+6,10%");
    expect(screen.getByTestId("performance-detail-period")).toHaveTextContent(/31\.05\.2031/);
    expect(screen.getByTestId("performance-detail-period")).toHaveTextContent(/Портфель/);

    expect(screen.getByTestId("performance-composition-cash")).toHaveTextContent("Брокерский счёт");
    expect(screen.getByTestId("performance-composition-membership")).toHaveTextContent(
      "Депозитный счёт",
    );
    expect(screen.queryByTestId("performance-composition-inkind")).toBeNull();

    const table = await screen.findByTestId("performance-accounts-table");
    const row = within(table).getByTestId("performance-account-row-3");
    await waitFor(() => expect(within(row).getByText("+8,00%")).toBeVisible());
    expect(within(row).getByText("+7,00%")).toBeVisible();
    expect(within(row).getByText("доступен")).toBeVisible();
    expect(within(row).getByRole("link", { name: "Открыть" })).toHaveAttribute(
      "href",
      `/v2/capital/performance?start=${START}&end=${END}&scope=account&account_id=3`,
    );

    expect(screen.getByTestId("performance-detail-bridge")).toHaveTextContent(/42\s?600/);
    const bridgeNote = screen.getByTestId("performance-detail-bridge").parentElement;
    expect(bridgeNote).toHaveTextContent(/Изменение стоимости после внешних потоков/i);
    expect(bridgeNote).toHaveTextContent(/Не прибыль и не доходность/i);
    expect(reads.some((read) => read.includes("/api/performance/readiness"))).toBe(true);
  });

  it("rejects a reversed interval as a context error without fetching readiness", async () => {
    const { mount, reads } = setup(
      `/v2/capital/performance?start=${END}&end=${START}&scope=portfolio`,
    );
    mount();

    expect(await screen.findByText(/Начальная дата позже конечной/i)).toBeVisible();
    expect(reads.some((read) => read.includes("/api/performance/readiness"))).toBe(false);
  });

  it("rejects an unknown account without falling back to the portfolio", async () => {
    const { mount } = setup(
      `/v2/capital/performance?start=${START}&end=${END}&scope=account&account_id=999`,
    );
    mount();

    expect(await screen.findByText(/недоступен.*Портфель не подставляется/i)).toBeVisible();
  });

  it("reports the classes view as unsupported with a way back to accounts", async () => {
    const { mount } = setup(`${PORTFOLIO_PATH}&view=classes`);
    mount();

    expect(await screen.findByText(/Разрез по классам ещё не поддерживается/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Перейти к счетам" }));
    await screen.findByTestId("performance-accounts-table");
    expect(screen.getByTestId("test-location")).toHaveTextContent("view=accounts");
  });

  it("disables a preset without an exact snapshot date", async () => {
    const { mount } = setup(PORTFOLIO_PATH);
    mount();

    const preset = await screen.findByRole("button", { name: "1 мес." });
    expect(preset).toBeDisabled();
    expect(preset).toHaveAttribute(
      "title",
      expect.stringContaining("Нет снимка на точную дату пресета"),
    );
  });

  it("keeps period controls keyboard-operable", async () => {
    const { mount } = setup(PORTFOLIO_PATH);
    mount();

    await screen.findByTestId("performance-detail-period");
    const apply = screen.getByRole("button", { name: "Применить даты" });
    apply.focus();
    expect(apply).toHaveFocus();
    const scope = screen.getByLabelText("Охват");
    scope.focus();
    expect(scope).toHaveFocus();
  });
});
