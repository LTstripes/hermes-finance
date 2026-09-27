import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type {
  PerformanceAttribution,
  PerformanceReadiness,
  PerformanceReadinessDiagnostic,
} from "../api/types";
import {
  CapitalPerformanceSummary,
  type CapitalPerformanceSummaryProps,
} from "./CapitalPerformanceSummary";

const START = "2031-05-31";
const END = "2031-07-31";
const HREF = `/v2/capital/performance?start=${START}&end=${END}&scope=portfolio`;

function metric(
  kind: "xirr" | "twrr",
  value: string | null,
  available = true,
): PerformanceReadiness["xirr"] {
  return {
    metric: kind,
    scope: "portfolio",
    account_id: null,
    performance_currency: "RUB",
    value,
    value_unit: "percentage_points",
    annualized: kind === "xirr",
    period: { start_date: START, end_date: END },
    availability: available ? "available" : "not_computable",
    quality: available ? "exact" : "unavailable",
    reason_codes: available ? [] : [`not_computable_${kind}_missing`],
  } as PerformanceReadiness["xirr"];
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

function diagnostic(
  key: string,
  affected: Array<"xirr" | "twrr">,
  capability:
    | "available"
    | "requires_reopen"
    | "not_implemented"
    | "source_required"
    | "unsupported" = "available",
): PerformanceReadinessDiagnostic {
  return {
    key,
    reason_codes: [`canonical_${key}`],
    affected_metrics: affected,
    category:
      capability === "available" || capability === "requires_reopen" ? "actionable" : "limitation",
    refs: { ...EMPTY_REFS },
    action: {
      kind: "inspect_result",
      capability,
      params: { ...EMPTY_REFS },
      verify: "reread_readiness",
    },
  };
}

function readinessFixture(
  xirrValue: string | null,
  twrrValue: string | null,
  diagnostics: PerformanceReadinessDiagnostic[] = [],
): PerformanceReadiness {
  return {
    schema_version: 1,
    scope: "portfolio",
    account_id: null,
    start_date: START,
    end_date: END,
    performance_currency: "RUB",
    xirr: metric("xirr", xirrValue, xirrValue !== null),
    twrr: metric("twrr", twrrValue, twrrValue !== null),
    evidence: {
      scope: "portfolio",
      account_id: null,
      start_date: START,
      end_date: END,
      performance_currency: "RUB",
      availability: xirrValue !== null || twrrValue !== null ? "available" : "not_computable",
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
    diagnostics,
  };
}

function attributionFixture(): PerformanceAttribution {
  return {
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
}

function baseProps(
  overrides: Partial<CapitalPerformanceSummaryProps> = {},
): CapitalPerformanceSummaryProps {
  return {
    attribution: attributionFixture(),
    attributionError: false,
    attributionReady: true,
    detailHref: HREF,
    pairStart: START,
    pairEnd: END,
    readiness: readinessFixture("7.42", "6.10"),
    readinessError: false,
    readinessReady: true,
    retry: vi.fn(),
    ...overrides,
  };
}

function renderSummary(props: CapitalPerformanceSummaryProps) {
  return render(
    <MemoryRouter>
      <CapitalPerformanceSummary {...props} />
    </MemoryRouter>,
  );
}

describe("CapitalPerformanceSummary", () => {
  it("shows both metrics with exact dates, units and currency", () => {
    renderSummary(baseProps());
    expect(screen.getByTestId("capital-performance-period")).toHaveTextContent(/31\.05\.2031/);
    expect(screen.getByTestId("capital-performance-period")).toHaveTextContent(/31\.07\.2031/);
    expect(screen.getByTestId("capital-performance-period")).toHaveTextContent(/RUB/);
    expect(screen.getByTestId("capital-performance-period")).toHaveTextContent(/п\.п\./);
    expect(screen.getByTestId("capital-performance-xirr")).toHaveTextContent("+7,42%");
    expect(screen.getByTestId("capital-performance-twrr")).toHaveTextContent("+6,10%");
    expect(screen.getByText(/приведён к году по короткому периоду/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "Подробнее" })).toHaveAttribute("href", HREF);
  });

  it("keeps an available XIRR visible when TWRR is blocked", () => {
    renderSummary(
      baseProps({
        readiness: readinessFixture("5.00", null, [
          diagnostic("valuation_boundary", ["twrr"], "not_implemented"),
        ]),
      }),
    );
    expect(screen.getByTestId("capital-performance-xirr")).toHaveTextContent("+5,00%");
    expect(screen.getByTestId("capital-performance-twrr")).toHaveTextContent(
      /Нет подтверждённого наблюдения до\/после операции/i,
    );
    expect(screen.getByRole("link", { name: "Проверить данные" })).toHaveAttribute("href", HREF);
  });

  it("shows at most two priority reasons with a path to all of them", () => {
    renderSummary(
      baseProps({
        readiness: readinessFixture(null, null, [
          diagnostic("xirr_ambiguous", ["xirr"], "unsupported"),
          diagnostic("cash_history", ["xirr", "twrr"], "requires_reopen"),
          diagnostic("unknown_future_code", ["twrr"], "unsupported"),
        ]),
      }),
    );
    expect(screen.getAllByText(/Не подтверждена полнота денежной истории/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText(/XIRR неоднозначен/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Показаны 2 приоритетные причины из 3/i)).toBeVisible();
    expect(screen.queryByText("unknown_future_code")).toBeNull();
  });

  it("distinguishes an exact zero from a loss", () => {
    renderSummary(
      baseProps({
        readiness: readinessFixture("0", "-3.5"),
      }),
    );
    expect(screen.getByTestId("capital-performance-xirr")).toHaveTextContent("0,00%");
    expect(screen.getByTestId("capital-performance-xirr")).not.toHaveTextContent("+0,00%");
    expect(screen.getByTestId("capital-performance-twrr")).toHaveTextContent(/3,50%/);
  });

  it("never shows a stale response as current", () => {
    const stale = readinessFixture("7.42", "6.10");
    const retry = vi.fn();
    renderSummary(
      baseProps({
        readiness: { ...stale, start_date: "2031-04-30", end_date: "2031-05-31" },
        readinessReady: true,
        retry,
      }),
    );
    expect(screen.queryByText("+7,42%")).toBeNull();
    expect(screen.queryByText("+6,10%")).toBeNull();
    expect(screen.getByText(/прошлый процент как текущий не показывается/i)).toBeVisible();
    const retryButtons = screen.getAllByRole("button", { name: "Повторить" });
    expect(retryButtons.length).toBeGreaterThan(0);
    fireEvent.click(retryButtons[0]);
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("hides both metrics and retries the coherent read when readiness fails", () => {
    const retry = vi.fn();
    renderSummary(
      baseProps({
        readiness: null,
        readinessError: true,
        readinessReady: false,
        retry,
      }),
    );
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getByText(/Проверка готовности не завершилась/i)).toBeVisible();
    fireEvent.click(screen.getAllByRole("button", { name: "Повторить" })[0]);
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("shows loading placeholders while the coherent read is pending", () => {
    renderSummary(
      baseProps({
        readiness: null,
        readinessError: false,
        readinessReady: false,
      }),
    );
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getByText(/Проверяем готовность расчёта/i)).toBeVisible();
  });

  it("keeps the monetary bridge secondary with its disclaimer", () => {
    renderSummary(baseProps());
    const bridge = screen.getByTestId("capital-performance-bridge");
    expect(bridge).toHaveTextContent(/42\s?600/);
    expect(bridge).toHaveTextContent(/Не прибыль и не доходность/i);
  });

  it("renders a capability action only for available capabilities", () => {
    const { container } = renderSummary(
      baseProps({
        readiness: readinessFixture(null, null, [
          diagnostic("membership_history", ["xirr", "twrr"], "not_implemented"),
        ]),
      }),
    );
    expect(screen.getByText(/Возможность пока не реализована/i)).toBeVisible();
    expect(container.querySelector("button")).toBeNull();
  });
});
