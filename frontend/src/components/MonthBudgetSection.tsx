import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

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
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  OverflowMenu,
  OverflowMenuItem,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "./ui";
import { formatMoney } from "../lib/format";
import { EXPENSE_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type Props = { monthId: number; readOnly: boolean; onDirtyChange?: (dirty: boolean) => void };

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

export function MonthBudgetSection({ monthId, readOnly, onDirtyChange }: Props) {
  const [expenses, setExpenses] = useState<ExpenseEntry[]>([]);
  const [savings, setSavings] = useState<SavingAllocation[]>([]);
  const [plan, setPlan] = useState<PlannedBudgetLine[]>([]);
  const [comparison, setComparison] = useState<PlanVsActualRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
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

  const localDirty =
    expenseDraftTouched ||
    savingDraftTouched ||
    planDraftTouched ||
    editingExpenseId !== null ||
    editingSavingId !== null ||
    editingPlanId !== null;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [e, s, p, c] = await Promise.all([
          listExpenses(monthId, signal),
          listSavings(monthId, signal),
          listPlannedBudget(monthId, signal),
          plannedVsActual(monthId, signal),
        ]);
        if (!signal?.aborted) {
          setExpenses(e);
          setSavings(s);
          setPlan(p);
          setComparison(c);
        }
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [monthId],
  );

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, [load]);

  const mandatoryTotal = useMemo(
    () =>
      sumMoneyAmounts(
        expenses.filter((x) => x.expense_type === "mandatory").map((x) => moneyAmount(x.amount)),
      ),
    [expenses],
  );
  const otherExpenseTotal = useMemo(
    () =>
      sumMoneyAmounts(
        expenses.filter((x) => x.expense_type !== "mandatory").map((x) => moneyAmount(x.amount)),
      ),
    [expenses],
  );
  const savingsTotal = useMemo(
    () => sumMoneyAmounts(savings.map((x) => moneyAmount(x.amount))),
    [savings],
  );
  const plannedTotal = useMemo(
    () => sumMoneyAmounts(plan.map((x) => moneyAmount(x.planned_amount))),
    [plan],
  );

  async function addExpense(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!expCategory.trim() || !normalizeMoneyInput(expAmount)) {
        throw new Error("Категория и сумма обязательны");
      }
      await createExpense({
        reporting_month_id: monthId,
        category: expCategory.trim(),
        amount: rub(expAmount),
        expense_type: expType,
        notes: expNotes.trim() || null,
      });
      setExpCategory("");
      setExpAmount("");
      setExpNotes("");
      setExpenseDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveExpenseEdit() {
    if (editingExpenseId == null || !editExpense) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (!editExpense.category.trim() || !normalizeMoneyInput(editExpense.amount)) {
        throw new Error("Категория и сумма обязательны");
      }
      await updateExpense(editingExpenseId, {
        category: editExpense.category.trim(),
        amount: rub(editExpense.amount),
        expense_type: editExpense.expense_type,
        notes: editExpense.notes.trim() || null,
      });
      setEditingExpenseId(null);
      setEditExpense(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveSavingEdit() {
    if (editingSavingId == null || !editSaving) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (!editSaving.destination.trim() || !normalizeMoneyInput(editSaving.amount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      await updateSaving(editingSavingId, {
        destination: editSaving.destination.trim(),
        amount: rub(editSaving.amount),
        notes: editSaving.notes.trim() || null,
      });
      setEditingSavingId(null);
      setEditSaving(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addSaving(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!savDest.trim() || !normalizeMoneyInput(savAmount)) {
        throw new Error("Назначение и сумма обязательны");
      }
      await createSaving({
        reporting_month_id: monthId,
        destination: savDest.trim(),
        amount: rub(savAmount),
        notes: savNotes.trim() || null,
      });
      setSavDest("");
      setSavAmount("");
      setSavNotes("");
      setSavingDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addPlan(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!planCategory.trim() || !normalizeMoneyInput(planAmount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      await createPlannedBudget({
        reporting_month_id: monthId,
        category: planCategory.trim(),
        planned_amount: rub(planAmount),
        expense_type: planType,
        notes: planNotes.trim() || null,
      });
      setPlanCategory("");
      setPlanAmount("");
      setPlanNotes("");
      setPlanDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePlanEdit() {
    if (editingPlanId == null || !editPlan) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (!editPlan.category.trim() || !normalizeMoneyInput(editPlan.planned_amount)) {
        throw new Error("Категория и сумма плана обязательны");
      }
      await updatePlannedBudget(editingPlanId, {
        category: editPlan.category.trim(),
        planned_amount: rub(editPlan.planned_amount),
        expense_type: editPlan.expense_type,
        notes: editPlan.notes.trim() || null,
      });
      setEditingPlanId(null);
      setEditPlan(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем бюджет…" inline />;
  if (error) return <ErrorState description={error} inline title="Не удалось загрузить бюджет" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={<Badge>обязательные {formatMoney(mandatoryTotal)}</Badge>}
        label="Бюджет"
        title="Расходы"
      >
        {expenses.length === 0 ? (
          <EmptyState description="Расходов пока нет." inline title="Пусто" />
        ) : (
          <Table className="month-budget-table">
            <thead>
              <tr>
                <Th>Категория</Th>
                <Th>Тип</Th>
                <Th numeric>Сумма</Th>
                <Th className="month-budget-table__notes">Комментарий</Th>
                <Th className="month-budget-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {expenses.map((row) => {
                const editing = editingExpenseId === row.id && editExpense;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Категория расхода"
                          onChange={(e) =>
                            setEditExpense({ ...editExpense, category: e.target.value })
                          }
                          value={editExpense.category}
                        />
                      ) : (
                        row.category
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          aria-label="Тип расхода"
                          onChange={(e) =>
                            setEditExpense({ ...editExpense, expense_type: e.target.value })
                          }
                          value={editExpense.expense_type}
                        >
                          <option value="mandatory">Обязательный</option>
                          <option value="comfortable">Комфортный</option>
                          <option value="other">Прочее</option>
                        </Select>
                      ) : (
                        <span
                          className={
                            row.expense_type === "mandatory"
                              ? "badge badge--closed"
                              : "badge badge--draft"
                          }
                        >
                          {labelOf(EXPENSE_TYPE_LABELS, row.expense_type)}
                        </span>
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Сумма расхода"
                          className="input--money"
                          onChange={(e) =>
                            setEditExpense({ ...editExpense, amount: e.target.value })
                          }
                          value={editExpense.amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.amount))
                      )}
                    </Td>
                    <Td className="month-budget-table__notes">
                      {editing ? (
                        <Input
                          aria-label="Комментарий расхода"
                          onChange={(e) =>
                            setEditExpense({ ...editExpense, notes: e.target.value })
                          }
                          value={editExpense.notes}
                        />
                      ) : (
                        <span className="muted tiny">{row.notes ?? "—"}</span>
                      )}
                    </Td>
                    <Td className="month-budget-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveExpenseEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingExpenseId(null);
                                setEditExpense(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для расхода «${row.category}»`}>
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
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelExpense(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Обязательные: <strong>{formatMoney(mandatoryTotal)}</strong>
          </span>
          <span>
            Комфортные и прочие: <strong>{formatMoney(otherExpenseTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addExpense}>
            <div className="editor-grid">
              <Field htmlFor="exp-cat" label="Категория расхода">
                <Input
                  id="exp-cat"
                  onChange={(e) => {
                    setExpCategory(e.target.value);
                    setExpenseDraftTouched(true);
                  }}
                  required
                  value={expCategory}
                />
              </Field>
              <Field htmlFor="exp-type" label="Тип расхода">
                <Select
                  id="exp-type"
                  onChange={(e) => {
                    setExpType(e.target.value);
                    setExpenseDraftTouched(true);
                  }}
                  value={expType}
                >
                  <option value="mandatory">Обязательный</option>
                  <option value="comfortable">Комфортный</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="exp-amt" label="Сумма расхода">
                <Input
                  className="input--money"
                  id="exp-amt"
                  onChange={(e) => {
                    setExpAmount(e.target.value);
                    setExpenseDraftTouched(true);
                  }}
                  required
                  value={expAmount}
                />
              </Field>
              <Field htmlFor="exp-notes" label="Комментарий расхода">
                <Input
                  id="exp-notes"
                  onChange={(e) => {
                    setExpNotes(e.target.value);
                    setExpenseDraftTouched(true);
                  }}
                  value={expNotes}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить расход
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>план {formatMoney(plannedTotal)}</Badge>}
        label="Бюджет"
        title="План расходов"
      >
        <details className="field-details">
          <summary>О плане</summary>
          <p>
            План — это намерение, а не факт. Фактические расходы выше не считаются бюджетом
            автоматически. Сопоставление ниже группирует план и факт по точной паре «категория +
            тип»; одинаковые строки суммируются.
          </p>
        </details>
        {plan.length === 0 ? (
          <EmptyState
            description="Плана нет — это нормально, закрытию месяца он не нужен."
            inline
            title="Пусто"
          />
        ) : (
          <Table className="month-budget-table">
            <thead>
              <tr>
                <Th>Категория</Th>
                <Th>Тип</Th>
                <Th numeric>Сумма плана</Th>
                <Th className="month-budget-table__notes">Комментарий</Th>
                <Th className="month-budget-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {plan.map((row) => {
                const editing = editingPlanId === row.id && editPlan;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Категория плана"
                          onChange={(e) => setEditPlan({ ...editPlan, category: e.target.value })}
                          value={editPlan.category}
                        />
                      ) : (
                        row.category
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          aria-label="Тип плана"
                          onChange={(e) =>
                            setEditPlan({ ...editPlan, expense_type: e.target.value })
                          }
                          value={editPlan.expense_type}
                        >
                          <option value="mandatory">Обязательный</option>
                          <option value="comfortable">Комфортный</option>
                          <option value="other">Прочее</option>
                        </Select>
                      ) : (
                        <span
                          className={
                            row.expense_type === "mandatory"
                              ? "badge badge--closed"
                              : "badge badge--draft"
                          }
                        >
                          {labelOf(EXPENSE_TYPE_LABELS, row.expense_type)}
                        </span>
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Сумма плана"
                          className="input--money"
                          onChange={(e) =>
                            setEditPlan({ ...editPlan, planned_amount: e.target.value })
                          }
                          value={editPlan.planned_amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.planned_amount))
                      )}
                    </Td>
                    <Td className="month-budget-table__notes">
                      {editing ? (
                        <Input
                          aria-label="Комментарий плана"
                          onChange={(e) => setEditPlan({ ...editPlan, notes: e.target.value })}
                          value={editPlan.notes}
                        />
                      ) : (
                        <span className="muted tiny">{row.notes ?? "—"}</span>
                      )}
                    </Td>
                    <Td className="month-budget-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSavePlanEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingPlanId(null);
                                setEditPlan(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для плана «${row.category}»`}>
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
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelPlan(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Итого план: <strong>{formatMoney(plannedTotal)}</strong>
          </span>
        </div>
        {comparison.length > 0 ? (
          <Table className="month-budget-table">
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
                  <Td numeric>{formatMoney(moneyAmount(row.planned))}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.actual))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : null}
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addPlan}>
            <div className="editor-grid">
              <Field htmlFor="plan-cat" label="Категория плана">
                <Input
                  id="plan-cat"
                  onChange={(e) => {
                    setPlanCategory(e.target.value);
                    setPlanDraftTouched(true);
                  }}
                  required
                  value={planCategory}
                />
              </Field>
              <Field htmlFor="plan-type" label="Тип плана">
                <Select
                  id="plan-type"
                  onChange={(e) => {
                    setPlanType(e.target.value);
                    setPlanDraftTouched(true);
                  }}
                  value={planType}
                >
                  <option value="mandatory">Обязательный</option>
                  <option value="comfortable">Комфортный</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="plan-amt" label="Сумма плана">
                <Input
                  className="input--money"
                  id="plan-amt"
                  onChange={(e) => {
                    setPlanAmount(e.target.value);
                    setPlanDraftTouched(true);
                  }}
                  required
                  value={planAmount}
                />
              </Field>
              <Field htmlFor="plan-notes" label="Комментарий плана">
                <Input
                  id="plan-notes"
                  onChange={(e) => {
                    setPlanNotes(e.target.value);
                    setPlanDraftTouched(true);
                  }}
                  value={planNotes}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить в план
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>отложено {formatMoney(savingsTotal)}</Badge>}
        label="Бюджет"
        title="Откладывание"
      >
        <details className="field-details">
          <summary>О накоплениях</summary>
          <p>Отложенные суммы учитываются отдельно от расходов и не являются типом расхода.</p>
        </details>
        {savings.length === 0 ? (
          <EmptyState description="Откладываний нет." inline title="Пусто" />
        ) : (
          <Table className="month-budget-table">
            <thead>
              <tr>
                <Th>Куда</Th>
                <Th numeric>Сумма</Th>
                <Th className="month-budget-table__notes">Комментарий</Th>
                <Th className="month-budget-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {savings.map((row) => {
                const editing = editingSavingId === row.id && editSaving;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Назначение"
                          onChange={(e) =>
                            setEditSaving({ ...editSaving, destination: e.target.value })
                          }
                          value={editSaving.destination}
                        />
                      ) : (
                        row.destination
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Сумма к откладыванию"
                          className="input--money"
                          onChange={(e) => setEditSaving({ ...editSaving, amount: e.target.value })}
                          value={editSaving.amount}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.amount))
                      )}
                    </Td>
                    <Td className="month-budget-table__notes">
                      {editing ? (
                        <Input
                          aria-label="Комментарий к откладыванию"
                          onChange={(e) => setEditSaving({ ...editSaving, notes: e.target.value })}
                          value={editSaving.notes}
                        />
                      ) : (
                        <span className="muted tiny">{row.notes ?? "—"}</span>
                      )}
                    </Td>
                    <Td className="month-budget-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveSavingEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingSavingId(null);
                                setEditSaving(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для откладывания «${row.destination}»`}>
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
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelSaving(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Итого отложено: <strong>{formatMoney(savingsTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addSaving}>
            <div className="editor-grid">
              <Field htmlFor="sav-dest" label="Назначение">
                <Input
                  id="sav-dest"
                  onChange={(e) => {
                    setSavDest(e.target.value);
                    setSavingDraftTouched(true);
                  }}
                  required
                  value={savDest}
                />
              </Field>
              <Field htmlFor="sav-amt" label="Сумма к откладыванию">
                <Input
                  className="input--money"
                  id="sav-amt"
                  onChange={(e) => {
                    setSavAmount(e.target.value);
                    setSavingDraftTouched(true);
                  }}
                  required
                  value={savAmount}
                />
              </Field>
              <Field htmlFor="sav-notes" label="Комментарий к откладыванию">
                <Input
                  id="sav-notes"
                  onChange={(e) => {
                    setSavNotes(e.target.value);
                    setSavingDraftTouched(true);
                  }}
                  value={savNotes}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить откладывание
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delExpense ? `Удалить расход «${delExpense.category}»?` : ""}
        onCancel={() => setDelExpense(null)}
        onConfirm={() => {
          if (!delExpense) return;
          setBusy(true);
          void deleteExpense(delExpense.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelExpense(null);
            });
        }}
        open={delExpense !== null}
        title="Удалить расход?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delSaving ? `Удалить откладывание «${delSaving.destination}»?` : ""}
        onCancel={() => setDelSaving(null)}
        onConfirm={() => {
          if (!delSaving) return;
          setBusy(true);
          void deleteSaving(delSaving.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelSaving(null);
            });
        }}
        open={delSaving !== null}
        title="Удалить откладывание?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delPlan ? `Удалить план «${delPlan.category}»?` : ""}
        onCancel={() => setDelPlan(null)}
        onConfirm={() => {
          if (!delPlan) return;
          setBusy(true);
          void deletePlannedBudget(delPlan.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelPlan(null);
            });
        }}
        open={delPlan !== null}
        title="Удалить план?"
      />
    </div>
  );
}
