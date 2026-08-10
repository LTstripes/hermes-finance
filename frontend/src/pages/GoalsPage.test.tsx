import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createGoal,
  deleteGoal,
  listGoals,
  listGoalSummary,
  updateGoal,
  type Goal,
  type GoalSummary,
} from "../api/goals";
import { listMonths } from "../api/months";
import { GoalsPage } from "./GoalsPage";

vi.mock("../api/goals", () => ({
  createGoal: vi.fn(),
  deleteGoal: vi.fn(),
  listGoals: vi.fn(),
  listGoalSummary: vi.fn(),
  updateGoal: vi.fn(),
}));

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
}));

const mainGoal: Goal = {
  id: 1,
  name: "Пассивный доход",
  goal_type: "passive_income",
  target_value: { amount: "100000.00", currency: "RUB" },
  target_date: "2031-12-31",
  is_active: true,
  is_main: true,
  calculation_mode: "monthly_net_passive_income",
  notes: null,
};

const secondGoal: Goal = {
  id: 2,
  name: "Запасная цель",
  goal_type: "passive_income",
  target_value: { amount: "150000.00", currency: "RUB" },
  target_date: null,
  is_active: true,
  is_main: false,
  calculation_mode: "monthly_net_passive_income",
  notes: null,
};

const inactiveGoal: Goal = {
  id: 3,
  name: "Капитал потом",
  goal_type: "capital",
  target_value: { amount: "7000000.00", currency: "RUB" },
  target_date: null,
  is_active: false,
  is_main: false,
  calculation_mode: "liquid_capital_net",
  notes: null,
};

function withForecast(goal: Goal, progress: string | null, status = "not_projectable"): GoalSummary {
  return {
    ...goal,
    achievement_forecast: {
      goal_id: goal.id,
      reporting_month_id: 11,
      as_of_date: "2031-02-28",
      method_version: "goal_achievement_v1",
      source_forecast_version: goal.goal_type === "passive_income" ? "v1" : null,
      status: goal.is_active ? (status as GoalSummary["achievement_forecast"]["status"]) : "inactive",
      reason_code: goal.is_active ? "no_trajectory_model" : "goal_inactive",
      current_value: goal.is_active ? { amount: "80000.00", currency: "RUB" } : null,
      target_value: goal.target_value,
      remaining_amount: goal.is_active ? { amount: "20000.00", currency: "RUB" } : null,
      progress_pct: goal.is_active ? progress : null,
      estimated_achievement_date: null,
      is_approximate: false,
      warnings: [],
    },
  };
}

const listGoalsMock = vi.mocked(listGoals);
const listGoalSummaryMock = vi.mocked(listGoalSummary);
const createGoalMock = vi.mocked(createGoal);
const updateGoalMock = vi.mocked(updateGoal);
const deleteGoalMock = vi.mocked(deleteGoal);
const listMonthsMock = vi.mocked(listMonths);

describe("GoalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listGoalsMock.mockResolvedValue([mainGoal, secondGoal, inactiveGoal]);
    listGoalSummaryMock.mockResolvedValue([
      withForecast(mainGoal, "80.00"),
      withForecast(secondGoal, "53.33"),
      withForecast(inactiveGoal, null),
    ]);
    listMonthsMock.mockResolvedValue([
      {
        id: 10,
        year: 2031,
        month: 1,
        status: "closed",
        snapshot_date: "2031-01-31",
        source: "manual",
      },
      {
        id: 11,
        year: 2031,
        month: 2,
        status: "draft",
        snapshot_date: "2031-02-28",
        source: "manual",
      },
    ]);
    createGoalMock.mockResolvedValue(secondGoal);
    updateGoalMock.mockResolvedValue(secondGoal);
    deleteGoalMock.mockResolvedValue(undefined);
  });

  it("shows active/inactive goals and backend-derived progress for the newest month", async () => {
    render(<GoalsPage />);

    expect(await screen.findByText("Пассивный доход")).toBeInTheDocument();
    expect(screen.getByText("Капитал потом")).toBeInTheDocument();
    expect(screen.getByLabelText("Оценка на месяц")).toHaveValue("11");
    expect(screen.getByText("80,00%")).toBeInTheDocument();
    expect(screen.getByText("53,33%")).toBeInTheDocument();
    expect(screen.getAllByText("Нет честного прогноза даты").length).toBeGreaterThan(0);
    expect(listGoalSummaryMock).toHaveBeenCalledWith(
      11,
      { includeInactive: true },
      expect.any(AbortSignal),
    );
  });

  it("creates a goal with exact normalized money and the canonical calculation mode", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByText("Пассивный доход");
    await user.click(screen.getByRole("button", { name: "Создать цель" }));
    await user.type(screen.getByLabelText("Название"), "Новая цель");
    await user.type(screen.getByLabelText("Целевое значение"), "250000,50");
    await user.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() =>
      expect(createGoalMock).toHaveBeenCalledWith({
        name: "Новая цель",
        goal_type: "passive_income",
        target_value: { amount: "250000.50", currency: "RUB" },
        target_date: null,
        is_active: true,
        is_main: false,
        calculation_mode: "monthly_net_passive_income",
        notes: null,
      }),
    );
  });

  it("selects another passive goal as main through PATCH", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    const secondName = await screen.findByText("Запасная цель");
    const row = secondName.closest("tr");
    expect(row).not.toBeNull();
    await user.click(within(row!).getByRole("button", { name: "Сделать основной" }));

    await waitFor(() => expect(updateGoalMock).toHaveBeenCalledWith(2, { is_main: true }));
  });

  it("edits and deletes a non-main goal while keeping destructive actions off the main goal", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    const mainRow = (await screen.findByText("Пассивный доход")).closest("tr");
    expect(mainRow).not.toBeNull();
    expect(within(mainRow!).queryByRole("button", { name: "Удалить" })).toBeNull();
    expect(within(mainRow!).queryByRole("button", { name: "Деактивировать" })).toBeNull();

    const secondRow = screen.getByText("Запасная цель").closest("tr");
    expect(secondRow).not.toBeNull();
    await user.click(within(secondRow!).getByRole("button", { name: "Изменить" }));
    const target = screen.getByLabelText("Целевое значение");
    await user.clear(target);
    await user.type(target, "175000");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(updateGoalMock).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          target_value: { amount: "175000.00", currency: "RUB" },
          calculation_mode: "monthly_net_passive_income",
        }),
      ),
    );

    await user.click(within(secondRow!).getByRole("button", { name: "Удалить" }));
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(deleteGoalMock).toHaveBeenCalledWith(2));
  });
});
