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

function withForecast(
  goal: Goal,
  progress: string | null,
  status = "not_projectable",
): GoalSummary {
  return {
    ...goal,
    achievement_forecast: {
      goal_id: goal.id,
      reporting_month_id: 11,
      as_of_date: "2031-02-28",
      method_version: "goal_achievement_v1",
      source_forecast_version: goal.goal_type === "passive_income" ? "v1" : null,
      status: goal.is_active
        ? (status as GoalSummary["achievement_forecast"]["status"])
        : "inactive",
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

function cardFor(name: string): HTMLElement {
  const heading = screen.getByRole("heading", { level: 3, name });
  const card = heading.closest("article");
  if (!card) throw new Error("expected goal card");
  return card;
}

const listGoalsMock = vi.mocked(listGoals);
const listGoalSummaryMock = vi.mocked(listGoalSummary);
const createGoalMock = vi.mocked(createGoal);
const updateGoalMock = vi.mocked(updateGoal);
const deleteGoalMock = vi.mocked(deleteGoal);
const listMonthsMock = vi.mocked(listMonths);

describe("GoalsPage R03-09 cards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listGoalsMock.mockResolvedValue([secondGoal, inactiveGoal, mainGoal]);
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

  it("puts the main active goal first, shows progress cards, and keeps inactive goals collapsed", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByRole("heading", { level: 3, name: "Пассивный доход" });
    const activePanel = screen.getByText("Цели (2)").closest(".panel");
    if (!activePanel) throw new Error("expected active goals panel");

    const activeCards = within(activePanel).getAllByRole("listitem");
    expect(activeCards).toHaveLength(2);
    expect(within(activeCards[0]).getByRole("heading", { name: "Пассивный доход" })).toBeInTheDocument();
    expect(activeCards[0]).toHaveClass("goal-card--main");

    const mainCard = cardFor("Пассивный доход");
    expect(within(mainCard).getByText("80,0%")).toBeInTheDocument();
    expect(within(mainCard).getByRole("progressbar", { name: /Пассивный доход/ })).toHaveAttribute(
      "value",
      "80.00",
    );
    expect(within(mainCard).getByText(/80\s*000\s*₽/)).toBeInTheDocument();
    expect(within(mainCard).getByText(/100\s*000\s*₽/)).toBeInTheDocument();
    expect(within(mainCard).getByText(/20\s*000\s*₽/)).toBeInTheDocument();
    expect(within(mainCard).getByText("Прогноз даты пока недоступен")).toBeInTheDocument();

    expect(within(mainCard).queryByRole("button", { name: /Действия для цели/ })).toBeNull();
    expect(within(mainCard).getByRole("button", { name: "Изменить" })).toBeInTheDocument();

    await user.click(
      within(mainCard).getByRole("button", { name: /Почему нет прогноза даты для цели/ }),
    );
    expect(
      screen.getByText(/Недостаточно данных, чтобы надёжно спрогнозировать будущую дату/),
    ).toBeInTheDocument();
    expect(screen.queryByText("no_trajectory_model")).toBeNull();

    const archiveLabel = screen.getByText("Архив");
    const archive = archiveLabel.closest("details");
    if (!archive) throw new Error("expected goals archive");
    expect(archive).not.toHaveAttribute("open");
    await user.click(archiveLabel);
    expect(archive).toHaveAttribute("open");
    expect(within(archive).getByRole("heading", { name: "Капитал потом" })).toBeInTheDocument();

    expect(listGoalSummaryMock).toHaveBeenCalledWith(
      11,
      { includeInactive: true },
      expect.anything(),
    );
  });

  it("creates a goal with exact normalized money and the canonical calculation mode", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByRole("heading", { level: 3, name: "Пассивный доход" });
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

  it("moves make-main and lifecycle actions into the overflow menu", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByRole("heading", { level: 3, name: "Запасная цель" });
    const card = cardFor("Запасная цель");

    expect(within(card).queryByRole("button", { name: "Сделать основной" })).toBeNull();
    await user.click(within(card).getByRole("button", { name: "Действия для цели «Запасная цель»" }));
    await user.click(within(card).getByRole("menuitem", { name: "Сделать основной" }));

    await waitFor(() => expect(updateGoalMock).toHaveBeenCalledWith(2, { is_main: true }));
  });

  it("keeps edit visible and destructive actions unavailable for the main goal", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByRole("heading", { level: 3, name: "Пассивный доход" });
    const mainCard = cardFor("Пассивный доход");
    expect(within(mainCard).getByRole("button", { name: "Изменить" })).toBeInTheDocument();
    expect(within(mainCard).queryByRole("button", { name: /Действия для цели/ })).toBeNull();

    const secondCard = cardFor("Запасная цель");
    await user.click(within(secondCard).getByRole("button", { name: "Изменить" }));
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

    const refreshedCard = cardFor("Запасная цель");
    await user.click(
      within(refreshedCard).getByRole("button", { name: "Действия для цели «Запасная цель»" }),
    );
    await user.click(within(refreshedCard).getByRole("menuitem", { name: "Удалить" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Удалить" }),
    );
    await waitFor(() => expect(deleteGoalMock).toHaveBeenCalledWith(2));
  });

  it("can reactivate an archived goal from its overflow menu", async () => {
    const user = userEvent.setup();
    render(<GoalsPage />);

    await screen.findByRole("heading", { level: 3, name: "Пассивный доход" });
    const archiveLabel = screen.getByText("Архив");
    await user.click(archiveLabel);

    const archivedCard = cardFor("Капитал потом");
    await user.click(
      within(archivedCard).getByRole("button", { name: "Действия для цели «Капитал потом»" }),
    );
    await user.click(within(archivedCard).getByRole("menuitem", { name: "Активировать" }));

    await waitFor(() => expect(updateGoalMock).toHaveBeenCalledWith(3, { is_active: true }));
  });
});
