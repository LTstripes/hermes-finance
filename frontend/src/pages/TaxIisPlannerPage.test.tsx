import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listMonths } from "../api/months";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { ReportingMonth, TaxIisPlanner } from "../api/types";
import { TaxIisPlannerPage } from "./TaxIisPlannerPage";

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
}));

vi.mock("../api/taxIisPlanner", () => ({
  getTaxIisPlanner: vi.fn(),
}));

const month: ReportingMonth = {
  id: 2,
  year: 2031,
  month: 2,
  status: "draft",
  snapshot_date: "2031-02-28",
  source: "manual",
};

const money = (amount: string) => ({ amount, currency: "RUB" });

function completePlanner(): TaxIisPlanner {
  return {
    contract_version: "tax_iis_planner_v1",
    tax_year: 2031,
    as_of: {
      reporting_month: month,
      selection_reason: "requested",
    },
    salary_tax: {
      tax_year: 2031,
      history_complete: true,
      history_coverage: "complete",
      available: true,
      opening_context_available: false,
      taxable_gross_ytd: money("2500000.00"),
      current_marginal_bracket: {
        threshold_from: money("2400000.00"),
        threshold_to: money("5000000.00"),
        rate_bps: 1500,
      },
      current_marginal_rate_bps: 1500,
      next_threshold: money("5000000.00"),
      distance_to_next_threshold: money("2500000.00"),
      tax_bracket_source: "official_default",
      warning_codes: [],
    },
    iis_accounts: [
      {
        account_id: 7,
        account_name: "Synthetic IIS",
        iis_type: "type_a",
        opened_at: "2031-01-01",
        eligible_close_at: "2036-01-01",
        contributions_by_tax_year: [
          { tax_year: 2031, amount: money("400000.00"), is_target_reached: true },
        ],
        tax_benefits: {
          planned: money("60000.00"),
          submitted: money("50000.00"),
          received: money("40000.00"),
          rejected: money("10000.00"),
        },
      },
    ],
    warnings: [],
  };
}

function incompletePlanner(): TaxIisPlanner {
  const planner = completePlanner();
  return {
    ...planner,
    salary_tax: {
      ...planner.salary_tax,
      history_complete: false,
      history_coverage: "unavailable",
      available: false,
      taxable_gross_ytd: null,
      current_marginal_bracket: null,
      current_marginal_rate_bps: null,
      next_threshold: null,
      distance_to_next_threshold: null,
      warning_codes: ["salary_tax_history_incomplete"],
    },
    warnings: ["salary_tax_history_incomplete"],
  };
}

describe("TaxIisPlannerPage", () => {
  beforeEach(() => {
    vi.mocked(listMonths).mockResolvedValue([month]);
    vi.mocked(getTaxIisPlanner).mockResolvedValue(completePlanner());
  });

  it("renders backend salary context and keeps IIS benefit statuses separate", async () => {
    render(<TaxIisPlannerPage />);

    expect(await screen.findByRole("heading", { name: "Налоги и ИИС" })).toBeInTheDocument();
    expect(await screen.findAllByText(/2\s*500\s*000/)).not.toHaveLength(0);
    expect(screen.getByText(/15%/)).toBeInTheDocument();
    expect(screen.getByText(/Цель достигнута/)).toBeInTheDocument();
    expect(screen.getByText("Запланировано", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Подано", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Получено", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Отклонено", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/эти статусы не складываются/)).toBeInTheDocument();
    expect(screen.getByText(/официальная шкала/i)).toBeInTheDocument();
    expect(getTaxIisPlanner).toHaveBeenCalledWith(
      { reportingMonthId: month.id },
      expect.any(AbortSignal),
    );
    expect(screen.queryByText(/portfolio_result|cost_basis/i)).toBeNull();
  });

  it("shows incomplete salary history as unavailable without guessing a gross", async () => {
    vi.mocked(getTaxIisPlanner).mockResolvedValue(incompletePlanner());

    render(<TaxIisPlannerPage />);

    expect(await screen.findAllByText(/salary_tax_history_incomplete/)).not.toHaveLength(0);
    expect(
      screen.getAllByText(/gross YTD, текущая ступень и расстояние до порога недоступны/i),
    ).not.toHaveLength(0);
    expect(screen.getByText("Synthetic IIS")).toBeInTheDocument();
    expect(screen.queryByText(/2\s*500\s*000/)).toBeNull();
  });
});
