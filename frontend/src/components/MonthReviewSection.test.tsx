import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getDashboard } from "../api/dashboard";
import { listGoalSummary } from "../api/goals";
import { closeMonth, reopenMonth } from "../api/months";
import type { DashboardKpis } from "../api/types";
import { MonthReviewSection } from "./MonthReviewSection";

vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/goals", () => ({ listGoalSummary: vi.fn() }));
vi.mock("../api/months", () => ({
  closeMonth: vi.fn(),
  reopenMonth: vi.fn(),
}));

const kpis: DashboardKpis = {
  liquid_capital_net: { amount: "1000000.00", currency: "RUB" },
  liquid_capital_delta: null,
  forecast_monthly_passive_income: { amount: "15000.00", currency: "RUB" },
  passive_income_average: { amount: "12000.00", currency: "RUB" },
  passive_income_average_months: 6,
  passive_income_average_complete: false,
  goal_progress_pct: "42.5",
  goal_target: { amount: "100000.00", currency: "RUB" },
  mandatory_expenses: { amount: "50000.00", currency: "RUB" },
  mandatory_expense_coverage_pct: "40.0",
  mortgage_balance: { amount: "0.00", currency: "RUB" },
  mortgage_coverage_pct: null,
};

const dashboard = {
  month: {
    id: 7,
    year: 2026,
    month: 7,
    status: "draft",
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  kpis,
  mortgage: {
    mortgage_balance: { amount: "0.00", currency: "RUB" },
    coverage_pct: null,
    gap: { amount: "0.00", currency: "RUB" },
  },
  warnings: ["Среднее доступно по части истории"],
  calculation_version: "1.0",
};

const getDashboardMock = vi.mocked(getDashboard);
const listGoalSummaryMock = vi.mocked(listGoalSummary);
const closeMonthMock = vi.mocked(closeMonth);
const reopenMonthMock = vi.mocked(reopenMonth);

beforeEach(() => {
  vi.clearAllMocks();
  getDashboardMock.mockResolvedValue(dashboard);
  listGoalSummaryMock.mockResolvedValue([]);
  closeMonthMock.mockResolvedValue({ ...dashboard.month, status: "closed" });
  reopenMonthMock.mockResolvedValue({ ...dashboard.month, status: "draft" });
});

describe("MonthReviewSection", () => {
  it("keeps review focused and closes a draft after explicit confirmation", async () => {
    const user = userEvent.setup();
    const onStatusChanged = vi.fn();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={onStatusChanged}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Проверка месяца" })).toBeInTheDocument();
    expect(
      screen.getByText("Есть детали, которые стоит проверить перед закрытием."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть цели →" })).toHaveAttribute("href", "/goals");
    expect(screen.queryByText(/api\/goals/i)).toBeNull();
    expect(screen.queryByRole("heading", { name: "ИИС" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Заметка месяца" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Закрыть месяц" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));

    expect(closeMonthMock).toHaveBeenCalledWith(7);
    expect(onStatusChanged).toHaveBeenCalledOnce();
  });

  it("reopens a closed month without disabling the action", async () => {
    const user = userEvent.setup();
    const onStatusChanged = vi.fn();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={onStatusChanged}
          readOnly
          status="closed"
        />
      </MemoryRouter>,
    );

    const reopen = await screen.findByRole("button", { name: "Открыть заново" });
    expect(reopen).toBeEnabled();
    await user.click(reopen);
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Открыть заново" }));

    expect(reopenMonthMock).toHaveBeenCalledWith(7);
    expect(onStatusChanged).toHaveBeenCalledOnce();
  });
});
