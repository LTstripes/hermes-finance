import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { createExpense, deleteExpense, listExpenses, updateExpense } from "../api/expenses";
import {
  createPlannedBudget,
  deletePlannedBudget,
  listPlannedBudget,
  plannedVsActual,
  updatePlannedBudget,
} from "../api/plannedBudget";
import { createSaving, deleteSaving, listSavings, updateSaving } from "../api/savings";
import type {
  ExpenseEntry,
  PlannedBudgetLine,
  PlanVsActualRow,
  ReportingMonth,
  SavingAllocation,
} from "../api/types";
import { ConfirmDialog, OverflowMenu, OverflowMenuItem, Table, Td, Th } from "../components/ui";
import { formatMoney } from "../lib/format";
import { EXPENSE_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, toKopecks, sumMoneyAmounts } from "../lib/money";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { MonthMoneyInput } from "./MonthMoneyInput";
import styles from "./UiV2MonthEditor.module.css";

/** Leaf section id reserved for Integrator wiring (#563, after #558). */
import { MonthPanelTotal } from "./MonthPanelTotal";

export const MONTH_BUDGET_SECTION_ID = "budget";

type ExpenseExpectation = {
  category: string;
  expense_type: string;
  amount: string;
  notes: string;
};

type SavingExpectation = {
  destination: string;
  amount: string;
  notes: string;
};

type PlanExpectation = {
  category: string;
  expense_type: string;
  planned_amount: string;
  notes: string;
};

type BudgetSnapshot = {
  expenses: ExpenseEntry[];
  savings: SavingAllocation[];
  plan: PlannedBudgetLine[];
  comparison: PlanVsActualRow[];
};

function kindLabel(kind: "expense" | "saving" | "plan"): string {
  return kind === "expense" ? "Расход" : kind === "saving" ? "Накопление" : "План";
}

function expenseMatches(row: ExpenseEntry, expected: ExpenseExpectation): boolean {
  return (
    row.category === expected.category.trim() &&
    row.expense_type === expected.expense_type &&
    normalizeMoneyInput(moneyAmount(row.amount)) === normalizeMoneyInput(expected.amount) &&
    (row.notes ?? null) === (expected.notes.trim() || null)
  );
}

function savingMatches(row: SavingAllocation, expected: SavingExpectation): boolean {
  return (
    row.destination === expected.destination.trim() &&
    normalizeMoneyInput(moneyAmount(row.amount)) === normalizeMoneyInput(expected.amount) &&
    (row.notes ?? null) === (expected.notes.trim() || null)
  );
}

function planMatches(row: PlannedBudgetLine, expected: PlanExpectation): boolean {
  return (
    row.category === expected.category.trim() &&
    row.expense_type === expected.expense_type &&
    normalizeMoneyInput(moneyAmount(row.planned_amount)) ===
      normalizeMoneyInput(expected.planned_amount) &&
    (row.notes ?? null) === (expected.notes.trim() || null)
  );
}

function missingRowError(kind: "expense" | "saving" | "plan", id: number): Error {
  return new Error(
    `${kindLabel(kind)} #${id} отсутствует в перечитанных данных. Запись не подтверждена, черновик сохранён.`,
  );
}

function staleRowError(kind: "expense" | "saving" | "plan", id: number): Error {
  return new Error(
    `${kindLabel(kind)} #${id} в перечитанных данных не отражает запрошенные изменения. Правка не подтверждена.`,
  );
}

function deleteMissingError(kind: "expense" | "saving" | "plan", id: number): Error {
  return new Error(
    `${kindLabel(kind)} #${id} остался в перечитанных данных. Удаление не подтверждено.`,
  );
}

type ExpenseDraft = {
  category: string;
  expense_type: string;
  amount: string;
  notes: string;
};

type SavingDraft = {
  destination: string;
  amount: string;
  notes: string;
};

type PlanDraft = {
  category: string;
  expense_type: string;
  planned_amount: string;
  notes: string;
};

/**
 * V2P-09 leaf: budget, expenses and savings transferred from MonthBudgetSection.
 * Receives the exact-month MonthEditorContext, never selects another month.
 * Missing planned stays missing (rendered as em dash), explicit 0 stays 0.
 */
export function UiV2MonthBudgetSection({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, refresh, setDirty } = context;
  const monthId = month.id;

  const [expenses, setExpenses] = useState<ExpenseEntry[]>([]);
  const [savings, setSavings] = useState<SavingAllocation[]>([]);
  const [plan, setPlan] = useState<PlannedBudgetLine[]>([]);
  const [comparison, setComparison] = useState<PlanVsActualRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [expCategory, setExpCategory] = useState("");
  const [expAmount, setExpAmount] = useState("");
  const [expType, setExpType] = useState("mandatory");
  const [expNotes, setExpNotes] = useState("");
  const [savDest, setSavDest] = useState("");
  const [savAmount, setSavAmount] = useState("");
  const [savNotes, setSavNotes] = useState("");
  const [planCategory, setPlanCategory] = useState("");
  const [planAmount, setPlanAmount] = useState("");
  const [planType, setPlanType] = useState("mandatory");
  const [planNotes, setPlanNotes] = useState("");

  const [expenseDraftTouched, setExpenseDraftTouched] = useState(false);
  const [savingDraftTouched, setSavingDraftTouched] = useState(false);
  const [planDraftTouched, setPlanDraftTouched] = useState(false);

  const [delExpense, setDelExpense] = useState<ExpenseEntry | null>(null);
  const [delSaving, setDelSaving] = useState<SavingAllocation | null>(null);
  const [delPlan, setDelPlan] = useState<PlannedBudgetLine | null>(null);
  const expenseEditRef = useRef<HTMLInputElement>(null);
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [editExpense, setEditExpense] = useState<ExpenseDraft | null>(null);
  const savingEditRef = useRef<HTMLInputElement>(null);
  const [editingSavingId, setEditingSavingId] = useState<number | null>(null);
  const [editSaving, setEditSaving] = useState<SavingDraft | null>(null);
  const planEditRef = useRef<HTMLInputElement>(null);
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);
  const [editPlan, setEditPlan] = useState<PlanDraft | null>(null);

  useEffect(() => {
    if (editingExpenseId !== null) expenseEditRef.current?.focus();
  }, [editingExpenseId]);
  useEffect(() => {
    if (editingSavingId !== null) savingEditRef.current?.focus();
  }, [editingSavingId]);
  useEffect(() => {
    if (editingPlanId !== null) planEditRef.current?.focus();
  }, [editingPlanId]);
  const operation = useRef(0);

  const localDirty =
    expenseDraftTouched ||
    savingDraftTouched ||
    planDraftTouched ||
    editingExpenseId !== null ||
    editingSavingId !== null ||
    editingPlanId !== null;

  useEffect(() => {
    context.setPending?.(MONTH_BUDGET_SECTION_ID, busy);
    return () => context.setPending?.(MONTH_BUDGET_SECTION_ID, false);
  }, [context.setPending, busy]);
  useEffect(() => {
    setDirty(MONTH_BUDGET_SECTION_ID, localDirty);
  }, [localDirty, setDirty]);

  useEffect(
    () => () => {
      operation.current += 1;
      setDirty(MONTH_BUDGET_SECTION_ID, false);
    },
    [setDirty],
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const token = ++operation.current;
      const target = monthId;
      setLoading(true);
      setError(null);
      try {
        const [freshExpenses, freshSavings, freshPlan, freshComparison] = await Promise.all([
          listExpenses(target, signal),
          listSavings(target, signal),
          listPlannedBudget(target, signal),
          plannedVsActual(target, signal),
        ]);
        if (signal?.aborted || operation.current !== token) return;
        if (
          freshExpenses.some((row) => row.reporting_month_id !== target) ||
          freshSavings.some((row) => row.reporting_month_id !== target) ||
          freshPlan.some((row) => row.reporting_month_id !== target)
        ) {
          throw new Error("Получены записи другого месяца. Обновите раздел.");
        }
        setExpenses(freshExpenses);
        setSavings(freshSavings);
        setPlan(freshPlan);
        setComparison(freshComparison);
      } catch (cause) {
        if (signal?.aborted || operation.current !== token) return;
        setError(formatApiError(cause));
      } finally {
        if (!signal?.aborted && operation.current === token) setLoading(false);
      }
    },
    [monthId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const mandatoryTotal = useMemo(
    () =>
      sumMoneyAmounts(
        expenses
          .filter((row) => row.expense_type === "mandatory")
          .map((row) => moneyAmount(row.amount)),
      ),
    [expenses],
  );
  const otherExpenseTotal = useMemo(
    () =>
      sumMoneyAmounts(
        expenses
          .filter((row) => row.expense_type !== "mandatory")
          .map((row) => moneyAmount(row.amount)),
      ),
    [expenses],
  );
  const savingsTotal = useMemo(
    () => sumMoneyAmounts(savings.map((row) => moneyAmount(row.amount))),
    [savings],
  );
  const plannedTotal = useMemo(
    () => sumMoneyAmounts(plan.map((row) => moneyAmount(row.planned_amount))),
    [plan],
  );

  // Keep each record editable by id while the displayed totals come from the
  // existing plan/fact contract, which groups exact category/type pairs.
  const budgetGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        category: string;
        expenseType: string;
        actual: ExpenseEntry[];
        planned: PlannedBudgetLine[];
        comparison?: PlanVsActualRow;
      }
    >();
    function group(category: string, expenseType: string) {
      const key = JSON.stringify([category, expenseType]);
      let value = groups.get(key);
      if (!value) {
        value = { category, expenseType, actual: [], planned: [] };
        groups.set(key, value);
      }
      return value;
    }
    for (const row of expenses) group(row.category, row.expense_type).actual.push(row);
    for (const row of plan) group(row.category, row.expense_type).planned.push(row);
    for (const row of comparison) group(row.category, row.expense_type).comparison = row;
    return [...groups.values()];
  }, [expenses, plan, comparison]);

  function isStale(token: number, target: number): boolean {
    return operation.current !== token || month.id !== target;
  }

  const latestInputs = useRef({
    expCategory: "",
    expType: "mandatory",
    expAmount: "",
    expNotes: "",
    savDest: "",
    savAmount: "",
    savNotes: "",
    planCategory: "",
    planType: "mandatory",
    planAmount: "",
    planNotes: "",
    editExpense: null as ExpenseDraft | null,
    editSaving: null as SavingDraft | null,
    editPlan: null as PlanDraft | null,
  });

  useEffect(() => {
    latestInputs.current = {
      expCategory,
      expType,
      expAmount,
      expNotes,
      savDest,
      savAmount,
      savNotes,
      planCategory,
      planType,
      planAmount,
      planNotes,
      editExpense,
      editSaving,
      editPlan,
    };
  });

  async function refetchBudget(target: number): Promise<BudgetSnapshot> {
    const [freshExpenses, freshSavings, freshPlan, freshComparison] = await Promise.all([
      listExpenses(target),
      listSavings(target),
      listPlannedBudget(target),
      plannedVsActual(target),
    ]);
    if (
      freshExpenses.some((row) => row.reporting_month_id !== target) ||
      freshSavings.some((row) => row.reporting_month_id !== target) ||
      freshPlan.some((row) => row.reporting_month_id !== target)
    ) {
      throw new Error("Подтверждение вернуло записи другого месяца.");
    }
    return {
      expenses: freshExpenses,
      savings: freshSavings,
      plan: freshPlan,
      comparison: freshComparison,
    };
  }

  function installSnapshot(snapshot: BudgetSnapshot): void {
    setExpenses(snapshot.expenses);
    setSavings(snapshot.savings);
    setPlan(snapshot.plan);
    setComparison(snapshot.comparison);
  }

  async function refreshMonthChecked(
    token: number,
    target: number,
  ): Promise<ReportingMonth | null> {
    const freshMonth = await refresh();
    if (isStale(token, target)) return null;
    if (freshMonth.id !== target) throw new Error("Подтверждение вернуло другой месяц.");
    return freshMonth;
  }

  function lifecycleNotice(statusAtSubmit: string, freshStatus: string): string | null {
    if (freshStatus === statusAtSubmit) return null;
    return (
      `Запись подтверждена, но статус месяца изменился ` +
      `(${statusAtSubmit} → ${freshStatus}). Обновите раздел.`
    );
  }

  const templates = [...expenses, ...savings].filter(
    (row) => row.actual_fact_origin === "clone_template_v1",
  );
  async function confirmTemplates() {
    if (readOnly || busy || localDirty || !templates.length) return;
    const expenseTemplates = expenses.filter(
      (row) => row.actual_fact_origin === "clone_template_v1",
    );
    const savingTemplates = savings.filter((row) => row.actual_fact_origin === "clone_template_v1");
    const token = ++operation.current;
    setBusy(true);
    setActionError(null);
    try {
      for (const row of expenseTemplates) {
        await updateExpense(row.id, { amount: row.amount });
        if (isStale(token, monthId)) return;
      }
      for (const row of savingTemplates) {
        await updateSaving(row.id, { amount: row.amount });
        if (isStale(token, monthId)) return;
      }
      const snapshot = await refetchBudget(monthId);
      if (isStale(token, monthId)) return;
      if (
        [...snapshot.expenses, ...snapshot.savings].some(
          (row) => row.actual_fact_origin === "clone_template_v1",
        )
      )
        throw new Error("Подтверждение не подтверждено повторной загрузкой.");
      for (const row of expenseTemplates) {
        const fresh = snapshot.expenses.find((item) => item.id === row.id);
        if (
          !fresh ||
          fresh.actual_fact_origin !== "saved_actual_v1" ||
          !expenseMatches(fresh, {
            category: row.category,
            expense_type: row.expense_type,
            amount: moneyAmount(row.amount),
            notes: row.notes ?? "",
          })
        )
          throw staleRowError("expense", row.id);
      }
      for (const row of savingTemplates) {
        const fresh = snapshot.savings.find((item) => item.id === row.id);
        if (
          !fresh ||
          fresh.actual_fact_origin !== "saved_actual_v1" ||
          !savingMatches(fresh, {
            destination: row.destination,
            amount: moneyAmount(row.amount),
            notes: row.notes ?? "",
          })
        )
          throw staleRowError("saving", row.id);
      }
      installSnapshot(snapshot);
      await refreshMonthChecked(token, monthId);
    } catch (cause) {
      if (!isStale(token, monthId)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, monthId)) setBusy(false);
    }
  }

  async function addExpense(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const submitted: ExpenseExpectation = {
      category: expCategory,
      expense_type: expType,
      amount: expAmount,
      notes: expNotes,
    };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.category.trim() || !normalizeMoneyInput(submitted.amount)) {
        throw new Error("Категория и сумма обязательны");
      }
      const created = await createExpense({
        reporting_month_id: target,
        category: submitted.category.trim(),
        amount: rub(submitted.amount),
        expense_type: submitted.expense_type,
        notes: submitted.notes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.expenses.find((row) => row.id === created.id);
      if (!confirmed) throw missingRowError("expense", created.id);
      if (!expenseMatches(confirmed, submitted)) throw staleRowError("expense", created.id);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current;
      if (
        latest.expCategory === submitted.category &&
        latest.expType === submitted.expense_type &&
        latest.expAmount === submitted.amount &&
        latest.expNotes === submitted.notes
      ) {
        setExpCategory("");
        setExpAmount("");
        setExpNotes("");
        setExpenseDraftTouched(false);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ?? "Расход сохранён и подтверждён.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function handleSaveExpenseEdit() {
    if (editingExpenseId == null || !editExpense || readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const rowId = editingExpenseId;
    const submitted: ExpenseExpectation = { ...editExpense };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.category.trim() || !normalizeMoneyInput(submitted.amount)) {
        throw new Error("Категория и сумма обязательны");
      }
      const updated = await updateExpense(rowId, {
        category: submitted.category.trim(),
        amount: rub(submitted.amount),
        expense_type: submitted.expense_type,
        notes: submitted.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.expenses.find((row) => row.id === rowId);
      if (!confirmed) throw missingRowError("expense", rowId);
      if (!expenseMatches(confirmed, submitted)) throw staleRowError("expense", rowId);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current.editExpense;
      if (
        latest !== null &&
        latest.category === submitted.category &&
        latest.expense_type === submitted.expense_type &&
        latest.amount === submitted.amount &&
        latest.notes === submitted.notes
      ) {
        setEditingExpenseId(null);
        setEditExpense(null);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ?? "Расход обновлён и подтверждён.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function addSaving(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const submitted: SavingExpectation = {
      destination: savDest,
      amount: savAmount,
      notes: savNotes,
    };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.destination.trim() || !normalizeMoneyInput(submitted.amount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      const created = await createSaving({
        reporting_month_id: target,
        destination: submitted.destination.trim(),
        amount: rub(submitted.amount),
        notes: submitted.notes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.savings.find((row) => row.id === created.id);
      if (!confirmed) throw missingRowError("saving", created.id);
      if (!savingMatches(confirmed, submitted)) throw staleRowError("saving", created.id);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current;
      if (
        latest.savDest === submitted.destination &&
        latest.savAmount === submitted.amount &&
        latest.savNotes === submitted.notes
      ) {
        setSavDest("");
        setSavAmount("");
        setSavNotes("");
        setSavingDraftTouched(false);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ??
          "Накопление сохранено и подтверждено.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function handleSaveSavingEdit() {
    if (editingSavingId == null || !editSaving || readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const rowId = editingSavingId;
    const submitted: SavingExpectation = { ...editSaving };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.destination.trim() || !normalizeMoneyInput(submitted.amount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      const updated = await updateSaving(rowId, {
        destination: submitted.destination.trim(),
        amount: rub(submitted.amount),
        notes: submitted.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.savings.find((row) => row.id === rowId);
      if (!confirmed) throw missingRowError("saving", rowId);
      if (!savingMatches(confirmed, submitted)) throw staleRowError("saving", rowId);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current.editSaving;
      if (
        latest !== null &&
        latest.destination === submitted.destination &&
        latest.amount === submitted.amount &&
        latest.notes === submitted.notes
      ) {
        setEditingSavingId(null);
        setEditSaving(null);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ??
          "Накопление обновлено и подтверждено.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function addPlan(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const submitted: PlanExpectation = {
      category: planCategory,
      expense_type: planType,
      planned_amount: planAmount,
      notes: planNotes,
    };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.category.trim() || !normalizeMoneyInput(submitted.planned_amount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      const created = await createPlannedBudget({
        reporting_month_id: target,
        category: submitted.category.trim(),
        planned_amount: rub(submitted.planned_amount),
        expense_type: submitted.expense_type,
        notes: submitted.notes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.plan.find((row) => row.id === created.id);
      if (!confirmed) throw missingRowError("plan", created.id);
      if (!planMatches(confirmed, submitted)) throw staleRowError("plan", created.id);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current;
      if (
        latest.planCategory === submitted.category &&
        latest.planType === submitted.expense_type &&
        latest.planAmount === submitted.planned_amount &&
        latest.planNotes === submitted.notes
      ) {
        setPlanCategory("");
        setPlanAmount("");
        setPlanNotes("");
        setPlanDraftTouched(false);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ?? "План сохранён и подтверждён.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function handleSavePlanEdit() {
    if (editingPlanId == null || !editPlan || readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const rowId = editingPlanId;
    const submitted: PlanExpectation = { ...editPlan };
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!submitted.category.trim() || !normalizeMoneyInput(submitted.planned_amount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      const updated = await updatePlannedBudget(rowId, {
        category: submitted.category.trim(),
        planned_amount: rub(submitted.planned_amount),
        expense_type: submitted.expense_type,
        notes: submitted.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const confirmed = snapshot.plan.find((row) => row.id === rowId);
      if (!confirmed) throw missingRowError("plan", rowId);
      if (!planMatches(confirmed, submitted)) throw staleRowError("plan", rowId);
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      const latest = latestInputs.current.editPlan;
      if (
        latest !== null &&
        latest.category === submitted.category &&
        latest.expense_type === submitted.expense_type &&
        latest.planned_amount === submitted.planned_amount &&
        latest.notes === submitted.notes
      ) {
        setEditingPlanId(null);
        setEditPlan(null);
      }
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ?? "План обновлён и подтверждён.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  async function confirmDelete(kind: "expense" | "saving" | "plan") {
    if (readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    const statusAtSubmit = month.status;
    const expenseId = delExpense?.id ?? null;
    const savingId = delSaving?.id ?? null;
    const planId = delPlan?.id ?? null;
    const deletedId = kind === "expense" ? expenseId : kind === "saving" ? savingId : planId;
    if (deletedId == null) return;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (kind === "expense") {
        await deleteExpense(deletedId);
      } else if (kind === "saving") {
        await deleteSaving(deletedId);
      } else {
        await deletePlannedBudget(deletedId);
      }
      const snapshot = await refetchBudget(target);
      if (isStale(token, target)) return;
      const remaining =
        kind === "expense"
          ? snapshot.expenses
          : kind === "saving"
            ? snapshot.savings
            : snapshot.plan;
      if (remaining.some((row) => row.id === deletedId)) {
        throw deleteMissingError(kind, deletedId);
      }
      installSnapshot(snapshot);
      const freshMonth = await refreshMonthChecked(token, target);
      if (freshMonth === null) return;
      setDelExpense(null);
      setDelSaving(null);
      setDelPlan(null);
      setNotice(
        lifecycleNotice(statusAtSubmit, freshMonth.status) ?? "Запись удалена и подтверждена.",
      );
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) setBusy(false);
    }
  }

  if (loading) return <p role="status">Загружаем бюджет…</p>;
  if (error) {
    return (
      <div className={styles.warning} role="alert">
        <p>Не удалось загрузить бюджет: {error}</p>
        <button onClick={() => void load()} type="button">
          Повторить загрузку
        </button>
      </div>
    );
  }

  return (
    <div>
      {context.workspace ? (
        <MonthPanelTotal
          value={`обязательные ${formatMoney(mandatoryTotal)} · крупные и прочие ${formatMoney(otherExpenseTotal)}`}
        />
      ) : null}
      {actionError ? (
        <p className={styles.warning} role="alert">
          {actionError}
        </p>
      ) : null}
      {notice ? <p role="status">{context.workspace ? "Сохранено" : notice}</p> : null}

      {!readOnly && templates.length > 0 ? (
        <div>
          <p>Перенесено из другого месяца — подтвердите или измените.</p>
          <button
            type="button"
            disabled={busy || localDirty}
            onClick={() => void confirmTemplates()}
          >
            Подтвердить без изменений
          </button>
        </div>
      ) : null}
      <section aria-label="Расходы месяца" className={styles.panel}>
        {!context.workspace && <h2>Расходы</h2>}
        {(
          [
            { id: "mandatory", title: "Обязательные", total: mandatoryTotal },
            { id: "other", title: "Крупные и прочие", total: otherExpenseTotal },
          ] as const
        ).map((expenseGroup) => {
          const rows = expenses
            .filter(
              (row) => (row.expense_type === "mandatory") === (expenseGroup.id === "mandatory"),
            )
            .sort((a, b) => {
              const left = toKopecks(moneyAmount(a.amount));
              const right = toKopecks(moneyAmount(b.amount));
              return left === right ? 0 : left > right ? -1 : 1;
            });
          const groups = budgetGroups.filter(
            (group) => (group.expenseType === "mandatory") === (expenseGroup.id === "mandatory"),
          );
          if (readOnly && !rows.length && !groups.length) return null;
          const addingHere = (expType === "mandatory") === (expenseGroup.id === "mandatory");
          const addRow = !readOnly ? (
            <tr>
              <Td
                colSpan={
                  plan.length
                    ? 3 + Number(editingExpenseId !== null)
                    : 3 +
                      Number(editingExpenseId !== null) +
                      Number(rows.some((row) => row.notes?.trim()) || editingExpenseId !== null)
                }
              >
                {addingHere ? (
                  <form
                    className={styles.addExpenseRow}
                    onSubmit={(event) => void addExpense(event)}
                  >
                    <label>
                      Категория расхода
                      <input
                        required
                        value={expCategory}
                        onChange={(event) => {
                          setExpCategory(event.target.value);
                          setExpenseDraftTouched(true);
                        }}
                      />
                    </label>
                    <label htmlFor={`budget-add-${expenseGroup.id}`}>
                      Сумма расхода
                      <MonthMoneyInput
                        aria-label="Сумма расхода"
                        id={`budget-add-${expenseGroup.id}`}
                        required
                        value={expAmount}
                        onChange={(value) => {
                          setExpAmount(value);
                          setExpenseDraftTouched(true);
                        }}
                      />
                    </label>
                    <label>
                      Комментарий расхода
                      <input
                        value={expNotes}
                        onChange={(event) => {
                          setExpNotes(event.target.value);
                          setExpenseDraftTouched(true);
                        }}
                      />
                    </label>
                    <button disabled={busy} type="submit">
                      Добавить расход
                    </button>
                  </form>
                ) : (
                  <button
                    type="button"
                    disabled={busy || expenseDraftTouched}
                    onClick={() =>
                      setExpType(expenseGroup.id === "mandatory" ? "mandatory" : "other")
                    }
                  >
                    + Добавить расход
                  </button>
                )}
              </Td>
            </tr>
          ) : null;
          return (
            <section key={expenseGroup.id} aria-label={expenseGroup.title}>
              <h3>
                {expenseGroup.title} · {formatMoney(expenseGroup.total)}
              </h3>
              {plan.length > 0 ? (
                <Table aria-label="Расходы месяца" className={styles.budgetTable}>
                  <thead>
                    <tr>
                      <Th scope="col">Категория</Th>
                      {editingExpenseId !== null ? <Th scope="col">Тип</Th> : null}
                      <Th scope="col">Факт</Th>
                      <Th scope="col">План</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((group) => {
                      const actual =
                        group.comparison?.actual ??
                        (group.actual.length
                          ? {
                              amount: sumMoneyAmounts(
                                group.actual.map((row) => moneyAmount(row.amount)),
                              ),
                              currency: "RUB",
                            }
                          : null);
                      const planned =
                        group.comparison?.planned ??
                        (group.planned.length
                          ? {
                              amount: sumMoneyAmounts(
                                group.planned.map((row) => moneyAmount(row.planned_amount)),
                              ),
                              currency: "RUB",
                            }
                          : null);
                      return (
                        <tr key={JSON.stringify([group.category, group.expenseType])}>
                          <Td>{group.category}</Td>
                          {editingExpenseId !== null ? (
                            <Td>{labelOf(EXPENSE_TYPE_LABELS, group.expenseType)}</Td>
                          ) : null}
                          {!readOnly ? (
                            <Td numeric>
                              {actual === null ? "—" : formatMoney(moneyAmount(actual))}
                              {group.actual.length ? (
                                <details
                                  open={group.actual.some((row) => row.id === editingExpenseId)}
                                >
                                  <summary>Расходы: {group.actual.length}</summary>
                                  {group.actual.map((row) => (
                                    <fieldset
                                      className={styles.budgetEntry}
                                      key={row.id}
                                      onKeyDown={(event) => {
                                        if (busy) return;
                                        if (event.key === "Escape") {
                                          event.preventDefault();
                                          setEditingExpenseId(null);
                                          setEditExpense(null);
                                        }
                                        if (
                                          event.key === "Enter" &&
                                          event.target instanceof HTMLInputElement &&
                                          editingExpenseId === row.id
                                        ) {
                                          event.preventDefault();
                                          void handleSaveExpenseEdit();
                                        }
                                      }}
                                    >
                                      {editingExpenseId === row.id && editExpense ? (
                                        <>
                                          <label>
                                            Категория расхода
                                            <input
                                              ref={expenseEditRef}
                                              value={editExpense.category}
                                              onChange={(event) =>
                                                setEditExpense({
                                                  ...editExpense,
                                                  category: event.target.value,
                                                })
                                              }
                                            />
                                          </label>
                                          <label>
                                            Тип расхода
                                            <select
                                              value={editExpense.expense_type}
                                              onChange={(event) =>
                                                setEditExpense({
                                                  ...editExpense,
                                                  expense_type: event.target.value,
                                                })
                                              }
                                            >
                                              <option value="mandatory">Обязательный</option>
                                              <option value="comfortable">Комфортный</option>
                                              <option value="other">Прочее</option>
                                            </select>
                                          </label>
                                          <label htmlFor={`budget-expense-${row.id}`}>
                                            Сумма расхода
                                            <MonthMoneyInput
                                              aria-label="Сумма расхода"
                                              id={`budget-expense-${row.id}`}
                                              value={editExpense.amount}
                                              onChange={(value) =>
                                                setEditExpense({ ...editExpense, amount: value })
                                              }
                                            />
                                          </label>
                                          <label>
                                            Комментарий расхода
                                            <input
                                              value={editExpense.notes}
                                              onChange={(event) =>
                                                setEditExpense({
                                                  ...editExpense,
                                                  notes: event.target.value,
                                                })
                                              }
                                            />
                                          </label>
                                          {!readOnly ? (
                                            <button
                                              disabled={busy || readOnly}
                                              onClick={() => void handleSaveExpenseEdit()}
                                              type="button"
                                            >
                                              Готово
                                            </button>
                                          ) : null}
                                          {!readOnly ? (
                                            <button
                                              disabled={busy}
                                              onClick={() => {
                                                setEditingExpenseId(null);
                                                setEditExpense(null);
                                              }}
                                              type="button"
                                            >
                                              Отмена
                                            </button>
                                          ) : null}
                                        </>
                                      ) : (
                                        <>
                                          <span>
                                            {formatMoney(moneyAmount(row.amount))}
                                            {row.notes ? ` · ${row.notes}` : ""}
                                          </span>
                                          <OverflowMenu label="Действия строки">
                                            {!readOnly ? (
                                              <OverflowMenuItem
                                                disabled={busy || readOnly}
                                                onClick={() => {
                                                  setEditingExpenseId(row.id);
                                                  setEditExpense({
                                                    category: row.category,
                                                    expense_type: row.expense_type,
                                                    amount: moneyAmount(row.amount),
                                                    notes: row.notes ?? "",
                                                  });
                                                }}
                                                type="button"
                                              >
                                                Изменить
                                              </OverflowMenuItem>
                                            ) : null}
                                            {!readOnly ? (
                                              <OverflowMenuItem
                                                disabled={busy || readOnly}
                                                onClick={() => setDelExpense(row)}
                                                type="button"
                                              >
                                                Удалить
                                              </OverflowMenuItem>
                                            ) : null}
                                          </OverflowMenu>
                                        </>
                                      )}
                                    </fieldset>
                                  ))}
                                </details>
                              ) : null}
                            </Td>
                          ) : null}
                          <Td>
                            {planned === null ? "—" : formatMoney(moneyAmount(planned))}
                            {group.planned.length ? (
                              <details open={group.planned.some((row) => row.id === editingPlanId)}>
                                <summary>План: {group.planned.length}</summary>
                                {group.planned.map((row) => (
                                  <fieldset
                                    className={styles.budgetEntry}
                                    key={row.id}
                                    onKeyDown={(event) => {
                                      if (busy) return;
                                      if (event.key === "Escape") {
                                        event.preventDefault();
                                        setEditingPlanId(null);
                                        setEditPlan(null);
                                      }
                                      if (
                                        event.key === "Enter" &&
                                        event.target instanceof HTMLInputElement &&
                                        editingPlanId === row.id
                                      ) {
                                        event.preventDefault();
                                        void handleSavePlanEdit();
                                      }
                                    }}
                                  >
                                    {editingPlanId === row.id && editPlan ? (
                                      <>
                                        <label>
                                          Категория плана
                                          <input
                                            ref={planEditRef}
                                            value={editPlan.category}
                                            onChange={(event) =>
                                              setEditPlan({
                                                ...editPlan,
                                                category: event.target.value,
                                              })
                                            }
                                          />
                                        </label>
                                        <label>
                                          Тип плана
                                          <select
                                            value={editPlan.expense_type}
                                            onChange={(event) =>
                                              setEditPlan({
                                                ...editPlan,
                                                expense_type: event.target.value,
                                              })
                                            }
                                          >
                                            <option value="mandatory">Обязательный</option>
                                            <option value="comfortable">Комфортный</option>
                                            <option value="other">Прочее</option>
                                          </select>
                                        </label>
                                        <label htmlFor={`budget-plan-${row.id}`}>
                                          Сумма плана
                                          <MonthMoneyInput
                                            aria-label="Сумма плана"
                                            id={`budget-plan-${row.id}`}
                                            value={editPlan.planned_amount}
                                            onChange={(value) =>
                                              setEditPlan({ ...editPlan, planned_amount: value })
                                            }
                                          />
                                        </label>
                                        <label>
                                          Комментарий плана
                                          <input
                                            value={editPlan.notes}
                                            onChange={(event) =>
                                              setEditPlan({
                                                ...editPlan,
                                                notes: event.target.value,
                                              })
                                            }
                                          />
                                        </label>
                                        {!readOnly ? (
                                          <button
                                            disabled={busy || readOnly}
                                            onClick={() => void handleSavePlanEdit()}
                                            type="button"
                                          >
                                            Готово
                                          </button>
                                        ) : null}
                                        {!readOnly ? (
                                          <button
                                            disabled={busy}
                                            onClick={() => {
                                              setEditingPlanId(null);
                                              setEditPlan(null);
                                            }}
                                            type="button"
                                          >
                                            Отмена
                                          </button>
                                        ) : null}
                                      </>
                                    ) : (
                                      <>
                                        <span>
                                          {formatMoney(moneyAmount(row.planned_amount))}
                                          {row.notes ? ` · ${row.notes}` : ""}
                                        </span>
                                        <OverflowMenu label="Действия строки">
                                          {!readOnly ? (
                                            <OverflowMenuItem
                                              disabled={busy || readOnly}
                                              onClick={() => {
                                                setEditingPlanId(row.id);
                                                setEditPlan({
                                                  category: row.category,
                                                  expense_type: row.expense_type,
                                                  planned_amount: moneyAmount(row.planned_amount),
                                                  notes: row.notes ?? "",
                                                });
                                              }}
                                              type="button"
                                            >
                                              Изменить
                                            </OverflowMenuItem>
                                          ) : null}
                                          {!readOnly ? (
                                            <OverflowMenuItem
                                              disabled={busy || readOnly}
                                              onClick={() => setDelPlan(row)}
                                              type="button"
                                            >
                                              Удалить
                                            </OverflowMenuItem>
                                          ) : null}
                                        </OverflowMenu>
                                      </>
                                    )}
                                  </fieldset>
                                ))}
                              </details>
                            ) : null}
                          </Td>
                        </tr>
                      );
                    })}
                    {addRow}
                  </tbody>
                </Table>
              ) : (
                <Table aria-label="Расходы месяца" className={styles.budgetTable}>
                  <thead>
                    <tr>
                      <Th scope="col">Категория</Th>
                      {editingExpenseId !== null ? <Th scope="col">Тип</Th> : null}
                      <Th scope="col" numeric>
                        Сумма
                      </Th>
                      {rows.some((row) => row.notes?.trim()) || editingExpenseId !== null ? (
                        <Th scope="col">Комментарий</Th>
                      ) : null}
                      {!readOnly ? <Th scope="col">Действия</Th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const editing = editingExpenseId === row.id && editExpense;
                      return (
                        <tr
                          key={row.id}
                          onKeyDown={(event) => {
                            if (busy) return;
                            if (event.key === "Escape") {
                              event.preventDefault();
                              setEditingExpenseId(null);
                              setEditExpense(null);
                            }
                            if (
                              event.key === "Enter" &&
                              event.target instanceof HTMLInputElement &&
                              editingExpenseId === row.id
                            ) {
                              event.preventDefault();
                              void handleSaveExpenseEdit();
                            }
                          }}
                        >
                          <Td>
                            {editing ? (
                              <input
                                ref={expenseEditRef}
                                aria-label="Категория расхода"
                                onChange={(event) =>
                                  setEditExpense({ ...editExpense, category: event.target.value })
                                }
                                value={editExpense.category}
                              />
                            ) : (
                              row.category
                            )}
                          </Td>
                          {editingExpenseId !== null ? (
                            <Td>
                              {editing ? (
                                <select
                                  aria-label="Тип расхода"
                                  onChange={(event) =>
                                    setEditExpense({
                                      ...editExpense,
                                      expense_type: event.target.value,
                                    })
                                  }
                                  value={editExpense.expense_type}
                                >
                                  <option value="mandatory">Обязательный</option>
                                  <option value="comfortable">Комфортный</option>
                                  <option value="other">Прочее</option>
                                </select>
                              ) : (
                                labelOf(EXPENSE_TYPE_LABELS, row.expense_type)
                              )}
                            </Td>
                          ) : null}
                          <Td numeric>
                            {editing ? (
                              <MonthMoneyInput
                                aria-label="Сумма расхода"
                                value={editExpense.amount}
                                onChange={(value) =>
                                  setEditExpense({ ...editExpense, amount: value })
                                }
                              />
                            ) : (
                              formatMoney(moneyAmount(row.amount))
                            )}
                          </Td>
                          {rows.some((row) => row.notes?.trim()) || editingExpenseId !== null ? (
                            <Td>
                              {editing ? (
                                <input
                                  aria-label="Комментарий расхода"
                                  onChange={(event) =>
                                    setEditExpense({ ...editExpense, notes: event.target.value })
                                  }
                                  value={editExpense.notes}
                                />
                              ) : (
                                (row.notes ?? "—")
                              )}
                            </Td>
                          ) : null}
                          {!readOnly ? (
                            <Td numeric>
                              {editing ? (
                                <>
                                  {!readOnly ? (
                                    <button
                                      disabled={busy || readOnly}
                                      onClick={() => void handleSaveExpenseEdit()}
                                      type="button"
                                    >
                                      Готово
                                    </button>
                                  ) : null}
                                  {!readOnly ? (
                                    <button
                                      disabled={busy}
                                      onClick={() => {
                                        setEditingExpenseId(null);
                                        setEditExpense(null);
                                      }}
                                      type="button"
                                    >
                                      Отмена
                                    </button>
                                  ) : null}
                                </>
                              ) : (
                                <OverflowMenu label="Действия строки">
                                  {!readOnly ? (
                                    <OverflowMenuItem
                                      disabled={busy || readOnly}
                                      onClick={() => {
                                        setEditingExpenseId(row.id);
                                        setEditExpense({
                                          category: row.category,
                                          expense_type: row.expense_type,
                                          amount: moneyAmount(row.amount),
                                          notes: row.notes ?? "",
                                        });
                                      }}
                                      type="button"
                                    >
                                      Изменить
                                    </OverflowMenuItem>
                                  ) : null}
                                  {!readOnly ? (
                                    <OverflowMenuItem
                                      disabled={busy || readOnly}
                                      onClick={() => setDelExpense(row)}
                                      type="button"
                                    >
                                      Удалить
                                    </OverflowMenuItem>
                                  ) : null}
                                </OverflowMenu>
                              )}
                            </Td>
                          ) : null}
                        </tr>
                      );
                    })}
                    {addRow}
                  </tbody>
                </Table>
              )}
            </section>
          );
        })}
        <section aria-label="План бюджета месяца">
          {plan.length ? (
            <p>
              План: <strong>{formatMoney(plannedTotal)}</strong>
            </p>
          ) : null}
          {!readOnly ? (
            <details>
              <summary>Добавить план</summary>
              <form className={styles.form} onSubmit={(event) => void addPlan(event)}>
                <label>
                  Категория плана
                  <input
                    onChange={(event) => {
                      setPlanCategory(event.target.value);
                      setPlanDraftTouched(true);
                    }}
                    required
                    value={planCategory}
                  />
                </label>
                <label>
                  Тип плана
                  <select
                    onChange={(event) => {
                      setPlanType(event.target.value);
                      setPlanDraftTouched(true);
                    }}
                    value={planType}
                  >
                    <option value="mandatory">Обязательный</option>
                    <option value="comfortable">Комфортный</option>
                    <option value="other">Прочее</option>
                  </select>
                </label>
                <label>
                  Сумма плана
                  <input
                    onChange={(event) => {
                      setPlanAmount(event.target.value);
                      setPlanDraftTouched(true);
                    }}
                    required
                    value={planAmount}
                  />
                </label>
                <label>
                  Комментарий плана
                  <input
                    onChange={(event) => {
                      setPlanNotes(event.target.value);
                      setPlanDraftTouched(true);
                    }}
                    value={planNotes}
                  />
                </label>
                <button disabled={busy} type="submit">
                  Добавить в план
                </button>
              </form>
            </details>
          ) : null}
        </section>
      </section>

      {!readOnly || toKopecks(savingsTotal) !== 0n ? (
        <section aria-label="Накопления месяца">
          <details
            className={styles.panel}
            open={readOnly || !context.workspace ? true : undefined}
          >
            <summary>Накопления · {formatMoney(savingsTotal)}</summary>
            <p>
              Всего накоплений: <strong>{formatMoney(savingsTotal)}</strong>
            </p>
            {savings.length === 0 ? (
              <p>Накоплений пока нет.</p>
            ) : (
              <Table aria-label="Накопления месяца" className={styles.budgetTable}>
                <thead>
                  <tr>
                    <Th scope="col">Направление</Th>
                    <Th scope="col" numeric>
                      Сумма
                    </Th>
                    {savings.some((row) => row.notes?.trim()) || editingSavingId !== null ? (
                      <Th scope="col">Комментарий</Th>
                    ) : null}
                    {!readOnly ? <Th scope="col">Действия</Th> : null}
                  </tr>
                </thead>
                <tbody>
                  {savings.map((row) => {
                    const editing = editingSavingId === row.id && editSaving;
                    return (
                      <tr
                        key={row.id}
                        onKeyDown={(event) => {
                          if (busy) return;
                          if (event.key === "Escape") {
                            event.preventDefault();
                            setEditingSavingId(null);
                            setEditSaving(null);
                          }
                          if (
                            event.key === "Enter" &&
                            event.target instanceof HTMLInputElement &&
                            editingSavingId === row.id
                          ) {
                            event.preventDefault();
                            void handleSaveSavingEdit();
                          }
                        }}
                      >
                        <Td>
                          {editing ? (
                            <input
                              ref={savingEditRef}
                              aria-label="Направление накопления"
                              onChange={(event) =>
                                setEditSaving({ ...editSaving, destination: event.target.value })
                              }
                              value={editSaving.destination}
                            />
                          ) : (
                            row.destination
                          )}
                        </Td>
                        <Td numeric>
                          {editing ? (
                            <MonthMoneyInput
                              aria-label="Сумма накопления"
                              value={editSaving.amount}
                              onChange={(value) => setEditSaving({ ...editSaving, amount: value })}
                            />
                          ) : (
                            formatMoney(moneyAmount(row.amount))
                          )}
                        </Td>
                        {savings.some((row) => row.notes?.trim()) || editingSavingId !== null ? (
                          <Td>
                            {editing ? (
                              <input
                                aria-label="Комментарий накопления"
                                onChange={(event) =>
                                  setEditSaving({ ...editSaving, notes: event.target.value })
                                }
                                value={editSaving.notes}
                              />
                            ) : (
                              (row.notes ?? "—")
                            )}
                          </Td>
                        ) : null}
                        {!readOnly ? (
                          <Td numeric>
                            {editing ? (
                              <>
                                <button
                                  disabled={busy || readOnly}
                                  onClick={() => void handleSaveSavingEdit()}
                                  type="button"
                                >
                                  Готово
                                </button>
                                <button
                                  disabled={busy}
                                  onClick={() => {
                                    setEditingSavingId(null);
                                    setEditSaving(null);
                                  }}
                                  type="button"
                                >
                                  Отмена
                                </button>
                              </>
                            ) : (
                              <OverflowMenu label="Действия строки">
                                <OverflowMenuItem
                                  disabled={busy || readOnly}
                                  onClick={() => {
                                    setEditingSavingId(row.id);
                                    setEditSaving({
                                      destination: row.destination,
                                      amount: moneyAmount(row.amount),
                                      notes: row.notes ?? "",
                                    });
                                  }}
                                  type="button"
                                >
                                  Изменить
                                </OverflowMenuItem>
                                <OverflowMenuItem
                                  disabled={busy || readOnly}
                                  onClick={() => setDelSaving(row)}
                                  type="button"
                                >
                                  Удалить
                                </OverflowMenuItem>
                              </OverflowMenu>
                            )}
                          </Td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
            {!readOnly ? (
              <form className={styles.form} onSubmit={(event) => void addSaving(event)}>
                <label>
                  Направление накопления
                  <input
                    onChange={(event) => {
                      setSavDest(event.target.value);
                      setSavingDraftTouched(true);
                    }}
                    required
                    value={savDest}
                  />
                </label>
                <label>
                  Сумма накопления
                  <input
                    onChange={(event) => {
                      setSavAmount(event.target.value);
                      setSavingDraftTouched(true);
                    }}
                    required
                    value={savAmount}
                  />
                </label>
                <label>
                  Комментарий накопления
                  <input
                    onChange={(event) => {
                      setSavNotes(event.target.value);
                      setSavingDraftTouched(true);
                    }}
                    value={savNotes}
                  />
                </label>
                <button disabled={busy} type="submit">
                  Добавить накопление
                </button>
              </form>
            ) : null}
          </details>
        </section>
      ) : null}

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delExpense ? `Удалить расход <${delExpense.category}>?` : ""}
        onCancel={() => setDelExpense(null)}
        onConfirm={() => void confirmDelete("expense")}
        open={delExpense !== null}
        title="Удалить расход?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delSaving ? `Удалить накопление <${delSaving.destination}>?` : ""}
        onCancel={() => setDelSaving(null)}
        onConfirm={() => void confirmDelete("saving")}
        open={delSaving !== null}
        title="Удалить накопление?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delPlan ? `Удалить план <${delPlan.category}>?` : ""}
        onCancel={() => setDelPlan(null)}
        onConfirm={() => void confirmDelete("plan")}
        open={delPlan !== null}
        title="Удалить план?"
      />
    </div>
  );
}
