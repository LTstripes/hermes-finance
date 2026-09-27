import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { createAccount, listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import {
  createCashBalance,
  deleteCashBalance,
  getCashTotal,
  listCashBalances,
  updateCashBalance,
} from "../api/cash";
import { getDashboard } from "../api/dashboard";
import { createDeposit, deleteDeposit, listDeposits, updateDeposit } from "../api/deposits";
import { listDebts } from "../api/debts";
import type { CashBalance, DepositSnapshot, MoneyValue } from "../api/types";
import { LinkedPairContext } from "../components/LinkedPairContext";
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
} from "../components/ui";
import { formatDate, formatMonth, formatMoney } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, DEPOSIT_TYPE_LABELS, SOURCE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, sumMoneyAmounts } from "../lib/money";
import { queryKeys } from "../queryClient";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import styles from "./UiV2MonthAssets.module.css";

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

const DIRTY_SECTION = "assets";

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

/** Visible rejection for a mismatched list — never filtered into an "empty" snapshot. */
const DEPOSITS_FOREIGN_MESSAGE =
  "Ответ API по вкладам принадлежит другому месяцу: список отклонён и не показывается пустым снимком.";
const CASH_FOREIGN_MESSAGE =
  "Ответ API по денежным позициям принадлежит другому месяцу: список отклонён и не показывается пустым снимком.";
/** Row mutation confirmed, aggregate not: kept apart on purpose (Integrator B1). */
const CASH_TOTAL_WARNING =
  "Итог наличных не перечитан: прежнее значение не показывается как текущее. Строки подтверждаются отдельным перечитыванием списка.";

/** API currency code → suffix used by formatMoney; unknown codes stay verbatim. */
function currencySuffix(currency: string | null | undefined): string {
  const code = (currency ?? "RUB").toUpperCase();
  return code === "RUB" ? "₽" : code;
}

function moneyValue(amount: string, currency: string): MoneyValue {
  const normalized = normalizeMoneyInput(amount);
  if (normalized == null) {
    throw new Error(`Некорректная сумма: ${amount.trim() || "пусто"}`);
  }
  return { amount: normalized, currency };
}

function sameMoney(left: string | null | undefined, right: string | null | undefined): boolean {
  const a = left == null ? null : normalizeMoneyInput(left);
  const b = right == null ? null : normalizeMoneyInput(right);
  return a !== null && b !== null && a === b;
}

/** A total is rendered only when every component amount is valid; otherwise — never a zero. */
function totalText(value: string | null, currency: string | null | undefined): string {
  return value === null ? "—" : formatMoney(value, { currency: currencySuffix(currency) });
}

/**
 * A response carrying any foreign-month row is rejected wholesale (Integrator
 * B2): filtering it would turn a mismatched list into an "authoritative"
 * empty snapshot and could falsely confirm a deletion.
 */
function requireMonthRows<T extends { reporting_month_id: number }>(
  rows: T[],
  monthId: number,
  label: string,
): T[] {
  if (rows.some((row) => row.reporting_month_id !== monthId)) {
    throw new Error(
      `Ответ списка ${label} принадлежит другому месяцу: перечитывание не подтверждает выбранный снимок.`,
    );
  }
  return rows;
}

/**
 * Native month-editor leaf (#560): month deposits, cash positions and the
 * canonical linked-pair context for the exact month of the editor context.
 * Every read and write is keyed to `context.month.id`; the body remounts when
 * that identity changes so a late response from another month is never shown.
 */
export function UiV2MonthAssetsSection({ context }: { context: MonthEditorContext }) {
  return <MonthAssetsBody key={context.month.id} context={context} />;
}

function MonthAssetsBody({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, setDirty } = context;
  const monthId = month.id;
  const queryClient = useQueryClient();

  const accountsQuery = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const depositsQuery = useQuery({
    queryKey: queryKeys.deposits(monthId),
    queryFn: ({ signal }) => listDeposits(monthId, signal),
  });
  const cashRowsQuery = useQuery({
    queryKey: queryKeys.cashBalances(monthId),
    queryFn: ({ signal }) => listCashBalances(monthId, signal),
  });
  const cashTotalQuery = useQuery({
    queryKey: ["cash-balances", monthId, "total"],
    queryFn: ({ signal }) => getCashTotal(monthId, signal),
  });
  const debtsQuery = useQuery({
    queryKey: queryKeys.debts(monthId),
    queryFn: ({ signal }) => listDebts(monthId, signal),
  });
  const dashboardQuery = useQuery({
    queryKey: queryKeys.dashboard(monthId),
    queryFn: ({ signal }) => getDashboard(monthId, signal),
  });

  const [depositDraft, setDepositDraft] = useState<DepositDraft>(emptyDeposit);
  const [cashDraft, setCashDraft] = useState<CashDraft>(emptyCash);
  const [depositDraftTouched, setDepositDraftTouched] = useState(false);
  const [cashDraftTouched, setCashDraftTouched] = useState(false);
  const [editingDepositId, setEditingDepositId] = useState<number | null>(null);
  const [editDeposit, setEditDeposit] = useState<DepositDraft | null>(null);
  const [pendingDeleteDeposit, setPendingDeleteDeposit] = useState<DepositSnapshot | null>(null);
  const [pendingDeleteCash, setPendingDeleteCash] = useState<CashBalance | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Cash aggregate authority: unconfirmed while a write is in flight or its
  // total readback failed — the pre-write value is never shown as current (B1).
  const [totalUnconfirmed, setTotalUnconfirmed] = useState(false);
  const [totalWarning, setTotalWarning] = useState<string | null>(null);
  const busyRef = useRef(false);
  const operation = useRef(0);

  const localDirty = depositDraftTouched || cashDraftTouched || editingDepositId !== null;

  useEffect(() => setDirty(DIRTY_SECTION, localDirty), [localDirty, setDirty]);
  useEffect(
    () => () => {
      operation.current += 1;
      setDirty(DIRTY_SECTION, false);
    },
    [setDirty],
  );

  const accounts = accountsQuery.data ?? [];
  // A mismatched response is rejected wholesale and visibly (B2); it is never
  // filtered into an empty slice that would look like an empty snapshot.
  const depositsForeign = (depositsQuery.data ?? []).some(
    (row) => row.reporting_month_id !== monthId,
  );
  const cashForeign = (cashRowsQuery.data ?? []).some((row) => row.reporting_month_id !== monthId);
  const depositRows = useMemo(() => depositsQuery.data ?? [], [depositsQuery.data]);
  const cashRows = useMemo(() => cashRowsQuery.data ?? [], [cashRowsQuery.data]);
  const cashTotal =
    cashTotalQuery.data && cashTotalQuery.data.reporting_month_id === monthId
      ? cashTotalQuery.data
      : null;

  const depositAccounts = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.status === "active" &&
          (account.account_type === "deposit" ||
            account.account_type === "savings" ||
            account.account_type === "other" ||
            account.account_type === "brokerage"),
      ),
    [accounts],
  );

  const depositTotals = useMemo(() => {
    // A rejected (foreign) list yields unknown totals — "—", never a computed zero.
    if (depositsForeign)
      return { balance: null, expected: null, actual: null, currency: "RUB", mixed: false };
    const firstCurrency = depositRows[0]?.balance.currency ?? "RUB";
    const balances = depositRows.map((row) => moneyAmount(row.balance));
    const expected = depositRows.map((row) => moneyAmount(row.expected_monthly_interest));
    const actual = depositRows.map((row) => moneyAmount(row.actual_interest_received));
    const allValid = (values: string[]) =>
      values.every((value) => normalizeMoneyInput(value) !== null);
    return {
      balance: allValid(balances) ? sumMoneyAmounts(balances) : null,
      expected: allValid(expected) ? sumMoneyAmounts(expected) : null,
      actual: allValid(actual) ? sumMoneyAmounts(actual) : null,
      currency: firstCurrency,
      mixed: depositRows.some((row) => row.balance.currency !== firstCurrency),
    };
  }, [depositRows, depositsForeign]);

  const defaultAccountId = depositAccounts[0]?.id ?? null;
  const effectiveAccountId =
    depositDraft.account_id || (defaultAccountId === null ? "" : String(defaultAccountId));

  const loading = accountsQuery.isPending || depositsQuery.isPending || cashRowsQuery.isPending;
  const loadError = [accountsQuery, depositsQuery, cashRowsQuery].find((query) => query.isError);

  // Authority of the displayed aggregates: current only after a confirmed read
  // of this month's total. Retained data behind an error, a foreign month, or
  // an unconfirmed post-write refresh renders as "Загружаем…"/«Недоступно» (B1).
  const cashTotalSettling =
    cashTotalQuery.isPending || (totalUnconfirmed && !cashTotalQuery.isError);
  const cashTotalCurrent = cashTotalQuery.isSuccess && !totalUnconfirmed;
  const cashTotalText = cashTotalSettling
    ? "Загружаем…"
    : cashTotal && cashTotalCurrent
      ? formatMoney(moneyAmount(cashTotal.total), {
          currency: currencySuffix(cashTotal.total.currency),
        })
      : "Недоступно";
  const cashInCapitalText = cashTotalSettling
    ? "Загружаем…"
    : cashTotal && cashTotalCurrent
      ? formatMoney(moneyAmount(cashTotal.total_in_capital), {
          currency: currencySuffix(cashTotal.total_in_capital.currency),
        })
      : "Недоступно";

  const debts = debtsQuery.data ?? [];
  const linkedPairs =
    dashboardQuery.data?.summary?.liquid_capital?.linked_pairs ??
    (dashboardQuery.isSuccess ? [] : null);
  let linkedPairError: string | null = null;
  if (debtsQuery.isError) {
    linkedPairError = formatApiError(debtsQuery.error);
  } else if (dashboardQuery.isError) {
    linkedPairError = formatApiError(dashboardQuery.error);
  }

  async function refetchDepositRows(): Promise<DepositSnapshot[]> {
    const result = await depositsQuery.refetch();
    if (!result.isSuccess || !result.data) {
      throw new Error("Список вкладов не удалось перечитать.");
    }
    return requireMonthRows(result.data, monthId, "вкладов");
  }

  async function refetchCashRows(): Promise<CashBalance[]> {
    const result = await cashRowsQuery.refetch();
    if (!result.isSuccess || !result.data) {
      throw new Error("Список денежных позиций не удалось перечитать.");
    }
    return requireMonthRows(result.data, monthId, "денежных позиций");
  }

  /** Confirmed save → other surfaces go stale; linked-pair facts reread now. */
  async function markDataStale(): Promise<void> {
    await queryClient.invalidateQueries({ refetchType: "none" });
    await queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(monthId) });
  }

  /**
   * Reread the cash aggregate and inspect the outcome (Integrator B1): the
   * total stays unconfirmed — with a visible warning and retry — unless this
   * month's aggregate comes back successfully.
   */
  async function refreshCashTotal(): Promise<void> {
    setTotalUnconfirmed(true);
    const result = await cashTotalQuery.refetch();
    const confirmed = result.isSuccess && result.data?.reporting_month_id === monthId;
    if (confirmed) {
      setTotalUnconfirmed(false);
      setTotalWarning(null);
    } else {
      setTotalWarning(CASH_TOTAL_WARNING);
    }
  }

  function reportFailure(token: number, cause: unknown): void {
    if (operation.current === token) {
      setActionError(formatApiError(cause));
    }
  }

  function finishAction(token: number): void {
    if (operation.current === token) {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function ensureDepositAccount(): Promise<number> {
    const existing = depositAccounts[0];
    if (existing) {
      return existing.id;
    }
    const created = await createAccount({
      name: "Депозиты",
      account_type: "deposit",
      status: "active",
      include_in_capital: true,
      include_in_returns: true,
    });
    await queryClient.invalidateQueries({ queryKey: queryKeys.accounts });
    return created.id;
  }

  async function handleCreateDeposit(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    if (readOnly) {
      setActionError("Месяц закрыт: изменения активов недоступны.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!normalizeMoneyInput(depositDraft.balance)) {
        throw new Error("Укажи баланс вклада");
      }
      if (!depositDraft.name.trim()) {
        throw new Error("Укажи название вклада");
      }
      let accountId = Number(effectiveAccountId);
      if (!Number.isInteger(accountId) || accountId < 1) {
        accountId = await ensureDepositAccount();
      }
      const balance = moneyValue(depositDraft.balance, "RUB");
      const created = await createDeposit({
        reporting_month_id: monthId,
        account_id: accountId,
        name: depositDraft.name.trim(),
        deposit_type: depositDraft.deposit_type,
        balance,
        annual_rate: depositDraft.annual_rate.trim() || "0.00",
        actual_interest_received: moneyValue(
          depositDraft.actual_interest.trim() === "" ? "0" : depositDraft.actual_interest,
          "RUB",
        ),
      });
      if (created.reporting_month_id !== monthId) {
        throw new Error("API сохранил вклад в другом месяце.");
      }
      const fresh = await refetchDepositRows();
      const confirmed = fresh.find((row) => row.id === created.id);
      if (
        !confirmed ||
        confirmed.name !== created.name ||
        !sameMoney(moneyAmount(confirmed.balance), moneyAmount(balance))
      ) {
        throw new Error("Сохранение вклада не подтверждено перечитыванием списка.");
      }
      await markDataStale();
      if (operation.current !== token) return;
      setDepositDraft({ ...emptyDeposit(), account_id: String(accountId) });
      setDepositDraftTouched(false);
      setNotice(`Вклад «${confirmed.name}» сохранён; данные перечитаны.`);
    } catch (cause) {
      reportFailure(token, cause);
      void depositsQuery.refetch();
    } finally {
      finishAction(token);
    }
  }

  async function handleSaveDepositEdit() {
    if (busyRef.current || readOnly) return;
    if (editingDepositId == null || !editDeposit) return;
    if (depositsForeign) {
      setActionError(DEPOSITS_FOREIGN_MESSAGE);
      void depositsQuery.refetch();
      return;
    }
    const current = depositRows.find((row) => row.id === editingDepositId);
    if (!current) {
      setEditingDepositId(null);
      setEditDeposit(null);
      setActionError("Вклад исчез из выбранного месяца. Список обновлён; повтори изменение.");
      void depositsQuery.refetch();
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!editDeposit.name.trim()) {
        throw new Error("Укажи название вклада");
      }
      const balance = moneyValue(editDeposit.balance, current.balance.currency);
      const actualInterest = moneyValue(
        editDeposit.actual_interest.trim() === "" ? "0" : editDeposit.actual_interest,
        current.actual_interest_received.currency,
      );
      const changed = await updateDeposit(
        editingDepositId,
        {
          name: editDeposit.name.trim(),
          deposit_type: editDeposit.deposit_type,
          balance,
          annual_rate: editDeposit.annual_rate.trim() || "0.00",
          actual_interest_received: actualInterest,
        },
        current.updated_at,
      );
      if (changed.id !== current.id || changed.reporting_month_id !== monthId) {
        throw new Error("Ответ сохранения не подтверждает выбранный вклад.");
      }
      const fresh = await refetchDepositRows();
      const confirmed = fresh.find((row) => row.id === current.id);
      if (
        !confirmed ||
        confirmed.name !== editDeposit.name.trim() ||
        !sameMoney(moneyAmount(confirmed.balance), moneyAmount(balance))
      ) {
        throw new Error("Изменение вклада не подтверждено перечитыванием списка.");
      }
      await markDataStale();
      if (operation.current !== token) return;
      setEditingDepositId(null);
      setEditDeposit(null);
      setNotice(`Вклад «${confirmed.name}» сохранён; данные перечитаны.`);
    } catch (cause) {
      reportFailure(token, cause);
      void depositsQuery.refetch();
    } finally {
      finishAction(token);
    }
  }

  async function handleDeleteDeposit() {
    const target = pendingDeleteDeposit;
    if (!target || busyRef.current) return;
    if (readOnly) {
      setPendingDeleteDeposit(null);
      setActionError("Месяц закрыт: удаление активов недоступно.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    setPendingDeleteDeposit(null);
    try {
      await deleteDeposit(target.id);
      const fresh = await refetchDepositRows();
      if (fresh.some((row) => row.id === target.id)) {
        throw new Error("Удаление не подтверждено перечитыванием списка.");
      }
      await markDataStale();
      if (operation.current !== token) return;
      setNotice(`Вклад «${target.name}» удалён; данные перечитаны.`);
    } catch (cause) {
      reportFailure(token, cause);
      void depositsQuery.refetch();
    } finally {
      finishAction(token);
    }
  }

  async function handleCreateCash(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    if (readOnly) {
      setActionError("Месяц закрыт: изменения активов недоступны.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!cashDraft.name.trim()) {
        throw new Error("Укажи название денежной позиции");
      }
      if (!normalizeMoneyInput(cashDraft.amount)) {
        throw new Error("Укажи сумму");
      }
      // From this point the pre-write total must not present as current (B1).
      setTotalUnconfirmed(true);
      const created = await createCashBalance({
        reporting_month_id: monthId,
        name: cashDraft.name.trim(),
        amount: moneyValue(cashDraft.amount, "RUB"),
        include_in_capital: cashDraft.include_in_capital,
      });
      if (created.reporting_month_id !== monthId) {
        throw new Error("API сохранил денежную позицию в другом месяце.");
      }
      const fresh = await refetchCashRows();
      const confirmed = fresh.find((row) => row.id === created.id);
      if (
        !confirmed ||
        confirmed.name !== created.name ||
        !sameMoney(moneyAmount(confirmed.amount), moneyAmount(created.amount)) ||
        confirmed.include_in_capital !== created.include_in_capital
      ) {
        throw new Error("Сохранение денежной позиции не подтверждено перечитыванием списка.");
      }
      await refreshCashTotal();
      await markDataStale();
      if (operation.current !== token) return;
      setCashDraft(emptyCash());
      setCashDraftTouched(false);
      setNotice(`Денежная позиция «${confirmed.name}» сохранена; данные перечитаны.`);
    } catch (cause) {
      reportFailure(token, cause);
      void cashRowsQuery.refetch();
      void refreshCashTotal();
    } finally {
      finishAction(token);
    }
  }

  async function handleDeleteCash() {
    const target = pendingDeleteCash;
    if (!target || busyRef.current) return;
    if (readOnly) {
      setPendingDeleteCash(null);
      setActionError("Месяц закрыт: удаление активов недоступно.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    setPendingDeleteCash(null);
    // From this point the pre-write total must not present as current (B1).
    setTotalUnconfirmed(true);
    try {
      await deleteCashBalance(target.id);
      const fresh = await refetchCashRows();
      if (fresh.some((row) => row.id === target.id)) {
        throw new Error("Удаление не подтверждено перечитыванием списка.");
      }
      await refreshCashTotal();
      await markDataStale();
      if (operation.current !== token) return;
      setNotice(`Денежная позиция «${target.name}» удалена; данные перечитаны.`);
    } catch (cause) {
      reportFailure(token, cause);
      void cashRowsQuery.refetch();
      void refreshCashTotal();
    } finally {
      finishAction(token);
    }
  }

  async function handleToggleCashCapital(row: CashBalance) {
    if (busyRef.current) return;
    if (readOnly) {
      setActionError("Месяц закрыт: изменения активов недоступны.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      // From this point the pre-write total must not present as current (B1).
      setTotalUnconfirmed(true);
      const target = !row.include_in_capital;
      const changed = await updateCashBalance(row.id, { include_in_capital: target });
      if (changed.id !== row.id || changed.reporting_month_id !== monthId) {
        throw new Error("Ответ API не подтверждает денежную позицию.");
      }
      const fresh = await refetchCashRows();
      const confirmed = fresh.find((item) => item.id === row.id);
      if (!confirmed || confirmed.include_in_capital !== target) {
        throw new Error("Изменение не подтверждено перечитыванием списка.");
      }
      await refreshCashTotal();
      await markDataStale();
      if (operation.current !== token) return;
      setNotice(
        `«${confirmed.name}»: ${target ? "включена" : "исключена"} из ликвидного капитала.`,
      );
    } catch (cause) {
      reportFailure(token, cause);
      void cashRowsQuery.refetch();
      void refreshCashTotal();
    } finally {
      finishAction(token);
    }
  }

  return (
    <div className="stack-18">
      <section
        aria-label="Источник и снимок месяца"
        className={styles.meta}
        data-testid="month-assets-meta"
      >
        <p>
          Источник: <strong>{labelOf(SOURCE_LABELS, month.source)}</strong> · Снимок:{" "}
          <strong>{formatDate(month.snapshot_date)}</strong> · Период:{" "}
          <strong>{formatMonth(month.year, month.month)}</strong> ·{" "}
          {month.status === "closed" ? "Закрыт" : "Черновик"}
        </p>
        <p className={styles.hint}>
          Суммы показываются так, как их возвращает API выбранного месяца. Раздел не рассчитывает
          полноту капитала и не подменяет отсутствующий снимок нулём.
        </p>
        {readOnly ? (
          <p className={styles.hint}>
            Месяц закрыт: создание, изменение и удаление активов недоступны до повторного открытия.
          </p>
        ) : null}
      </section>

      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}
      {notice ? (
        <div className="inline-alert inline-alert--ok" role="status">
          {notice}
        </div>
      ) : null}

      {loading ? (
        <LoadingState description="Загружаем депозиты и наличные…" inline />
      ) : loadError ? (
        <ErrorState
          description={formatApiError(loadError.error)}
          inline
          title="Не удалось загрузить активы"
        />
      ) : (
        <>
          <Panel
            action={
              <Badge>
                {depositsForeign ? (
                  <>итог — · снимок не подтверждён</>
                ) : (
                  <>
                    итог {totalText(depositTotals.balance, depositTotals.currency)} ·{" "}
                    {depositRows.length} шт.
                  </>
                )}
              </Badge>
            }
            label="Активы"
            title="Депозиты"
          >
            {depositsForeign ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {DEPOSITS_FOREIGN_MESSAGE}
              </div>
            ) : depositRows.length === 0 ? (
              <EmptyState
                description="Депозитов пока нет — добавь вклад формой ниже."
                inline
                title="Пусто"
              />
            ) : (
              <Table className={`month-deposits-table ${styles.depositsTable}`}>
                <thead>
                  <tr>
                    <Th className="month-deposits-table__name">Название</Th>
                    <Th className="month-deposits-table__type">Тип</Th>
                    <Th numeric>Баланс</Th>
                    <Th numeric>Ставка %</Th>
                    <Th numeric>Прогноз / мес</Th>
                    <Th numeric>Получено</Th>
                    <Th className="month-deposits-table__actions">Действия</Th>
                  </tr>
                </thead>
                <tbody>
                  {depositRows.map((row) => {
                    const editing = editingDepositId === row.id && editDeposit;
                    return (
                      <tr key={row.id}>
                        <Td>
                          {editing ? (
                            <Input
                              value={editDeposit.name}
                              onChange={(event) =>
                                setEditDeposit({ ...editDeposit, name: event.target.value })
                              }
                            />
                          ) : (
                            row.name
                          )}
                        </Td>
                        <Td>
                          {editing ? (
                            <Select
                              value={editDeposit.deposit_type}
                              onChange={(event) =>
                                setEditDeposit({ ...editDeposit, deposit_type: event.target.value })
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
                              onChange={(event) =>
                                setEditDeposit({ ...editDeposit, balance: event.target.value })
                              }
                            />
                          ) : (
                            formatMoney(moneyAmount(row.balance), {
                              currency: currencySuffix(row.balance.currency),
                            })
                          )}
                        </Td>
                        <Td numeric>
                          {editing ? (
                            <Input
                              className="input--money"
                              value={editDeposit.annual_rate}
                              onChange={(event) =>
                                setEditDeposit({ ...editDeposit, annual_rate: event.target.value })
                              }
                            />
                          ) : (
                            row.annual_rate
                          )}
                        </Td>
                        <Td numeric>
                          <span className="muted">
                            {formatMoney(moneyAmount(row.expected_monthly_interest), {
                              currency: currencySuffix(row.expected_monthly_interest.currency),
                            })}
                          </span>
                        </Td>
                        <Td numeric>
                          {editing ? (
                            <Input
                              className="input--money"
                              value={editDeposit.actual_interest}
                              onChange={(event) =>
                                setEditDeposit({
                                  ...editDeposit,
                                  actual_interest: event.target.value,
                                })
                              }
                            />
                          ) : (
                            formatMoney(moneyAmount(row.actual_interest_received), {
                              currency: currencySuffix(row.actual_interest_received.currency),
                            })
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
                Баланс: <strong>{totalText(depositTotals.balance, depositTotals.currency)}</strong>
              </span>
              <span>
                Прогноз / мес:{" "}
                <strong>{totalText(depositTotals.expected, depositTotals.currency)}</strong>
              </span>
              <span>
                Получено: <strong>{totalText(depositTotals.actual, depositTotals.currency)}</strong>
              </span>
            </div>
            {depositTotals.mixed ? (
              <p className={styles.hint} role="status">
                Строки в разных валютах: итог показан без конвертации.
              </p>
            ) : null}

            {!readOnly ? (
              <form className="form-stack asset-form" onSubmit={handleCreateDeposit}>
                <p className="panel__label" style={{ marginBottom: 0 }}>
                  Новый вклад
                </p>
                <div className="editor-grid">
                  <Field htmlFor="dep-name" label="Название вклада">
                    <Input
                      id="dep-name"
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, name: event.target.value });
                        setDepositDraftTouched(true);
                      }}
                      required
                      value={depositDraft.name}
                    />
                  </Field>
                  <Field htmlFor="dep-type" label="Тип">
                    <Select
                      id="dep-type"
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, deposit_type: event.target.value });
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
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, account_id: event.target.value });
                        setDepositDraftTouched(true);
                      }}
                      value={effectiveAccountId}
                    >
                      <option value="">авто (создать «Депозиты»)</option>
                      {depositAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.name} ({labelOf(ACCOUNT_TYPE_LABELS, account.account_type)})
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field htmlFor="dep-balance" label="Баланс вклада">
                    <Input
                      className="input--money"
                      id="dep-balance"
                      inputMode="decimal"
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, balance: event.target.value });
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
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, annual_rate: event.target.value });
                        setDepositDraftTouched(true);
                      }}
                      value={depositDraft.annual_rate}
                    />
                  </Field>
                  <Field htmlFor="dep-actual" label="Факт. процент">
                    <Input
                      className="input--money"
                      id="dep-actual"
                      onChange={(event) => {
                        setDepositDraft({ ...depositDraft, actual_interest: event.target.value });
                        setDepositDraftTouched(true);
                      }}
                      value={depositDraft.actual_interest}
                    />
                  </Field>
                </div>
                <Button disabled={busy || readOnly} type="submit" variant="primary">
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
                наличные {cashTotalText} · в капитале {cashInCapitalText}
              </Badge>
            }
            label="Активы"
            title="Денежные средства"
          >
            {cashForeign ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {CASH_FOREIGN_MESSAGE}
              </div>
            ) : cashRows.length === 0 ? (
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
                      <Td numeric>
                        {formatMoney(moneyAmount(row.amount), {
                          currency: currencySuffix(row.currency),
                        })}
                      </Td>
                      <Td>
                        <Button
                          disabled={busy || readOnly}
                          onClick={() => void handleToggleCashCapital(row)}
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
                Всего наличных: <strong>{cashTotalText}</strong>
              </span>
              <span>
                В ликвидном капитале: <strong>{cashInCapitalText}</strong>
              </span>
            </div>
            {!cashTotalQuery.isPending &&
            !totalUnconfirmed &&
            !(cashTotal && cashTotalQuery.isSuccess) ? (
              <div className="inline-alert inline-alert--warn" role="status">
                Итоги наличных за выбранный месяц недоступны: сумма не подменяется нулём, полнота
                капитала не утверждается.{" "}
                <Button
                  disabled={cashTotalQuery.isFetching}
                  onClick={() => void refreshCashTotal()}
                  size="sm"
                  type="button"
                >
                  Повторить чтение итога
                </Button>
              </div>
            ) : null}
            {totalWarning && !cashTotalQuery.isPending ? (
              <div className="inline-alert inline-alert--warn" role="alert">
                {totalWarning}{" "}
                <Button
                  disabled={cashTotalQuery.isFetching}
                  onClick={() => void refreshCashTotal()}
                  size="sm"
                  type="button"
                >
                  Повторить чтение итога
                </Button>
              </div>
            ) : null}

            {!readOnly ? (
              <form className="form-stack asset-form" onSubmit={handleCreateCash}>
                <p className="panel__label section-form-label">Новая денежная позиция</p>
                <div className="editor-grid">
                  <Field htmlFor="cash-name" label="Название денежной позиции">
                    <Input
                      id="cash-name"
                      onChange={(event) => {
                        setCashDraft({ ...cashDraft, name: event.target.value });
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
                      onChange={(event) => {
                        setCashDraft({ ...cashDraft, amount: event.target.value });
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
                    onChange={(event) => {
                      setCashDraft({ ...cashDraft, include_in_capital: event.target.checked });
                      setCashDraftTouched(true);
                    }}
                    type="checkbox"
                  />
                  Включать в ликвидный капитал
                </label>
                <Button disabled={busy || readOnly} type="submit" variant="primary">
                  Добавить денежную позицию
                </Button>
              </form>
            ) : null}
          </Panel>

          <LinkedPairContext
            accounts={accounts}
            debts={debts}
            error={linkedPairError}
            label="Актив"
            pairs={linkedPairs}
            title="Связанные долги"
          />

          <ConfirmDialog
            busy={busy}
            cancelLabel="Отмена"
            confirmLabel="Удалить"
            danger
            description={
              pendingDeleteDeposit ? `Удалить вклад «${pendingDeleteDeposit.name}»?` : ""
            }
            onCancel={() => {
              if (!busyRef.current) setPendingDeleteDeposit(null);
            }}
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
            onCancel={() => {
              if (!busyRef.current) setPendingDeleteCash(null);
            }}
            onConfirm={() => void handleDeleteCash()}
            open={pendingDeleteCash !== null}
            title="Удалить денежную позицию?"
          />
        </>
      )}
    </div>
  );
}
