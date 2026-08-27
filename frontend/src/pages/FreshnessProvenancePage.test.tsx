import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FreshnessProvenanceSummary, ReportingMonth } from "../api/types";
import { FreshnessProvenancePage } from "./FreshnessProvenancePage";

const months: ReportingMonth[] = [
  {
    id: 2,
    year: 2026,
    month: 8,
    status: "draft",
    snapshot_date: "2026-08-31",
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

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function family(overrides: Partial<FreshnessProvenanceSummary["families"][number]>) {
  return {
    family_id: "market_quotes",
    title: "Рыночные котировки",
    status: "stale" as const,
    providers: ["t_invest"],
    coverage: {
      row_count: 2,
      current_count: 0,
      stale_count: 1,
      unavailable_count: 0,
      unknown_count: 0,
      missing_count: 0,
      manual_count: 1,
      provider_count: 1,
    },
    reasons: [
      {
        code: "quote_stale",
        severity: "warning",
        message:
          "Есть применённые котировки старше окна актуальности относительно даты оценки месяца.",
      },
      {
        code: "manual_source_no_provider_timestamp",
        severity: "info",
        message: "Ручные значения без времени наблюдения провайдера не считаются устаревшими.",
      },
    ],
    items: [
      {
        item_kind: "quote",
        label: "Synthetic Stock",
        freshness_status: "stale" as const,
        source_kind: "t_invest",
        source_timestamp_kind: "price_date",
        source_date: "2026-08-10",
        source_datetime: null,
        fetched_at: "2026-08-20T10:00:00+00:00",
        import_apply_time: "2026-08-21T11:00:00+00:00",
        local_edit_time: "2026-08-21T11:00:00+00:00",
        reason_codes: ["quote_stale"],
        account_name: "Broker",
        instrument_name: "Synthetic Stock",
      },
      {
        item_kind: "quote",
        label: "Manual Fund",
        freshness_status: "not_applicable" as const,
        source_kind: "manual",
        source_timestamp_kind: "not_applicable",
        source_date: null,
        source_datetime: null,
        fetched_at: null,
        import_apply_time: null,
        local_edit_time: "2026-08-21T12:00:00+00:00",
        reason_codes: ["manual_source_no_provider_timestamp"],
        account_name: "Broker",
        instrument_name: "Manual Fund",
      },
    ],
    ...overrides,
  };
}

function summary(): FreshnessProvenanceSummary {
  return {
    reporting_month: months[0],
    evaluated_on: "2026-08-27",
    quote_valuation_target_date: "2026-08-27",
    generated_at: "2026-08-27T09:30:00+00:00",
    providers: ["t_invest"],
    reasons: [
      {
        code: "quote_stale",
        severity: "warning",
        message:
          "Есть применённые котировки старше окна актуальности относительно даты оценки месяца.",
      },
      {
        code: "manual_source_no_provider_timestamp",
        severity: "info",
        message: "Ручные значения без времени наблюдения провайдера не считаются устаревшими.",
      },
    ],
    families: [
      family({}),
      family({
        family_id: "t_invest_payouts",
        title: "Выплаты T-Invest",
        status: "missing",
        providers: [],
        coverage: {
          row_count: 0,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 0,
        },
        reasons: [
          {
            code: "payout_none_for_month",
            severity: "info",
            message: "В месяце нет принятых выплат T-Invest.",
          },
        ],
        items: [],
      }),
      family({
        family_id: "alfa_pro_positions",
        title: "Позиции Alfa PRO",
        status: "unknown",
        providers: [],
        coverage: {
          row_count: 0,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 1,
          missing_count: 0,
          manual_count: 0,
          provider_count: 0,
        },
        reasons: [
          {
            code: "alfa_pro_observation_not_persisted",
            severity: "info",
            message:
              "Hermes не сохраняет время наблюдения Alfa PRO после apply, поэтому актуальность этой семьи нельзя честно классифицировать.",
          },
        ],
        items: [],
      }),
      family({
        family_id: "alfa_statement_payouts",
        title: "Выписка Alfa PDF",
        status: "missing",
        providers: [],
        items: [],
        reasons: [],
        coverage: {
          row_count: 0,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 0,
        },
      }),
      family({
        family_id: "manual_month_data",
        title: "Ручные данные месяца",
        status: "not_applicable",
        providers: [],
        items: [
          {
            item_kind: "manual_group",
            label: "Доходы: 1",
            freshness_status: "not_applicable",
            source_kind: "manual",
            source_timestamp_kind: "not_applicable",
            source_date: null,
            source_datetime: null,
            fetched_at: null,
            import_apply_time: null,
            local_edit_time: null,
            reason_codes: ["manual_source_no_provider_timestamp"],
            account_name: null,
            instrument_name: null,
          },
        ],
        reasons: [
          {
            code: "manual_source_no_provider_timestamp",
            severity: "info",
            message: "Ручные значения без времени наблюдения провайдера не считаются устаревшими.",
          },
        ],
        coverage: {
          row_count: 1,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 1,
          provider_count: 0,
        },
      }),
      family({
        family_id: "deposit_cash_snapshots",
        title: "Депозиты и кэш",
        status: "missing",
        providers: [],
        items: [],
        reasons: [],
        coverage: {
          row_count: 0,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 0,
        },
      }),
    ],
  };
}

describe("FreshnessProvenancePage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows stale quotes, keeps manual rows out of stale, and does not invent a score", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(months))
      .mockResolvedValueOnce(jsonResponse(summary()));
    vi.stubGlobal("fetch", fetchMock);

    render(<FreshnessProvenancePage />);

    expect(screen.getByRole("heading", { name: "Актуальность данных" })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Рыночные котировки")).toBeInTheDocument();
    });

    expect(screen.getByText("Не смешивать эти даты")).toBeInTheDocument();
    expect(screen.getByText("31.08.2026")).toBeInTheDocument();
    expect(screen.getAllByText("27.08.2026").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "Есть применённые котировки старше окна актуальности относительно даты оценки месяца.",
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("Broker · Synthetic Stock")).toBeInTheDocument();
    expect(screen.getByText("10.08.2026")).toBeInTheDocument();
    expect(screen.getAllByText(/21\.08\.2026\s11:00\sUTC/).length).toBeGreaterThan(0);
    expect(screen.getByText("Broker · Manual Fund")).toBeInTheDocument();
    expect(screen.getAllByText("Вручную / не оценивается").length).toBeGreaterThan(0);
    expect(screen.getByText("Позиции Alfa PRO")).toBeInTheDocument();
    expect(
      screen.getByText(/Hermes не сохраняет время наблюдения Alfa PRO после apply/),
    ).toBeInTheDocument();
    expect(screen.getByText("Доходы: 1")).toBeInTheDocument();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
    expect(screen.queryByText("freshness_score")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Четыре разных часов" }));
    expect(
      screen.getByText(/Ручное значение без timestamp провайдера не считается устаревшим/),
    ).toBeInTheDocument();
  });
});
