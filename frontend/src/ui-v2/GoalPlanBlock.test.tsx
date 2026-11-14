import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getGoalPlan, type Goal, type GoalPlan } from "../api/goals";
import { GoalPlanBlock } from "./GoalPlanBlock";

vi.mock("../api/goals", () => ({ getGoalPlan: vi.fn() }));
vi.mock("./GoalPlanChart", () => ({ GoalPlanChart: () => <figure aria-label="Траектория" /> }));

const goal: Goal = {
  id: 9,
  name: "Synthetic goal",
  goal_type: "capital",
  calculation_mode: "liquid_capital_net",
  target_value: { amount: "1500000.00", currency: "RUB" },
  target_date: "2032-12-31",
  is_active: true,
  is_main: false,
  notes: null,
};
const base: GoalPlan = {
  method_version: "goal_plan_v1",
  status: "contribution_missing",
  as_of_date: "2032-01-31",
  base_capital: "1000000.00",
  coverage: "complete",
  components: { liquid_assets: "1200000.00", included_debts: "200000.00" },
  deadline_status: "available",
  required_contribution: "45000.00",
  contribution_difference: null,
  achievement_date: null,
  trajectory: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getGoalPlan).mockResolvedValue(base);
});

describe("goal plan presentation", () => {
  it("opens by default, preserves blank versus zero and sends exact Russian money and dates", async () => {
    const user = userEvent.setup();
    render(<GoalPlanBlock goal={goal} monthId={1} />);
    await screen.findByText("Введите взнос в месяц (0 — без взносов).");
    expect(screen.getByText("План достижения").parentElement).toHaveAttribute("open");
    expect(vi.mocked(getGoalPlan).mock.calls[0][2]).not.toHaveProperty("monthly_contribution");
    await user.type(screen.getByLabelText("Взнос в месяц"), "0");
    await waitFor(() =>
      expect(getGoalPlan).toHaveBeenLastCalledWith(
        9,
        1,
        { annual_rate_pct: "0.00", monthly_contribution: "0.00" },
        expect.any(AbortSignal),
      ),
    );
    await user.clear(screen.getByLabelText("Взнос в месяц"));
    await user.type(screen.getByLabelText("Взнос в месяц"), "12 345,67");
    await user.type(screen.getByLabelText("Первый взнос"), "29.02.2032");
    await waitFor(() =>
      expect(getGoalPlan).toHaveBeenLastCalledWith(
        9,
        1,
        {
          annual_rate_pct: "0.00",
          monthly_contribution: "12345.67",
          first_contribution_date: "2032-02-29",
        },
        expect.any(AbortSignal),
      ),
    );
    const count = vi.mocked(getGoalPlan).mock.calls.length;
    await user.clear(screen.getByLabelText("Первый взнос"));
    await user.type(screen.getByLabelText("Первый взнос"), "31.02.2032");
    expect(screen.getByRole("alert")).toHaveTextContent("ДД.ММ.ГГГГ");
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(getGoalPlan).toHaveBeenCalledTimes(count);
  });

  it.each([
    ["achieved", "available", "Цель уже достигнута по базе."],
    ["projected", "passed", "Срок цели прошёл."],
    ["not_reached", "available", "При этих условиях цель не достигается за 100 лет."],
  ])("shows a short state for %s / %s", async (status, deadline_status, text) => {
    vi.mocked(getGoalPlan).mockResolvedValue({ ...base, status, deadline_status });
    render(<GoalPlanBlock goal={goal} monthId={1} />);
    await screen.findByText(text);
    expect(screen.queryByText("Достигнете")).not.toBeInTheDocument();
    expect(screen.queryByText("Нужно в месяц к сроку")).not.toBeInTheDocument();
  });

  it("shows backend required payments and negative difference without changing them", async () => {
    vi.mocked(getGoalPlan).mockResolvedValue({
      ...base,
      status: "projected",
      achievement_date: "2032-06-01",
      contribution_difference: "-12000.00",
    });
    const user = userEvent.setup();
    render(<GoalPlanBlock goal={goal} monthId={1} />);
    await user.type(screen.getByLabelText("Взнос в месяц"), "33000");
    await screen.findByText("не хватает 12 000 ₽ в месяц");
    expect(screen.getByText("июнь 2032")).toBeVisible();
    expect(screen.getByText("45 000 ₽")).toBeVisible();
  });

  it("omits the required payment without a deadline", async () => {
    vi.mocked(getGoalPlan).mockResolvedValue({
      ...base,
      status: "projected",
      achievement_date: "2032-06-01",
      deadline_status: "absent",
      required_contribution: null,
    });
    render(<GoalPlanBlock goal={{ ...goal, target_date: null }} monthId={1} />);
    await screen.findByText("Срок цели не задан.");
    expect(screen.queryByText("Нужно в месяц к сроку")).not.toBeInTheDocument();
  });

  it("shows approximate capital with actual yield and incomplete history once", async () => {
    vi.mocked(getGoalPlan).mockResolvedValue({
      ...base,
      status: "income_estimate",
      required_capital: "2000000.00",
      income_months_count: 7,
      income_months_complete: false,
    });
    render(
      <GoalPlanBlock
        goal={{ ...goal, goal_type: "passive_income" }}
        monthId={1}
        currentIncome="10000.00"
      />,
    );
    await screen.findByText("≈ 2 000 000 ₽");
    expect(screen.getByText("При текущей отдаче 12,0% в год, доход за 7 из 12 мес.")).toBeVisible();
    expect(screen.queryByText("База оценки")).not.toBeInTheDocument();
    expect(screen.getByText(/Отдача = фактический/)).not.toBeVisible();
  });
});
