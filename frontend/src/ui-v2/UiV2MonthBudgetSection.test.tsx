import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createExpense, deleteExpense, listExpenses, updateExpense } from "../api/expenses";
import {
  createPlannedBudget,
  deletePlannedBudget,
  listPlannedBudget,
  plannedVsActual,
  updatePlannedBudget,
} from "../api/plannedBudget";
import { createSaving, deleteSaving, listSavings, updateSaving } from "../api/savings";
import type { ReportingMonth } from "../api/types";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { MONTH_BUDGET_SECTION_ID, UiV2MonthBudgetSection } from "./UiV2MonthBudgetSection";

vi.mock("../api/expenses", () => ({
  listExpenses: vi.fn(),
  createExpense: vi.fn(),
  updateExpense: vi.fn(),
  deleteExpense: vi.fn(),
}));
vi.mock("../api/plannedBudget", () => ({
  listPlannedBudget: vi.fn(),
  plannedVsActual: vi.fn(),
  createPlannedBudget: vi.fn(),
  updatePlannedBudget: vi.fn(),
  deletePlannedBudget: vi.fn(),
}));
vi.mock("../api/savings", () => ({
  listSavings: vi.fn(),
  createSaving: vi.fn(),
  updateSaving: vi.fn(),
  deleteSaving: vi.fn(),
}));

const draftMonth: ReportingMonth = {
  id: 7,
  year: 2030,
  month: 4,
  status: "draft",
  snapshot_date: "2030-04-30",
  source: "manual",
};

function contextWith(overrides: Partial<MonthEditorContext> = {}): MonthEditorContext {
  return {
    month: { ...draftMonth },
    readOnly: false,
    refresh: vi.fn(async () => ({ ...draftMonth })),
    setDirty: vi.fn(),
    returnToClose: null,
    ...overrides,
  };
}

function renderLeaf(context: MonthEditorContext) {
  return render(<UiV2MonthBudgetSection context={context} />);
}

const expenseFoodMandatory = {
  id: 11,
  reporting_month_id: 7,
  category: "Еда",
  amount: { amount: "50000.00", currency: "RUB" },
  expense_type: "mandatory",
  is_recurring: false,
  notes: null,
};

const expenseFoodComfort = {
  id: 12,
  reporting_month_id: 7,
  category: "Еда",
  amount: { amount: "7000.00", currency: "RUB" },
  expense_type: "comfortable",
  is_recurring: false,
  notes: null,
};

const savingRow = {
  id: 21,
  reporting_month_id: 7,
  destination: "Подушка",
  amount: { amount: "20000.00", currency: "RUB" },
  notes: null,
};

const planRow = {
  id: 31,
  reporting_month_id: 7,
  category: "Еда",
  planned_amount: { amount: "48000.00", currency: "RUB" },
  expense_type: "mandatory",
  notes: null,
};

beforeEach(() => {
  vi.mocked(listExpenses).mockReset().mockResolvedValue([]);
  vi.mocked(listSavings).mockReset().mockResolvedValue([]);
  vi.mocked(listPlannedBudget).mockReset().mockResolvedValue([]);
  vi.mocked(plannedVsActual).mockReset().mockResolvedValue([]);
  vi.mocked(createExpense).mockReset();
  vi.mocked(updateExpense).mockReset();
  vi.mocked(deleteExpense).mockReset().mockResolvedValue(undefined);
  vi.mocked(createSaving).mockReset();
  vi.mocked(updateSaving).mockReset();
  vi.mocked(deleteSaving).mockReset().mockResolvedValue(undefined);
  vi.mocked(createPlannedBudget).mockReset();
  vi.mocked(updatePlannedBudget).mockReset();
  vi.mocked(deletePlannedBudget).mockReset().mockResolvedValue(undefined);
});

describe("UiV2MonthBudgetSection plan/fact matrix", () => {
  it("renders plan-only with an explicit fact gap", async () => {
    vi.mocked(listPlannedBudget).mockResolvedValue([planRow]);
    vi.mocked(plannedVsActual).mockResolvedValue([
      {
        category: "Еда",
        expense_type: "mandatory",
        planned: { amount: "48000.00", currency: "RUB" },
        actual: null,
      },
    ]);
    renderLeaf(contextWith());
    const expenseSection = await screen.findByRole("region", { name: "Расходы месяца" });
    const row = within(expenseSection).getByText("Еда").closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[1].textContent).toBe("—");
    expect(cells[2].textContent).toMatch(/48\s*000/);
    expect(within(expenseSection).getAllByRole("table")).toHaveLength(1);
  });

  it("renders fact-only with a missing plan gap instead of zero", async () => {
    vi.mocked(listExpenses).mockResolvedValue([expenseFoodMandatory]);
    vi.mocked(plannedVsActual).mockResolvedValue([
      {
        category: "Такси",
        expense_type: "mandatory",
        planned: null,
        actual: { amount: "12000.00", currency: "RUB" },
      },
    ]);
    renderLeaf(contextWith());
    const planSection = await screen.findByRole("region", { name: "План бюджета месяца" });
    expect(within(planSection).queryByRole("table")).not.toBeInTheDocument();
    const expenses = screen.getByRole("region", { name: "Расходы месяца" });
    expect(within(expenses).getByText(expenseFoodMandatory.category)).toBeInTheDocument();
  });

  it("renders plan+fact and keeps explicit zero distinct from missing", async () => {
    vi.mocked(listPlannedBudget).mockResolvedValue([planRow]);
    vi.mocked(plannedVsActual).mockResolvedValue([
      {
        category: "Еда",
        expense_type: "mandatory",
        planned: { amount: "48000.00", currency: "RUB" },
        actual: { amount: "50000.00", currency: "RUB" },
      },
      {
        category: "Подписки",
        expense_type: "other",
        planned: { amount: "0.00", currency: "RUB" },
        actual: null,
      },
      {
        category: "Такси",
        expense_type: "mandatory",
        planned: null,
        actual: { amount: "12000.00", currency: "RUB" },
      },
    ]);
    renderLeaf(contextWith());
    const section = await screen.findByRole("region", { name: "Расходы месяца" });
    expect(within(section).getAllByRole("table")).toHaveLength(2);
    const fullCells = within(
      within(section).getByText("Еда").closest("tr") as HTMLElement,
    ).getAllByRole("cell");
    expect(fullCells[1].textContent).toMatch(/50\s*000/);
    expect(fullCells[2].textContent).toMatch(/48\s*000/);
    const zeroCells = within(
      within(section).getByText("Подписки").closest("tr") as HTMLElement,
    ).getAllByRole("cell");
    expect(zeroCells[1].textContent).toBe("—");
    expect(zeroCells[2].textContent).toMatch(/^0\s*₽$/);
    const missingCells = within(
      within(section).getByText("Такси").closest("tr") as HTMLElement,
    ).getAllByRole("cell");
    expect(missingCells[1].textContent).toMatch(/12\s*000/);
    expect(missingCells[2].textContent).toBe("—");
  });

  it("groups repeated records without losing separate edit and delete actions", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue([
      { ...expenseFoodMandatory, notes: "Первая покупка" },
      {
        ...expenseFoodMandatory,
        id: 13,
        amount: { amount: "2000.00", currency: "RUB" },
        notes: "Вторая покупка",
      },
    ]);
    vi.mocked(listPlannedBudget).mockResolvedValue([
      { ...planRow, notes: "Основной план" },
      {
        ...planRow,
        id: 32,
        planned_amount: { amount: "0.00", currency: "RUB" },
        notes: "Дополнение",
      },
    ]);
    vi.mocked(plannedVsActual).mockResolvedValue([
      {
        category: "Еда",
        expense_type: "mandatory",
        actual: { amount: "52000.00", currency: "RUB" },
        planned: { amount: "48000.00", currency: "RUB" },
      },
    ]);
    renderLeaf(contextWith());
    const section = await screen.findByRole("region", { name: "Расходы месяца" });
    const table = within(section).getByRole("table");
    const cells = within(within(table).getByText("Еда").closest("tr") as HTMLElement).getAllByRole(
      "cell",
    );
    expect(cells[1]).toHaveTextContent(/52\s*000/);
    expect(cells[2]).toHaveTextContent(/48\s*000/);
    await user.click(within(cells[1]).getByText("Расходы: 2"));
    await user.click(within(cells[2]).getByText("План: 2"));
    expect(within(cells[1]).getByText(/Первая покупка/)).toBeVisible();
    expect(within(cells[1]).getByText(/Вторая покупка/)).toBeVisible();
    expect(within(cells[2]).getByText(/Основной план/)).toBeVisible();
    expect(within(cells[2]).getByText(/Дополнение/)).toBeVisible();
    expect(within(cells[1]).getAllByRole("button", { name: "Удалить" })).toHaveLength(2);
    expect(within(cells[2]).getAllByRole("button", { name: "Удалить" })).toHaveLength(2);
    await user.click(within(cells[2]).getAllByRole("button", { name: "Изменить" })[1]);
    expect(within(cells[2]).getByLabelText("Сумма плана")).toHaveValue("0.00");
  });

  it("keeps row identity by id when category repeats with different expense_type", async () => {
    vi.mocked(listExpenses).mockResolvedValue([expenseFoodMandatory, expenseFoodComfort]);
    renderLeaf(contextWith());
    const expenseSection = await screen.findByRole("region", { name: "Расходы месяца" });
    const rows = within(expenseSection).getAllByRole("row");
    const bodyRows = rows.filter((row) => within(row).queryAllByRole("cell").length > 0);
    expect(bodyRows).toHaveLength(2);
    expect(bodyRows[0].closest("section")).toHaveAccessibleName("Обязательные");
    expect(bodyRows[1].closest("section")).toHaveAccessibleName("Крупные и прочие");
  });

  it("supports savings create with exact money and readback", async () => {
    const user = userEvent.setup();
    vi.mocked(listSavings).mockResolvedValue([{ ...savingRow }]);
    vi.mocked(createSaving).mockResolvedValue({ ...savingRow });
    const context = contextWith();
    renderLeaf(context);

    await screen.findByRole("region", { name: "Накопления месяца" });
    await user.type(screen.getByLabelText("Направление накопления"), "Подушка");
    await user.type(screen.getByLabelText("Сумма накопления"), "20000");
    await user.click(screen.getByRole("button", { name: "Добавить накопление" }));

    await waitFor(() => expect(createSaving).toHaveBeenCalledTimes(1));
    expect(createSaving).toHaveBeenCalledWith({
      reporting_month_id: 7,
      destination: "Подушка",
      amount: { amount: "20000.00", currency: "RUB" },
      notes: null,
    });
    expect(listSavings).toHaveBeenCalledTimes(2);
    expect(context.refresh).toHaveBeenCalled();
    expect(await screen.findByText("Накопление сохранено и подтверждено.")).toBeInTheDocument();
  });
});

describe("UiV2MonthBudgetSection mutations and guards", () => {
  it("creates an expense with the canonical exact-money contract", async () => {
    const user = userEvent.setup();
    vi.mocked(createExpense).mockResolvedValue({ ...expenseFoodMandatory });
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    await waitFor(() => expect(createExpense).toHaveBeenCalledTimes(1));
    expect(createExpense).toHaveBeenCalledWith({
      reporting_month_id: 7,
      category: "Еда",
      amount: { amount: "50000.00", currency: "RUB" },
      expense_type: "mandatory",
      notes: null,
    });
  });

  it("keeps the draft visible when save fails", async () => {
    const user = userEvent.setup();
    vi.mocked(createExpense).mockRejectedValue(new Error("save failed"));
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    expect(await screen.findByText("save failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Категория расхода")).toHaveValue("Еда");
  });

  it("blocks a second submit while the first request is in flight", async () => {
    const user = userEvent.setup();
    let release!: (value: typeof expenseFoodMandatory) => void;
    vi.mocked(listExpenses).mockResolvedValue([{ ...expenseFoodMandatory }]);
    vi.mocked(createExpense).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    expect(createExpense).toHaveBeenCalledTimes(1);
    release({ ...expenseFoodMandatory });
    await waitFor(() =>
      expect(screen.getByText("Расход сохранён и подтверждён.")).toBeInTheDocument(),
    );
  });

  it("deletes a saving only after confirmation and rereads", async () => {
    const user = userEvent.setup();
    vi.mocked(listSavings)
      .mockResolvedValueOnce([{ ...savingRow }])
      .mockResolvedValue([]);
    renderLeaf(contextWith());

    const savingSection = await screen.findByRole("region", { name: "Накопления месяца" });
    await user.click(within(savingSection).getByRole("button", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить накопление?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(deleteSaving).toHaveBeenCalledWith(21));
    expect(await screen.findByText("Запись удалена и подтверждена.")).toBeInTheDocument();
    expect(
      screen.queryByRole("alertdialog", { name: "Удалить накопление?" }),
    ).not.toBeInTheDocument();
    expect(listSavings).toHaveBeenCalledTimes(2);
  });

  it("reports dirty state for an open draft and clears it after save", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue([{ ...expenseFoodMandatory }]);
    vi.mocked(createExpense).mockResolvedValue({ ...expenseFoodMandatory });
    const context = contextWith();
    renderLeaf(context);

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    expect(context.setDirty).toHaveBeenLastCalledWith(MONTH_BUDGET_SECTION_ID, true);

    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    await screen.findByText("Расход сохранён и подтверждён.");
    await waitFor(() =>
      expect(context.setDirty).toHaveBeenLastCalledWith(MONTH_BUDGET_SECTION_ID, false),
    );
  });

  it("disables mutations in a CLOSED month", async () => {
    vi.mocked(listExpenses).mockResolvedValue([expenseFoodMandatory]);
    vi.mocked(listSavings).mockResolvedValue([
      { ...savingRow, amount: { amount: "0.00", currency: "RUB" } },
    ]);
    const closed: ReportingMonth = { ...draftMonth, status: "closed" };
    renderLeaf(contextWith({ month: closed, readOnly: true }));

    const expenseSection = await screen.findByRole("region", { name: "Расходы месяца" });
    expect(
      within(expenseSection).queryByRole("button", { name: "Изменить" }),
    ).not.toBeInTheDocument();
    expect(
      within(expenseSection).queryByRole("button", { name: "Удалить" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Добавить расход" })).not.toBeInTheDocument();
    expect(
      within(expenseSection).queryByRole("columnheader", { name: "Комментарий" }),
    ).not.toBeInTheDocument();
    expect(
      within(expenseSection).queryByRole("columnheader", { name: "Тип" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Накопления месяца" })).not.toBeInTheDocument();
  });

  it("ignores a late save response after the month identity changes", async () => {
    const user = userEvent.setup();
    let release!: (value: typeof expenseFoodMandatory) => void;
    vi.mocked(createExpense).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const context = contextWith();
    const view = renderLeaf(context);

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    view.rerender(
      <UiV2MonthBudgetSection context={{ ...context, month: { ...draftMonth, id: 8 } }} />,
    );
    release({ ...expenseFoodMandatory });
    await waitFor(() => expect(createExpense).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Расход сохранён и подтверждён.")).not.toBeInTheDocument();
  });
});

describe("UiV2MonthBudgetSection readback confirmation", () => {
  it("fails an expense create when readback lacks the created id and keeps the draft", async () => {
    const user = userEvent.setup();
    vi.mocked(createExpense).mockResolvedValue({ ...expenseFoodMandatory, id: 99 });
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    expect(await screen.findByText(/отсутствует в перечитанных данных/)).toBeInTheDocument();
    expect(screen.queryByText("Расход сохранён и подтверждён.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Категория расхода")).toHaveValue("Еда");
    expect(screen.getByLabelText("Сумма расхода")).toHaveValue("50000");
  });

  it("fails a plan create when readback lacks the created id and keeps the draft", async () => {
    const user = userEvent.setup();
    vi.mocked(createPlannedBudget).mockResolvedValue({ ...planRow, id: 98 });
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "План бюджета месяца" });
    await user.type(screen.getByLabelText("Категория плана"), "Еда");
    await user.type(screen.getByLabelText("Сумма плана"), "48000");
    await user.click(screen.getByRole("button", { name: "Добавить в план" }));

    expect(await screen.findByText(/отсутствует в перечитанных данных/)).toBeInTheDocument();
    expect(screen.queryByText("План сохранён и подтверждён.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Категория плана")).toHaveValue("Еда");
  });

  it("fails a saving create when readback lacks the created id and keeps the draft", async () => {
    const user = userEvent.setup();
    vi.mocked(createSaving).mockResolvedValue({ ...savingRow, id: 97 });
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Накопления месяца" });
    await user.type(screen.getByLabelText("Направление накопления"), "Подушка");
    await user.type(screen.getByLabelText("Сумма накопления"), "20000");
    await user.click(screen.getByRole("button", { name: "Добавить накопление" }));

    expect(await screen.findByText(/отсутствует в перечитанных данных/)).toBeInTheDocument();
    expect(screen.queryByText("Накопление сохранено и подтверждено.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Направление накопления")).toHaveValue("Подушка");
  });

  it("fails an expense update when readback still shows old values and keeps the edit", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue([{ ...expenseFoodMandatory }]);
    vi.mocked(updateExpense).mockResolvedValue({
      ...expenseFoodMandatory,
      amount: { amount: "51000.00", currency: "RUB" },
    });
    renderLeaf(contextWith());

    const expenseSection = await screen.findByRole("region", { name: "Расходы месяца" });
    await user.click(within(expenseSection).getByRole("button", { name: "Изменить" }));
    const editingRow = screen.getByDisplayValue("Еда").closest("tr") as HTMLElement;
    const amount = within(editingRow).getByLabelText("Сумма расхода");
    await user.clear(amount);
    await user.type(amount, "51000");
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(await screen.findByText(/не отражает запрошенные изменения/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
    expect(within(editingRow).getByLabelText("Сумма расхода")).toHaveValue("51000");
  });

  it("fails a plan update when readback still shows old values and keeps the edit", async () => {
    const user = userEvent.setup();
    vi.mocked(listPlannedBudget).mockResolvedValue([{ ...planRow }]);
    vi.mocked(updatePlannedBudget).mockResolvedValue({
      ...planRow,
      planned_amount: { amount: "49000.00", currency: "RUB" },
    });
    renderLeaf(contextWith());

    const section = await screen.findByRole("region", { name: "Расходы месяца" });
    await user.click(within(section).getByText("План: 1"));
    await user.click(within(section).getByRole("button", { name: "Изменить" }));
    const editingRow = screen.getByDisplayValue("Еда").closest("tr") as HTMLElement;
    const amount = within(editingRow).getByLabelText("Сумма плана");
    await user.clear(amount);
    await user.type(amount, "49000");
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(await screen.findByText(/не отражает запрошенные изменения/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
    expect(within(editingRow).getByLabelText("Сумма плана")).toHaveValue("49000");
  });

  it("fails a saving update when readback still shows old values and keeps the edit", async () => {
    const user = userEvent.setup();
    vi.mocked(listSavings).mockResolvedValue([{ ...savingRow }]);
    vi.mocked(updateSaving).mockResolvedValue({
      ...savingRow,
      amount: { amount: "21000.00", currency: "RUB" },
    });
    renderLeaf(contextWith());

    const savingSection = await screen.findByRole("region", { name: "Накопления месяца" });
    await user.click(within(savingSection).getByRole("button", { name: "Изменить" }));
    const editingRow = screen.getByDisplayValue("Подушка").closest("tr") as HTMLElement;
    const amount = within(editingRow).getByLabelText("Сумма накопления");
    await user.clear(amount);
    await user.type(amount, "21000");
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(await screen.findByText(/не отражает запрошенные изменения/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OK" })).toBeInTheDocument();
    expect(within(editingRow).getByLabelText("Сумма накопления")).toHaveValue("21000");
  });

  it("fails an expense delete when readback still contains the row and keeps the dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(listExpenses).mockResolvedValue([{ ...expenseFoodMandatory }]);
    renderLeaf(contextWith());

    const expenseSection = await screen.findByRole("region", { name: "Расходы месяца" });
    await user.click(within(expenseSection).getByRole("button", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить расход?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    expect(await screen.findByText(/Удаление не подтверждено/)).toBeInTheDocument();
    expect(screen.getByRole("alertdialog", { name: "Удалить расход?" })).toBeInTheDocument();
    expect(deleteExpense).toHaveBeenCalledWith(11);
  });

  it("fails a saving delete when readback still contains the row and keeps the dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(listSavings).mockResolvedValue([{ ...savingRow }]);
    renderLeaf(contextWith());

    const savingSection = await screen.findByRole("region", { name: "Накопления месяца" });
    await user.click(within(savingSection).getByRole("button", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить накопление?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    expect(await screen.findByText(/Удаление не подтверждено/)).toBeInTheDocument();
    expect(screen.getByRole("alertdialog", { name: "Удалить накопление?" })).toBeInTheDocument();
    expect(deleteSaving).toHaveBeenCalledWith(21);
  });

  it("fails a plan delete when readback still contains the row and keeps the dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(listPlannedBudget).mockResolvedValue([{ ...planRow }]);
    renderLeaf(contextWith());

    const section = await screen.findByRole("region", { name: "Расходы месяца" });
    await user.click(within(section).getByText("План: 1"));
    await user.click(within(section).getByRole("button", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить план?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    expect(await screen.findByText(/Удаление не подтверждено/)).toBeInTheDocument();
    expect(screen.getByRole("alertdialog", { name: "Удалить план?" })).toBeInTheDocument();
    expect(deletePlannedBudget).toHaveBeenCalledWith(31);
  });

  it("fails a create when readback carries another month identity", async () => {
    const user = userEvent.setup();
    vi.mocked(createExpense).mockResolvedValue({ ...expenseFoodMandatory });
    vi.mocked(listExpenses)
      .mockResolvedValueOnce([])
      .mockResolvedValue([{ ...expenseFoodMandatory, reporting_month_id: 8 }]);
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    expect(await screen.findByText(/другого месяца/)).toBeInTheDocument();
    expect(screen.getByLabelText("Категория расхода")).toHaveValue("Еда");
  });

  it("keeps a newer draft typed during a deferred save", async () => {
    const user = userEvent.setup();
    let release!: (value: typeof expenseFoodMandatory) => void;
    vi.mocked(createExpense).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const created = { ...expenseFoodMandatory, id: 13 };
    vi.mocked(listExpenses).mockResolvedValueOnce([]).mockResolvedValue([created]);
    renderLeaf(contextWith());

    await screen.findByRole("region", { name: "Расходы месяца" });
    const category = screen.getByLabelText("Категория расхода");
    await user.type(category, "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    await user.type(category, "X");
    release(created);

    expect(await screen.findByText("Расход сохранён и подтверждён.")).toBeInTheDocument();
    expect(screen.getByLabelText("Категория расхода")).toHaveValue("ЕдаX");
  });

  it("reports a month lifecycle change explicitly instead of a routine success", async () => {
    const user = userEvent.setup();
    const closed: ReportingMonth = { ...draftMonth, status: "closed" };
    vi.mocked(createExpense).mockResolvedValue({ ...expenseFoodMandatory });
    vi.mocked(listExpenses).mockResolvedValue([{ ...expenseFoodMandatory }]);
    renderLeaf(contextWith({ refresh: vi.fn(async () => ({ ...closed })) }));

    await screen.findByRole("region", { name: "Расходы месяца" });
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));

    expect(await screen.findByText(/статус месяца изменился/)).toBeInTheDocument();
    expect(screen.queryByText("Расход сохранён и подтверждён.")).not.toBeInTheDocument();
  });
});
