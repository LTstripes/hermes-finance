import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { createAccount, listAccounts } from "../api/accounts";
import {
  createCashBalance,
  deleteCashBalance,
  getCashTotal,
  listCashBalances,
  updateCashBalance,
} from "../api/cash";
import { formatApiError } from "../api/client";
import { createDeposit, deleteDeposit, listDeposits, updateDeposit } from "../api/deposits";
import type { Account, CashBalance, CashTotal, DepositSnapshot } from "../api/types";
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
import { ACCOUNT_TYPE_LABELS, DEPOSIT_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type MonthAssetsSectionProps = {
  monthId: number;
  readOnly: boolean;
  onDirtyChange?: (dirty: boolean) => void;
};

type DepositDraft = {
  name: string;
  account_id: string;
  deposit_type: string;
  balance: string;
  annual_rate: string;
  actual_interest: string;
};

type CashDraft = {
  name: string;
  amount: string;
  include_in_capital: boolean;
};

const emptyDeposit = (): DepositDraft => ({
  name: "",
  account_id: "",
  deposit_type: "deposit",
  balance: "",
  annual_rate: "12.00",
  actual_interest: "0.00",
});

const emptyCash = (): CashDraft => ({
  name: "",
  amount: "",
  include_in_capital: true,
});

export function MonthAssetsSection({ monthId, readOnly, onDirtyChange }: MonthAssetsSectionProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [deposits, setDeposits] = useState<DepositSnapshot[]>([]);
  const [cashRows, setCashRows] = useState<CashBalance[]>([]);
  const [cashTotal, setCashTotal] = useState<CashTotal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [depositDraft, setDepositDraft] = useState<DepositDraft>(emptyDeposit);
  const [cashDraft, setCashDraft] = useState<CashDraft>(emptyCash);
  const [depositDraftTouched, setDepositDraftTouched] = useState(false);
  const [cashDraftTouched, setCashDraftTouched] = useState(false);
  const [editingDepositId, setEditingDepositId] = useState<number | null>(null);
  const [editDeposit, setEditDeposit] = useState<DepositDraft | null>(null);
  const [pendingDeleteDeposit, setPendingDeleteDeposit] = useState<DepositSnapshot | null>(null);
  const [pendingDeleteCash, setPendingDeleteCash] = useState<CashBalance | null>(null);

  const localDirty = depositDraftTouched || cashDraftTouched || editingDepositId !== null;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [accs, deps, cash, total] = await Promise.all([
          listAccounts(signal),
          listDeposits(monthId, signal),
          listCashBalances(monthId, signal),
          getCashTotal(monthId, signal),
        ]);
        if (signal?.aborted) {
          return;
        }
        setAccounts(accs);
        setDeposits(deps);
        setCashRows(cash);
        setCashTotal(total);
        const depositAccounts = accs.filter(
          (a) => a.account_type === "deposit" || a.account_type === "savings",
        );
        if (depositAccounts.length > 0) {
          setDepositDraft((prev) =>
            prev.account_id ? prev : { ...prev, account_id: String(depositAccounts[0].id) },
          );
        }
      } catch (err) {
        if (!signal?.aborted) {
          setError(formatApiError(err));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [monthId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const depositAccounts = useMemo(
    () =>
      accounts.filter(
        (a) =>
          a.status === "active" &&
          (a.account_type === "deposit" ||
            a.account_type === "savings" ||
            a.account_type === "other" ||
            a.account_type === "brokerage"),
      ),
    [accounts],
  );

  const depositTotals = useMemo(() => {
    const balances = deposits.map((d) => moneyAmount(d.balance));
    const expected = deposits.map((d) => moneyAmount(d.expected_monthly_interest));
    const actual = deposits.map((d) => moneyAmount(d.actual_interest_received));
    return {
      balance: sumMoneyAmounts(balances),
      expected: sumMoneyAmounts(expected),
      actual: sumMoneyAmounts(actual),
    };
  }, [deposits]);

  async function ensureDepositAccount(): Promise<number> {
    if (depositAccounts.length > 0) {
      return depositAccounts[0].id;
    }
    const created = await createAccount({
      name: "Депозиты",
      account_type: "deposit",
      status: "active",
      include_in_capital: true,
      include_in_returns: true,
    });
    setAccounts((prev) => [...prev, created]);
    return created.id;
  }

  async function handleCreateDeposit(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    setBusy(true);
    try {
      if (!normalizeMoneyInput(depositDraft.balance)) {
        throw new Error("Укажи баланс вклада");
      }
      if (!depositDraft.name.trim()) {
        throw new Error("Укажи название вклада");
      }
      let accountId = Number(depositDraft.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) {
        accountId = await ensureDepositAccount();
      }
      await createDeposit({
        reporting_month_id: monthId,
        account_id: accountId,
        name: depositDraft.name.trim(),
        deposit_type: depositDraft.deposit_type,
        balance: rub(depositDraft.balance),
        annual_rate: depositDraft.annual_rate.trim() || "0.00",
        actual_interest_received: rub(
          depositDraft.actual_interest.trim() === "" ? "0" : depositDraft.actual_interest,
        ),
      });
      setDepositDraft(() => ({ ...emptyDeposit(), account_id: String(accountId) }));
      setDepositDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDepositEdit() {
    if (editingDepositId == null || !editDeposit) {
      return;
    }
    const current = deposits.find((d) => d.id === editingDepositId);
    if (!current) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await updateDeposit(
        editingDepositId,
        {
          name: editDeposit.name.trim(),
          deposit_type: editDeposit.deposit_type,
          balance: rub(editDeposit.balance),
          annual_rate: editDeposit.annual_rate.trim() || "0.00",
          actual_interest_received: rub(
            editDeposit.actual_interest.trim() === "" ? "0" : editDeposit.actual_interest,
          ),
        },
        current.updated_at,
      );
      setEditingDepositId(null);
      setEditDeposit(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteDeposit() {
    if (!pendingDeleteDeposit) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteDeposit(pendingDeleteDeposit.id);
      setPendingDeleteDeposit(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDeleteDeposit(null);
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateCash(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    setBusy(true);
    try {
      if (!cashDraft.name.trim()) {
        throw new Error("Укажи название денежной позиции");
      }
      if (!normalizeMoneyInput(cashDraft.amount)) {
        throw new Error("Укажи сумму");
      }
      await createCashBalance({
        reporting_month_id: monthId,
        name: cashDraft.name.trim(),
        amount: rub(cashDraft.amount),
        include_in_capital: cashDraft.include_in_capital,
      });
      setCashDraft(emptyCash());
      setCashDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCash() {
    if (!pendingDeleteCash) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteCashBalance(pendingDeleteCash.id);
      setPendingDeleteCash(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDeleteCash(null);
    } finally {
      setBusy(false);
    }
  }

  async function toggleCashCapital(row: CashBalance) {
    if (readOnly) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await updateCashBalance(row.id, { include_in_capital: !row.include_in_capital });
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <LoadingState description="Загружаем депозиты и наличные…" inline />;
  }

  if (error) {
    return <ErrorState description={error} inline title="Не удалось загрузить активы" />;
  }

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={
          <Badge>
            итог {formatMoney(depositTotals.balance)} · {deposits.length} шт.
          </Badge>
        }
        label="Активы"
        title="Депозиты"
      >
        {deposits.length === 0 ? (
          <EmptyState
            description="Депозитов пока нет — добавь вклад формой ниже."
            inline
            title="Пусто"
          />
        ) : (
          <Table className="month-deposits-table">
            <thead>
              <tr>
                <Th>Название</Th>
                <Th>Тип</Th>
                <Th numeric>Баланс</Th>
                <Th numeric>Ставка %</Th>
                <Th numeric>Прогноз / мес</Th>
                <Th numeric>Получено</Th>
                <Th className="month-deposits-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {deposits.map((row) => {
                const editing = editingDepositId === row.id && editDeposit;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          value={editDeposit.name}
                          onChange={(e) => setEditDeposit({ ...editDeposit, name: e.target.value })}
                        />
                      ) : (
                        row.name
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          value={editDeposit.deposit_type}
                          onChange={(e) =>
                            setEditDeposit({ ...editDeposit, deposit_type: e.target.value })
                          }
                        >
                          <option value="deposit">Депозит</option>
                          <option value="savings">Накопления</option>
                        </Select>
                      ) : (
                        labelOf(DEPOSIT_TYPE_LABELS, row.deposit_type)
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDeposit.balance}
                          onChange={(e) =>
                            setEditDeposit({ ...editDeposit, balance: e.target.value })
                          }
                        />
                      ) : (
                        formatMoney(moneyAmount(row.balance))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDeposit.annual_rate}
                          onChange={(e) =>
                            setEditDeposit({ ...editDeposit, annual_rate: e.target.value })
                          }
                        />
                      ) : (
                        row.annual_rate
                      )}
                    </Td>
                    <Td numeric>
                      <span className="muted">
                        {formatMoney(moneyAmount(row.expected_monthly_interest))}
                      </span>
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDeposit.actual_interest}
                          onChange={(e) =>
                            setEditDeposit({
                              ...editDeposit,
                              actual_interest: e.target.value,
                            })
                          }
                        />
                      ) : (
                        formatMoney(moneyAmount(row.actual_interest_received))
                      )}
                    </Td>
                    <Td className="month-deposits-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveDepositEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingDepositId(null);
                                setEditDeposit(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для вклада «${row.name}»`}>
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingDepositId(row.id);
                                setEditDeposit({
                                  name: row.name,
                                  account_id: String(row.account_id),
                                  deposit_type: row.deposit_type,
                                  balance: moneyAmount(row.balance),
                                  annual_rate: row.annual_rate,
                                  actual_interest: moneyAmount(row.actual_interest_received),
                                });
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setPendingDeleteDeposit(row)}
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
            Баланс: <strong>{formatMoney(depositTotals.balance)}</strong>
          </span>
          <span>
            Прогноз / мес: <strong>{formatMoney(depositTotals.expected)}</strong>
          </span>
          <span>
            Получено: <strong>{formatMoney(depositTotals.actual)}</strong>
          </span>
        </div>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateDeposit}>
            <p className="panel__label" style={{ marginBottom: 0 }}>
              Новый вклад
            </p>
            <div className="editor-grid">
              <Field htmlFor="dep-name" label="Название вклада">
                <Input
                  id="dep-name"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, name: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  required
                  value={depositDraft.name}
                />
              </Field>
              <Field htmlFor="dep-type" label="Тип">
                <Select
                  id="dep-type"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, deposit_type: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  value={depositDraft.deposit_type}
                >
                  <option value="deposit">Депозит</option>
                  <option value="savings">Накопления</option>
                </Select>
              </Field>
              <Field htmlFor="dep-account" label="Счёт">
                <Select
                  id="dep-account"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, account_id: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  value={depositDraft.account_id}
                >
                  <option value="">авто (создать «Депозиты»)</option>
                  {depositAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({labelOf(ACCOUNT_TYPE_LABELS, a.account_type)})
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="dep-balance" label="Баланс вклада">
                <Input
                  className="input--money"
                  id="dep-balance"
                  inputMode="decimal"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, balance: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  required
                  value={depositDraft.balance}
                />
              </Field>
              <Field htmlFor="dep-rate" label="Годовая ставка %">
                <Input
                  className="input--money"
                  id="dep-rate"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, annual_rate: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  value={depositDraft.annual_rate}
                />
              </Field>
              <Field htmlFor="dep-actual" label="Факт. процент">
                <Input
                  className="input--money"
                  id="dep-actual"
                  onChange={(e) => {
                    setDepositDraft({ ...depositDraft, actual_interest: e.target.value });
                    setDepositDraftTouched(true);
                  }}
                  value={depositDraft.actual_interest}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить вклад
            </Button>
            <details className="field-details">
              <summary>О прогнозе процентов</summary>
              <p>
                Прогноз и фактическое начисление показываются отдельно; прогноз не является
                обещанием выплаты.
              </p>
            </details>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={
          <Badge>
            наличные {formatMoney(moneyAmount(cashTotal?.total))} · в капитале{" "}
            {formatMoney(moneyAmount(cashTotal?.total_in_capital))}
          </Badge>
        }
        label="Активы"
        title="Денежные средства"
      >
        {cashRows.length === 0 ? (
          <EmptyState description="Наличных позиций нет." inline title="Пусто" />
        ) : (
          <Table className="month-cash-table">
            <thead>
              <tr>
                <Th>Название</Th>
                <Th numeric>Сумма</Th>
                <Th>В капитале</Th>
                <Th className="month-cash-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {cashRows.map((row) => (
                <tr key={row.id}>
                  <Td>{row.name}</Td>
                  <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
                  <Td>
                    <Button
                      disabled={busy || readOnly}
                      onClick={() => void toggleCashCapital(row)}
                      size="sm"
                      type="button"
                    >
                      {row.include_in_capital ? "да" : "нет"}
                    </Button>
                  </Td>
                  <Td className="month-cash-table__actions">
                    <OverflowMenu label={`Действия для денежной позиции «${row.name}»`}>
                      <OverflowMenuItem
                        danger
                        disabled={busy || readOnly}
                        onClick={() => setPendingDeleteCash(row)}
                      >
                        Удалить
                      </OverflowMenuItem>
                    </OverflowMenu>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}

        <div className="totals-bar">
          <span>
            Всего наличных: <strong>{formatMoney(moneyAmount(cashTotal?.total) || "0.00")}</strong>
          </span>
          <span>
            В ликвидном капитале:{" "}
            <strong>{formatMoney(moneyAmount(cashTotal?.total_in_capital) || "0.00")}</strong>
          </span>
        </div>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateCash}>
            <p className="panel__label section-form-label">Новая денежная позиция</p>
            <div className="editor-grid">
              <Field htmlFor="cash-name" label="Название денежной позиции">
                <Input
                  id="cash-name"
                  onChange={(e) => {
                    setCashDraft({ ...cashDraft, name: e.target.value });
                    setCashDraftTouched(true);
                  }}
                  required
                  value={cashDraft.name}
                />
              </Field>
              <Field htmlFor="cash-amount" label="Сумма наличных">
                <Input
                  className="input--money"
                  id="cash-amount"
                  inputMode="decimal"
                  onChange={(e) => {
                    setCashDraft({ ...cashDraft, amount: e.target.value });
                    setCashDraftTouched(true);
                  }}
                  required
                  value={cashDraft.amount}
                />
              </Field>
            </div>
            <label className="check-row">
              <input
                checked={cashDraft.include_in_capital}
                onChange={(e) => {
                  setCashDraft({ ...cashDraft, include_in_capital: e.target.checked });
                  setCashDraftTouched(true);
                }}
                type="checkbox"
              />
              Включать в ликвидный капитал
            </label>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить денежную позицию
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={pendingDeleteDeposit ? `Удалить вклад «${pendingDeleteDeposit.name}»?` : ""}
        onCancel={() => setPendingDeleteDeposit(null)}
        onConfirm={() => void handleDeleteDeposit()}
        open={pendingDeleteDeposit !== null}
        title="Удалить вклад?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDeleteCash ? `Удалить денежную позицию «${pendingDeleteCash.name}»?` : ""
        }
        onCancel={() => setPendingDeleteCash(null)}
        onConfirm={() => void handleDeleteCash()}
        open={pendingDeleteCash !== null}
        title="Удалить денежную позицию?"
      />
    </div>
  );
}
