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
import { ConfirmDialog, Table, Td, Th } from "../components/ui";
import { formatMoney } from "../lib/format";
import { EXPENSE_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import styles from "./UiV2MonthEditor.module.css";

/** Leaf section id reserved for Integrator wiring (#563, after #558). */
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
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [editExpense, setEditExpense] = useState<ExpenseDraft | null>(null);
  const [editingSavingId, setEditingSavingId] = useState<number | null>(null);
  const [editSaving, setEditSaving] = useState<SavingDraft | null>(null);
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);
  const [editPlan, setEditPlan] = useState<PlanDraft | null>(null);

  const operation = useRef(0);

  const localDirty =
    expenseDraftTouched ||
    savingDraftTouched ||
    planDraftTouched ||
    editingExpenseId !== null ||
    editingSavingId !== null ||
    editingPlanId !== null;

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
      {actionError ? (
        <p className={styles.warning} role="alert">
          {actionError}
        </p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}

      <section aria-label="Расходы месяца" className={styles.panel}>
        <h2>Расходы</h2>
        <p>
          Обязательные: <strong>{formatMoney(mandatoryTotal)}</strong>
          {" · "}Комфортные и прочие: <strong>{formatMoney(otherExpenseTotal)}</strong>
        </p>
        {expenses.length === 0 ? (
          <p>Расходов пока нет.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Категория</Th>
                <Th>Тип</Th>
                <Th numeric>Сумма</Th>
                <Th>Комментарий</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {expenses.map((row) => {
                const editing = editingExpenseId === row.id && editExpense;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <input
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
                    <Td>
                      {editing ? (
                        <select
                          aria-label="Тип расхода"
                          onChange={(event) =>
                            setEditExpense({ ...editExpense, expense_type: event.target.value })
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
                    <Td>
                      {editing ? (
                        <input
                          aria-label="Сумма расхода"
                          onChange={(event) =>
                            setEditExpense({ ...editExpense, amount: event.target.value })
                          }
                          value={editExpense.amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.amount))
                      )}
                    </Td>
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
                    <Td>
                      {editing ? (
                        <>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => void handleSaveExpenseEdit()}
                            type="button"
                          >
                            OK
                          </button>
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
                        </>
                      ) : (
                        <>
                          <button
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
                          </button>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => setDelExpense(row)}
                            type="button"
                          >
                            Удалить
                          </button>
                        </>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        {!readOnly ? (
          <form className={styles.form} onSubmit={(event) => void addExpense(event)}>
            <label>
              Категория расхода
              <input
                onChange={(event) => {
                  setExpCategory(event.target.value);
                  setExpenseDraftTouched(true);
                }}
                required
                value={expCategory}
              />
            </label>
            <label>
              Тип расхода
              <select
                onChange={(event) => {
                  setExpType(event.target.value);
                  setExpenseDraftTouched(true);
                }}
                value={expType}
              >
                <option value="mandatory">Обязательный</option>
                <option value="comfortable">Комфортный</option>
                <option value="other">Прочее</option>
              </select>
            </label>
            <label>
              Сумма расхода
              <input
                onChange={(event) => {
                  setExpAmount(event.target.value);
                  setExpenseDraftTouched(true);
                }}
                required
                value={expAmount}
              />
            </label>
            <label>
              Комментарий расхода
              <input
                onChange={(event) => {
                  setExpNotes(event.target.value);
                  setExpenseDraftTouched(true);
                }}
                value={expNotes}
              />
            </label>
            <button disabled={busy} type="submit">
              Добавить расход
            </button>
          </form>
        ) : null}
      </section>

      <section aria-label="План бюджета месяца" className={styles.panel}>
        <h2>План бюджета</h2>
        <p>
          {plan.length === 0 ? (
            "План не задан"
          ) : (
            <>
              План: <strong>{formatMoney(plannedTotal)}</strong>
            </>
          )}
        </p>
        <p className={styles.hint}>
          Отдельный план показывается только когда он действительно введён. Отсутствующий план — это
          прочерк, а не ноль; введённый ноль остаётся нулём.
        </p>
        {plan.length === 0 ? (
          <p>План пока не введён.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Категория</Th>
                <Th>Тип</Th>
                <Th numeric>Сумма плана</Th>
                <Th>Комментарий</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {plan.map((row) => {
                const editing = editingPlanId === row.id && editPlan;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <input
                          aria-label="Категория плана"
                          onChange={(event) =>
                            setEditPlan({ ...editPlan, category: event.target.value })
                          }
                          value={editPlan.category}
                        />
                      ) : (
                        row.category
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <select
                          aria-label="Тип плана"
                          onChange={(event) =>
                            setEditPlan({ ...editPlan, expense_type: event.target.value })
                          }
                          value={editPlan.expense_type}
                        >
                          <option value="mandatory">Обязательный</option>
                          <option value="comfortable">Комфортный</option>
                          <option value="other">Прочее</option>
                        </select>
                      ) : (
                        labelOf(EXPENSE_TYPE_LABELS, row.expense_type)
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <input
                          aria-label="Сумма плана"
                          onChange={(event) =>
                            setEditPlan({ ...editPlan, planned_amount: event.target.value })
                          }
                          value={editPlan.planned_amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.planned_amount))
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <input
                          aria-label="Комментарий плана"
                          onChange={(event) =>
                            setEditPlan({ ...editPlan, notes: event.target.value })
                          }
                          value={editPlan.notes}
                        />
                      ) : (
                        (row.notes ?? "—")
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => void handleSavePlanEdit()}
                            type="button"
                          >
                            OK
                          </button>
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
                        </>
                      ) : (
                        <>
                          <button
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
                          </button>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => setDelPlan(row)}
                            type="button"
                          >
                            Удалить
                          </button>
                        </>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        {comparison.length > 0 ? (
          <Table>
            <thead>
              <tr>
                <Th>Категория</Th>
                <Th>Тип</Th>
                <Th numeric>План</Th>
                <Th numeric>Факт</Th>
              </tr>
            </thead>
            <tbody>
              {comparison.map((row) => (
                <tr key={`${row.category}::${row.expense_type}`}>
                  <Td>{row.category}</Td>
                  <Td>{labelOf(EXPENSE_TYPE_LABELS, row.expense_type)}</Td>
                  <Td>{row.planned === null ? "—" : formatMoney(moneyAmount(row.planned))}</Td>
                  <Td>{row.actual === null ? "—" : formatMoney(moneyAmount(row.actual))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : null}
        {!readOnly ? (
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
        ) : null}
      </section>

      <section aria-label="Накопления месяца" className={styles.panel}>
        <h2>Накопления</h2>
        <p>
          Всего накоплений: <strong>{formatMoney(savingsTotal)}</strong>
        </p>
        {savings.length === 0 ? (
          <p>Накоплений пока нет.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Направление</Th>
                <Th numeric>Сумма</Th>
                <Th>Комментарий</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {savings.map((row) => {
                const editing = editingSavingId === row.id && editSaving;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <input
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
                    <Td>
                      {editing ? (
                        <input
                          aria-label="Сумма накопления"
                          onChange={(event) =>
                            setEditSaving({ ...editSaving, amount: event.target.value })
                          }
                          value={editSaving.amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.amount))
                      )}
                    </Td>
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
                    <Td>
                      {editing ? (
                        <>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => void handleSaveSavingEdit()}
                            type="button"
                          >
                            OK
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
                        <>
                          <button
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
                          </button>
                          <button
                            disabled={busy || readOnly}
                            onClick={() => setDelSaving(row)}
                            type="button"
                          >
                            Удалить
                          </button>
                        </>
                      )}
                    </Td>
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
      </section>

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
