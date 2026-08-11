import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";

vi.mock("../components/BackendStatus", () => ({
  BackendStatus: () => <div>backend status stub</div>,
}));
vi.mock("../components/MainGoalPanel", () => ({
  MainGoalPanel: ({ reportingMonthId }: { reportingMonthId: number | null }) => (
    <div>main goal {reportingMonthId ?? "none"}</div>
  ),
}));
vi.mock("../components/charts/AssetAllocationChart", () => ({
  AssetAllocationChart: () => <div>asset chart stub</div>,
}));
vi.mock("../components/charts/CapitalChart", () => ({
  CapitalChart: () => <div>capital chart stub</div>,
}));
vi.mock("../components/charts/InvestmentResultChart", () => ({
  InvestmentResultChart: () => <div>result chart stub</div>,
}));
vi.mock("../components/charts/PassiveIncomeChart", () => ({
  PassiveIncomeChart: () => <div>passive chart stub</div>,
}));

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const months = [
  { id: 1, year: 2031, month: 1, status: "closed", snapshot_date: "2031-01-31", source: "manual" },
  { id: 2, year: 2031, month: 2, status: "draft", snapshot_date: "2031-02-28", source: "manual" },
];

function dashboard(monthId: number, warning: string | null = null) {
  const month = months.find((row) => row.id === monthId) ?? months[0];
  return {
    month,
    kpis: {
      liquid_capital_net: { amount: "4820500.00", currency: "RUB" },
      liquid_capital_delta: { amount: "120000.00", currency: "RUB" },
      forecast_monthly_passive_income: { amount: "86420.00", currency: "RUB" },
      passive_income_average: { amount: "85200.00", currency: "RUB" },
      passive_income_average_months: 6,
      passive_income_average_complete: false,
      goal_progress_pct: "68.0",
      goal_target: { amount: "100000.00", currency: "RUB" },
      mandatory_expenses: { amount: "150000.00", currency: "RUB" },
      mandatory_expense_coverage_pct: "56.8",
      mortgage_balance: { amount: "12450000.00", currency: "RUB" },
      mortgage_coverage_pct: "38.7",
    },
    mortgage: {
      mortgage_balance: { amount: "12450000.00", currency: "RUB" },
      coverage_pct: "38.7",
      gap: { amount: "7629500.00", currency: "RUB" },
    },
    historical_series: [],
    asset_allocation: [],
    result_by_account: [],
    result_by_instrument_class: [],
    warnings: warning ? [warning] : [],
    calculation_version: "g03-test",
  };
}

function setupDashboard(
  dashboardResponse: (monthId: number) => Response,
  monthsResponse: Response = jsonResponse(months),
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/months") {
      return monthsResponse;
    }
    if (url === "/api/months/2/dashboard") {
      return dashboardResponse(2);
    }
    if (url === "/api/months/1/dashboard") {
      return dashboardResponse(1);
    }
    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${url}`, details: [] } },
      404,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DashboardPage G03 component contract", () => {
  it("selects the newest month, switches KPI and main-goal source, and renders warnings", async () => {
    const fetchMock = setupDashboard((monthId) =>
      jsonResponse(dashboard(monthId, monthId === 2 ? "Среднее доступно за 6 месяцев" : null)),
    );
    const user = userEvent.setup();

    const selector = await screen.findByLabelText("Месяц KPI");
    expect(selector).toHaveValue("2");
    expect(screen.getByText("main goal 2")).toBeInTheDocument();
    expect(await screen.findByText("Среднее доступно за 6 месяцев")).toBeInTheDocument();

    await user.selectOptions(selector, "1");

    expect(selector).toHaveValue("1");
    expect(await screen.findByText("main goal 1")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/months/1/dashboard"),
    ).toBe(true);
    expect(screen.getByText("Предупреждений нет.")).toBeInTheDocument();
  });

  it("shows localized dashboard error state without pretending that KPI data loaded", async () => {
    setupDashboard(() =>
      jsonResponse(
        { error: { code: "internal_error", message: "Dashboard API failed", details: [] } },
        500,
      ),
    );

    const alerts = await screen.findAllByRole("alert");
    expect(
      alerts.some(
        (alert) => alert.textContent === "Внутренняя ошибка приложения. Попробуй обновить данные.",
      ),
    ).toBe(true);
    expect(screen.getAllByText("Не удалось загрузить показатели")).toHaveLength(5);
    expect(screen.queryByText("Dashboard API failed")).toBeNull();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
  });
});
