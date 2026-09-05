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

    expect(
      await screen.findAllByText(
        /Накопленный облагаемый доход, текущая ступень и расстояние до порога недоступны/i,
      ),
    ).not.toHaveLength(0);
    expect(screen.queryByText(/salary_tax_history_incomplete/)).toBeNull();
    expect(screen.queryByText(/gross YTD|marginal|backend/i)).toBeNull();
    expect(screen.getByText("Synthetic IIS")).toBeInTheDocument();
    expect(screen.queryByText(/2\s*500\s*000/)).toBeNull();
  });

  it("renders tax year and as-of reporting month from backend", async () => {
    render(<TaxIisPlannerPage />);

    expect(await screen.findByText(/Налоговый год 2031/)).toBeInTheDocument();
    expect(screen.getByText(/Срез .*2031/)).toBeInTheDocument();
  });

  it("renders exact threshold and distance values from backend without recalculation", async () => {
    const planner = completePlanner();
    planner.salary_tax = {
      ...planner.salary_tax,
      taxable_gross_ytd: money("2500000.00"),
      next_threshold: money("5000000.00"),
      // Deliberately NOT threshold minus YTD (5 000 000 − 2 500 000 = 2 500 000),
      // so the test proves the UI renders the backend distance verbatim.
      distance_to_next_threshold: money("1111111.00"),
    };
    vi.mocked(getTaxIisPlanner).mockResolvedValue(planner);

    render(<TaxIisPlannerPage />);

    expect(await screen.findAllByText(/1\s*111\s*111/)).not.toHaveLength(0);
    expect(screen.getByText(/Порог .*5\s*000\s*000/)).toBeInTheDocument();
    // Backend distance must not be replaced by a frontend threshold-minus-YTD guess.
    expect(screen.queryByText(/2\s*500\s*000.*1\s*111\s*111|1\s*111\s*111.*2\s*500\s*000/)).toBeNull();
    expect(await screen.findByText(/2\s*500\s*000/)).toBeInTheDocument();
  });

  it("keeps incomplete salary values unavailable and never renders them as zero", async () => {
    vi.mocked(getTaxIisPlanner).mockResolvedValue(incompletePlanner());

    render(<TaxIisPlannerPage />);

    await screen.findAllByText(/История зарплатного НДФЛ неполна/i);
    expect(screen.getByText(/Недоступно при неполной истории/)).toBeInTheDocument();
    // Salary values must stay unavailable ("—"), never collapsed to an exact zero.
    expect(screen.queryByText("0 ₽", { exact: true })).toBeNull();
    expect(screen.queryByText("0%", { exact: true })).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText(/2\s*500\s*000/)).toBeNull();
  });

  it("shows an explicit empty state when no IIS accounts exist", async () => {
    const planner = completePlanner();
    vi.mocked(getTaxIisPlanner).mockResolvedValue({ ...planner, iis_accounts: [] });

    render(<TaxIisPlannerPage />);

    expect(await screen.findByText("Нет профилей ИИС")).toBeInTheDocument();
    expect(
      screen.getByText(/В сохранённых данных нет счетов с профилем ИИС/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Synthetic IIS")).toBeNull();
  });

  it("states explicitly that year-end projection is not included", async () => {
    render(<TaxIisPlannerPage />);

    expect(await screen.findByText(/без прогноза до конца года/i)).toBeInTheDocument();
  });

  it("shows loading and error states via existing conventions", async () => {
    vi.mocked(getTaxIisPlanner).mockImplementation(() => new Promise(() => {}));

    const { unmount } = render(<TaxIisPlannerPage />);
    expect(await screen.findByText(/Собираем текущий налоговый контекст/)).toBeInTheDocument();
    unmount();

    vi.mocked(getTaxIisPlanner).mockRejectedValue(new Error("planner offline"));
    render(<TaxIisPlannerPage />);
    expect(await screen.findByText("Не удалось загрузить планировщик")).toBeInTheDocument();
    expect(screen.getByText(/planner offline/)).toBeInTheDocument();
  });
});
