import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { getDashboard } from "../api/dashboard";
import { listGoalSummary } from "../api/goals";
import { getCashTotal, listCashBalances } from "../api/cash";
import { listDeposits } from "../api/deposits";
import { listIncomes } from "../api/incomes";
import { closeMonth, getMonth, reopenMonth, updateMonth } from "../api/months";
import { getMonthSummary } from "../api/summary";
import type { ReportingMonth } from "../api/types";
import { MonthDetailPage } from "./MonthDetailPage";

vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/goals", () => ({ listGoalSummary: vi.fn() }));
vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/cash", () => ({
  getCashTotal: vi.fn(),
  listCashBalances: vi.fn(),
}));
vi.mock("../api/deposits", () => ({ listDeposits: vi.fn() }));
vi.mock("../api/incomes", () => ({ listIncomes: vi.fn() }));
vi.mock("../api/months", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/months")>();
  return {
    ...actual,
    closeMonth: vi.fn(),
    getMonth: vi.fn(),
    reopenMonth: vi.fn(),
    updateMonth: vi.fn(),
  };
});
vi.mock("../api/summary", () => ({ getMonthSummary: vi.fn() }));

vi.mock("../components/MonthAssetsSection", async (importOriginal) => importOriginal());
vi.mock("../components/MonthBudgetSection", () => ({
  MonthBudgetSection: () => <div>budget stub</div>,
}));
vi.mock("../components/MonthNoteSection", () => ({
  MonthNoteSection: () => <div>note stub</div>,
}));

vi.mock("../components/MonthFlowsSection", () => ({
  MonthFlowsSection: () => <div>flows stub</div>,
}));
vi.mock("../components/MonthLiabilitiesSection", () => ({
  MonthLiabilitiesSection: () => <div>liabilities stub</div>,
}));
vi.mock("../components/MonthPositionsSection", () => ({
  MonthPositionsSection: () => <div>positions stub</div>,
}));
vi.mock("../components/SalaryTaxRateSummary", () => ({
  SalaryTaxRateSummary: () => <div>tax rates stub</div>,
}));

const draftMonth: ReportingMonth = {
  id: 1,
  year: 2031,
  month: 2,
  status: "draft",
  snapshot_date: "2031-02-28",
  source: "manual",
};

const closedMonth: ReportingMonth = { ...draftMonth, status: "closed" };
const nextMonth: ReportingMonth = { ...draftMonth, id: 2, month: 3 };

const getMonthMock = vi.mocked(getMonth);
const listIncomesMock = vi.mocked(listIncomes);
const listAccountsMock = vi.mocked(listAccounts);
const listCashBalancesMock = vi.mocked(listCashBalances);
const getCashTotalMock = vi.mocked(getCashTotal);
const listDepositsMock = vi.mocked(listDeposits);
const getMonthSummaryMock = vi.mocked(getMonthSummary);
const getDashboardMock = vi.mocked(getDashboard);
const listGoalSummaryMock = vi.mocked(listGoalSummary);
const updateMonthMock = vi.mocked(updateMonth);
const closeMonthMock = vi.mocked(closeMonth);
const reopenMonthMock = vi.mocked(reopenMonth);

function MonthRouteHarness() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate("/months/2?section=income")} type="button">
        Перейти в следующий месяц
      </button>
      <MonthDetailPage />
    </>
  );
}

function renderPage(entry = "/months/1", withMonthSwitcher = false) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          element={withMonthSwitcher ? <MonthRouteHarness /> : <MonthDetailPage />}
          path="/months/:monthId"
        />
        <Route element={<div>months list</div>} path="/months" />
      </Routes>
    </MemoryRouter>,
  );
}

function mockLoadedMonth(month: ReportingMonth = draftMonth) {
  getMonthMock.mockResolvedValue(month);
  listIncomesMock.mockResolvedValue([]);
  getMonthSummaryMock.mockResolvedValue({
    month: {
      id: month.id,
      year: month.year,
      month: month.month,
      status: month.status,
      snapshot_date: month.snapshot_date,
      source: month.source,
    },
    salary_tax: {
      tax: { amount: "13000.00", currency: "RUB" },
      calculated_net: { amount: "87000.00", currency: "RUB" },
    },
    salary_actual_net: { amount: "0.00", currency: "RUB" },
  });
  getDashboardMock.mockResolvedValue({
    month,
    kpis: {
      liquid_capital_net: { amount: "1500000.00", currency: "RUB" },
      liquid_capital_delta: { amount: "10000.00", currency: "RUB" },
      forecast_monthly_passive_income: { amount: "50000.00", currency: "RUB" },
      passive_income_average: { amount: "45000.00", currency: "RUB" },
      passive_income_average_months: 6,
      passive_income_average_complete: false,
      goal_progress_pct: "45.0",
      goal_target: { amount: "100000.00", currency: "RUB" },
      mandatory_expenses: { amount: "90000.00", currency: "RUB" },
      mandatory_expense_coverage_pct: "50.0",
      mortgage_balance: { amount: "3000000.00", currency: "RUB" },
      mortgage_coverage_pct: "50.0",
    },
    mortgage: {
      mortgage_balance: { amount: "3000000.00", currency: "RUB" },
      coverage_pct: "50.0",
      gap: { amount: "1500000.00", currency: "RUB" },
    },
    warnings: ["Проверь данные"],
  });
  listGoalSummaryMock.mockResolvedValue([]);
}

describe("MonthDetailPage R03-06 workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLoadedMonth();
    listAccountsMock.mockResolvedValue([]);
    listCashBalancesMock.mockResolvedValue([]);
    getCashTotalMock.mockResolvedValue({
      reporting_month_id: 1,
      total: { amount: "0.00", currency: "RUB" },
      total_in_capital: { amount: "0.00", currency: "RUB" },
    });
    listDepositsMock.mockResolvedValue([]);
    updateMonthMock.mockResolvedValue(draftMonth);
    closeMonthMock.mockResolvedValue(closedMonth);
    reopenMonthMock.mockResolvedValue(draftMonth);
  });

  it("opens a section directly from the URL and keeps one section visible", async () => {
    renderPage("/months/1?section=assets");

    expect(await screen.findByLabelText("Название вклада")).toBeVisible();
    expect(screen.getByRole("button", { name: "Активы" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Раздел: Активы")).toBeInTheDocument();
    expect(screen.queryByText("positions stub")).toBeNull();
    expect(screen.getByLabelText("Период")).not.toBeVisible();
  });

  it("presents calculated salary values as read-only summary data", async () => {
    renderPage("/months/1?section=income");

    const summary = await screen.findByLabelText("Расчёт зарплаты");
    expect(within(summary).getByText("Расчётный налог")).toBeInTheDocument();
    expect(within(summary).getByText("Расчётный net")).toBeInTheDocument();
    expect(within(summary).queryByRole("textbox")).toBeNull();
    expect(screen.queryByText("Расчётный налог (backend)")).toBeNull();
  });

  it("preserves unsaved form state across section navigation without silent save", async () => {
    const user = userEvent.setup();
    renderPage("/months/1?section=income");

    const salary = await screen.findByLabelText("Зарплата до вычета налогов");
    await user.type(salary, "100000");
    expect(screen.getByText("Не сохранено")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Активы" }));
    expect(screen.getByLabelText("Название вклада")).toBeVisible();
    expect(updateMonthMock).not.toHaveBeenCalled();
    expect(closeMonthMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /^Доходы$/ }));
    expect(screen.getByLabelText("Зарплата до вычета налогов")).toHaveValue("100000");

    const beforeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
  });

  it("preserves an unfinished assets draft across section navigation without saving", async () => {
    const user = userEvent.setup();
    renderPage("/months/1?section=assets");

    const depositName = await screen.findByLabelText("Название вклада");
    await user.type(depositName, "Черновой вклад");

    await user.click(screen.getByRole("button", { name: /^Доходы$/ }));
    await user.click(screen.getByRole("button", { name: "Активы" }));

    expect(await screen.findByLabelText("Название вклада")).toHaveValue("Черновой вклад");
    expect(updateMonthMock).not.toHaveBeenCalled();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("uses review as an explicit step before closing and never closes dirty data", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { level: 1, name: /Февраль\s+2031/ });
    await user.click(screen.getByRole("button", { name: "Проверить и закрыть" }));
    expect(screen.getByRole("heading", { level: 2, name: "Проверка месяца" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Проверка" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await user.click(screen.getByRole("button", { name: /^Доходы$/ }));
    await user.type(screen.getByLabelText("Зарплата до вычета налогов"), "100000");
    await user.click(screen.getByRole("button", { name: "Проверка" }));
    expect(screen.getByRole("heading", { level: 2, name: "Проверка месяца" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("runs save, review, close, and reopen in the month workspace", async () => {
    const user = userEvent.setup();
    getMonthMock
      .mockResolvedValueOnce(draftMonth)
      .mockResolvedValueOnce(draftMonth)
      .mockResolvedValueOnce(closedMonth)
      .mockResolvedValueOnce(draftMonth);
    renderPage();

    const snapshot = await screen.findByLabelText("Дата снимка");
    await user.clear(snapshot);
    await user.type(snapshot, "2031-03-01");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(updateMonthMock).toHaveBeenCalledWith(1, { snapshot_date: "2031-03-01" }),
    );

    await user.click(screen.getByRole("button", { name: "Проверить и закрыть" }));
    await user.click(screen.getByRole("button", { name: "Закрыть месяц" }));
    const closeDialog = screen.getByRole("alertdialog");
    await user.click(within(closeDialog).getByRole("button", { name: "Закрыть" }));
    await waitFor(() => expect(closeMonthMock).toHaveBeenCalledWith(1));
    expect(await screen.findByText("Закрыт")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Открыть заново" }));
    const reopenDialog = screen.getByRole("alertdialog");
    await user.click(within(reopenDialog).getByRole("button", { name: "Открыть заново" }));
    await waitFor(() => expect(reopenMonthMock).toHaveBeenCalledWith(1));
  });

  it("scopes visited asset state to the current month route", async () => {
    const user = userEvent.setup();
    getMonthMock.mockImplementation(async (monthId) => (monthId === 1 ? draftMonth : nextMonth));
    renderPage("/months/1?section=assets", true);

    const monthADraft = await screen.findByLabelText("Название вклада");
    await user.type(monthADraft, "Черновой вклад");
    await user.click(screen.getByRole("button", { name: "Перейти в следующий месяц" }));

    await screen.findByRole("heading", { level: 1, name: /Март\s+2031/ });
    expect(screen.queryByLabelText("Название вклада")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Активы" }));
    expect(await screen.findByLabelText("Название вклада")).toHaveValue("");
    await user.type(screen.getByLabelText("Название вклада"), "Новый месяц");
    await user.click(screen.getByRole("button", { name: /^Доходы$/ }));
    await user.click(screen.getByRole("button", { name: "Активы" }));
    expect(await screen.findByLabelText("Название вклада")).toHaveValue("Новый месяц");
    expect(updateMonthMock).not.toHaveBeenCalled();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("offers reopen from the sticky header for a closed month without the old lock warning", async () => {
    const user = userEvent.setup();
    mockLoadedMonth(closedMonth);
    getMonthMock.mockResolvedValueOnce(closedMonth).mockResolvedValue(draftMonth);
    renderPage();

    const reopen = await screen.findByRole("button", { name: "Открыть для редактирования" });
    expect(screen.queryByText(/Месяц утверждён — редактирование заблокировано/)).toBeNull();

    await user.click(reopen);
    await user.click(screen.getByRole("button", { name: "Открыть" }));

    await waitFor(() => expect(reopenMonthMock).toHaveBeenCalledWith(1));
  });
});
