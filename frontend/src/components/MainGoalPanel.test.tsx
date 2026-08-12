import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listGoalSummary, type GoalSummary } from "../api/goals";
import { MainGoalPanel } from "./MainGoalPanel";

vi.mock("../api/goals", () => ({
  listGoalSummary: vi.fn(),
}));

const listGoalSummaryMock = vi.mocked(listGoalSummary);

function mainSummary(status: "achieved" | "not_projectable"): GoalSummary {
  return {
    id: 7,
    name: "Свобода",
    goal_type: "passive_income",
    target_value: { amount: "100000.00", currency: "RUB" },
    target_date: "2032-12-31",
    is_active: true,
    is_main: true,
    calculation_mode: "monthly_net_passive_income",
    notes: null,
    achievement_forecast: {
      goal_id: 7,
      reporting_month_id: 22,
      as_of_date: "2031-06-30",
      method_version: "goal_achievement_v1",
      source_forecast_version: "v1",
      status,
      reason_code: status === "achieved" ? null : "no_trajectory_model",
      current_value: { amount: "75000.00", currency: "RUB" },
      target_value: { amount: "100000.00", currency: "RUB" },
      remaining_amount: { amount: "999.99", currency: "RUB" },
      progress_pct: "12.34",
      estimated_achievement_date: status === "achieved" ? "2031-06-30" : null,
      is_approximate: false,
      warnings: status === "achieved" ? [] : ["Недостаточно данных для траектории"],
    },
  };
}

describe("MainGoalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps unavailable forecast detail behind compact help", async () => {
    const user = userEvent.setup();
    listGoalSummaryMock.mockResolvedValue([mainSummary("not_projectable")]);
    render(
      <MemoryRouter>
        <MainGoalPanel reportingMonthId={22} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Свобода")).toBeInTheDocument();
    expect(screen.getByText("Прогресс цели")).toBeInTheDocument();
    expect(screen.getByText("12,3%")).toBeInTheDocument();
    expect(screen.getByText(/999,99\s₽/)).toBeInTheDocument();
    expect(screen.getByText("Прогноз даты недоступен")).toBeInTheDocument();
    expect(screen.queryByText(/Недостаточно данных, чтобы надёжно спрогнозировать будущую дату/)).toBeNull();
    expect(screen.queryByText("Недостаточно данных для траектории")).toBeNull();
    expect(screen.queryByText("no_trajectory_model")).toBeNull();
    expect(screen.queryByText("goal_achievement_v1")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Почему прогноз цели выглядит так" }));
    expect(
      screen.getByText(/Недостаточно данных, чтобы надёжно спрогнозировать будущую дату/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Недостаточно данных для траектории/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Цели →" })).toHaveAttribute("href", "/goals");
  });

  it("shows the backend snapshot date when the goal is already achieved", async () => {
    listGoalSummaryMock.mockResolvedValue([mainSummary("achieved")]);
    render(
      <MemoryRouter>
        <MainGoalPanel reportingMonthId={22} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Достигнута 30.06.2031")).toBeInTheDocument();
  });
});
