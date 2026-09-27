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

  async function reloadAfterWrite(token: number, target: number): Promise<void> {
    const [freshExpenses, freshSavings, freshPlan, freshComparison] = await Promise.all([
      listExpenses(target),
      listSavings(target),
      listPlannedBudget(target),
      plannedVsActual(target),
    ]);
    if (isStale(token, target)) return;
    if (
      freshExpenses.some((row) => row.reporting_month_id !== target) ||
      freshSavings.some((row) => row.reporting_month_id !== target) ||
      freshPlan.some((row) => row.reporting_month_id !== target)
    ) {
      throw new Error("Подтверждение вернуло записи другого месяца.");
    }
    setExpenses(freshExpenses);
    setSavings(freshSavings);
    setPlan(freshPlan);
    setComparison(freshComparison);
    const freshMonth = await refresh();
    if (isStale(token, target)) return;
    if (freshMonth.id !== target) throw new Error("Подтверждение вернуло другой месяц.");
  }

  async function addExpense(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const token = ++operation.current;
    const target = month.id;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!expCategory.trim() || !normalizeMoneyInput(expAmount)) {
        throw new Error("Категория и сумма обязательны");
      }
      const created = await createExpense({
        reporting_month_id: target,
        category: expCategory.trim(),
        amount: rub(expAmount),
        expense_type: expType,
        notes: expNotes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setExpCategory("");
      setExpAmount("");
      setExpNotes("");
      setExpenseDraftTouched(false);
      setNotice("Расход сохранён и перечитан.");
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
    const rowId = editingExpenseId;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!editExpense.category.trim() || !normalizeMoneyInput(editExpense.amount)) {
        throw new Error("Категория и сумма обязательны");
      }
      const updated = await updateExpense(rowId, {
        category: editExpense.category.trim(),
        amount: rub(editExpense.amount),
        expense_type: editExpense.expense_type,
        notes: editExpense.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setEditingExpenseId(null);
      setEditExpense(null);
      setNotice("Расход обновлён и перечитан.");
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
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!savDest.trim() || !normalizeMoneyInput(savAmount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      const created = await createSaving({
        reporting_month_id: target,
        destination: savDest.trim(),
        amount: rub(savAmount),
        notes: savNotes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setSavDest("");
      setSavAmount("");
      setSavNotes("");
      setSavingDraftTouched(false);
      setNotice("Накопление сохранено и перечитано.");
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
    const rowId = editingSavingId;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!editSaving.destination.trim() || !normalizeMoneyInput(editSaving.amount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      const updated = await updateSaving(rowId, {
        destination: editSaving.destination.trim(),
        amount: rub(editSaving.amount),
        notes: editSaving.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setEditingSavingId(null);
      setEditSaving(null);
      setNotice("Накопление обновлено и перечитано.");
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
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!planCategory.trim() || !normalizeMoneyInput(planAmount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      const created = await createPlannedBudget({
        reporting_month_id: target,
        category: planCategory.trim(),
        planned_amount: rub(planAmount),
        expense_type: planType,
        notes: planNotes.trim() || null,
      });
      if (created.reporting_month_id !== target) {
        throw new Error("Создана запись другого месяца.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setPlanCategory("");
      setPlanAmount("");
      setPlanNotes("");
      setPlanDraftTouched(false);
      setNotice("План сохранён и перечитан.");
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
    const rowId = editingPlanId;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!editPlan.category.trim() || !normalizeMoneyInput(editPlan.planned_amount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      const updated = await updatePlannedBudget(rowId, {
        category: editPlan.category.trim(),
        planned_amount: rub(editPlan.planned_amount),
        expense_type: editPlan.expense_type,
        notes: editPlan.notes.trim() || null,
      });
      if (updated.id !== rowId || updated.reporting_month_id !== target) {
        throw new Error("Подтверждение вернуло другую запись.");
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setEditingPlanId(null);
      setEditPlan(null);
      setNotice("План обновлён и перечитан.");
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
    const expenseId = delExpense?.id ?? null;
    const savingId = delSaving?.id ?? null;
    const planId = delPlan?.id ?? null;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (kind === "expense" && expenseId != null) {
        await deleteExpense(expenseId);
      } else if (kind === "saving" && savingId != null) {
        await deleteSaving(savingId);
      } else if (kind === "plan" && planId != null) {
        await deletePlannedBudget(planId);
      } else {
        return;
      }
      await reloadAfterWrite(token, target);
      if (isStale(token, target)) return;
      setDelExpense(null);
      setDelSaving(null);
      setDelPlan(null);
      setNotice("Запись удалена, список перечитан.");
    } catch (cause) {
      if (!isStale(token, target)) setActionError(formatApiError(cause));
    } finally {
      if (!isStale(token, target)) {
        setBusy(false);
        if (kind === "expense") setDelExpense(null);
        if (kind === "saving") setDelSaving(null);
        if (kind === "plan") setDelPlan(null);
      }
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
