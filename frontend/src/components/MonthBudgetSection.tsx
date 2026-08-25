import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { createExpense, deleteExpense, listExpenses, updateExpense } from "../api/expenses";
import { createSaving, deleteSaving, listSavings, updateSaving } from "../api/savings";
import type { ExpenseEntry, SavingAllocation } from "../api/types";
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

export function MonthBudgetSection({ monthId, readOnly, onDirtyChange }: Props) {
  const [expenses, setExpenses] = useState<ExpenseEntry[]>([]);
  const [savings, setSavings] = useState<SavingAllocation[]>([]);
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
  const [expenseDraftTouched, setExpenseDraftTouched] = useState(false);
  const [savingDraftTouched, setSavingDraftTouched] = useState(false);
  const [delExpense, setDelExpense] = useState<ExpenseEntry | null>(null);
  const [delSaving, setDelSaving] = useState<SavingAllocation | null>(null);
  const [editingExpenseId, setEditingExpenseId] = useState<number | null>(null);
  const [editExpense, setEditExpense] = useState<ExpenseDraft | null>(null);
  const [editingSavingId, setEditingSavingId] = useState<number | null>(null);
  const [editSaving, setEditSaving] = useState<SavingDraft | null>(null);

  const localDirty =
    expenseDraftTouched ||
    savingDraftTouched ||
    editingExpenseId !== null ||
    editingSavingId !== null;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [e, s] = await Promise.all([
          listExpenses(monthId, signal),
          listSavings(monthId, signal),
        ]);
        if (!signal?.aborted) {
          setExpenses(e);
          setSavings(s);
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
    </div>
  );
}
