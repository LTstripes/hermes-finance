import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import { createExpense, deleteExpense, listExpenses } from "../api/expenses";
import { createSaving, deleteSaving, listSavings } from "../api/savings";
import type { ExpenseEntry, SavingAllocation } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "./ui";
import { formatMoney } from "../lib/format";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type Props = { monthId: number; readOnly: boolean };

export function MonthBudgetSection({ monthId, readOnly }: Props) {
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
  const [delExpense, setDelExpense] = useState<ExpenseEntry | null>(null);
  const [delSaving, setDelSaving] = useState<SavingAllocation | null>(null);

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
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем бюджет…" inline />;
  if (error) return <EmptyState description={error} inline title="Ошибка бюджета" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={<Badge>mandatory {formatMoney(mandatoryTotal)}</Badge>}
        label="Бюджет"
        title="Расходы"
      >
        {expenses.length === 0 ? (
          <EmptyState description="Расходов пока нет." inline title="Пусто" />
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
              {expenses.map((row) => (
                <tr key={row.id}>
                  <Td>{row.category}</Td>
                  <Td>
                    <span
                      className={
                        row.expense_type === "mandatory"
                          ? "badge badge--closed"
                          : "badge badge--draft"
                      }
                    >
                      {row.expense_type}
                    </span>
                  </Td>
                  <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
                  <Td>
                    <span className="muted tiny">{row.notes ?? "—"}</span>
                  </Td>
                  <Td>
                    <Button
                      disabled={busy || readOnly}
                      onClick={() => setDelExpense(row)}
                      size="sm"
                      type="button"
                      variant="danger"
                    >
                      Удал.
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Mandatory: <strong>{formatMoney(mandatoryTotal)}</strong>
          </span>
          <span>
            Comfortable/other: <strong>{formatMoney(otherExpenseTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addExpense}>
            <div className="editor-grid">
              <Field htmlFor="exp-cat" label="Категория расхода">
                <Input
                  id="exp-cat"
                  onChange={(e) => setExpCategory(e.target.value)}
                  required
                  value={expCategory}
                />
              </Field>
              <Field htmlFor="exp-type" label="Тип расхода">
                <Select id="exp-type" onChange={(e) => setExpType(e.target.value)} value={expType}>
                  <option value="mandatory">mandatory</option>
                  <option value="comfortable">comfortable</option>
                  <option value="other">other</option>
                </Select>
              </Field>
              <Field htmlFor="exp-amt" label="Сумма расхода">
                <Input
                  className="input--money"
                  id="exp-amt"
                  onChange={(e) => setExpAmount(e.target.value)}
                  required
                  value={expAmount}
                />
              </Field>
              <Field htmlFor="exp-notes" label="Комментарий расхода">
                <Input
                  id="exp-notes"
                  onChange={(e) => setExpNotes(e.target.value)}
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
        action={<Badge>savings {formatMoney(savingsTotal)}</Badge>}
        label="Бюджет"
        title="Откладывание"
      >
        <p className="muted field-hint">
          Saving allocations — отдельно от расходов (не expense_type).
        </p>
        {savings.length === 0 ? (
          <EmptyState description="Откладываний нет." inline title="Пусто" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Куда</Th>
                <Th numeric>Сумма</Th>
                <Th>Комментарий</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {savings.map((row) => (
                <tr key={row.id}>
                  <Td>{row.destination}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
                  <Td>
                    <span className="muted tiny">{row.notes ?? "—"}</span>
                  </Td>
                  <Td>
                    <Button
                      disabled={busy || readOnly}
                      onClick={() => setDelSaving(row)}
                      size="sm"
                      type="button"
                      variant="danger"
                    >
                      Удал.
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="totals-bar">
          <span>
            Итого savings: <strong>{formatMoney(savingsTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addSaving}>
            <div className="editor-grid">
              <Field htmlFor="sav-dest" label="Назначение">
                <Input
                  id="sav-dest"
                  onChange={(e) => setSavDest(e.target.value)}
                  required
                  value={savDest}
                />
              </Field>
              <Field htmlFor="sav-amt" label="Сумма savings">
                <Input
                  className="input--money"
                  id="sav-amt"
                  onChange={(e) => setSavAmount(e.target.value)}
                  required
                  value={savAmount}
                />
              </Field>
              <Field htmlFor="sav-notes" label="Комментарий savings">
                <Input
                  id="sav-notes"
                  onChange={(e) => setSavNotes(e.target.value)}
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
        description={delSaving ? `Удалить savings «${delSaving.destination}»?` : ""}
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
        title="Удалить savings?"
      />
    </div>
  );
}
