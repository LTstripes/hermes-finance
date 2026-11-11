import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { createAccount, listAccounts } from "../api/accounts";
import { ApiClientError, formatApiError } from "../api/client";
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
import { formatDate, formatMonth, formatMoney, formatPercent } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, DEPOSIT_TYPE_LABELS, SOURCE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, sumMoneyAmounts, toKopecks } from "../lib/money";
import { queryKeys } from "../queryClient";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { MonthMoneyInput } from "./MonthMoneyInput";
import { MonthSaveBar } from "./MonthSaveBar";
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
  "Итог денег не перечитан: прежнее значение не показывается как текущее. Строки подтверждаются отдельным перечитыванием списка.";

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

/** A typed client rejection confirms the server did not accept this write. */
function isDefiniteWriteRejection(cause: unknown): boolean {
  return (
    cause instanceof ApiClientError &&
    cause.status >= 400 &&
    cause.status < 500 &&
    cause.status !== 408 &&
    cause.status !== 429 &&
    cause.code !== "http_error"
  );
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

/** Exactly the values submitted for a deposit write, normalized as sent. */
type DepositIntent = {
  name: string;
  deposit_type: string;
  balance: MoneyValue;
  annual_rate: string;
  actual_interest_received: MoneyValue;
};

type DepositRecovery = {
  unconfirmed: boolean;
  version: number;
  pendingCreate: PendingCreate | null;
  createDraft: DepositDraft | null;
  edits: Map<number, DepositIntent>;
  otherWrites: Map<
    number,
    | { kind: "create"; id: number | null; intent: DepositIntent; draft: DepositDraft }
    | { kind: "delete"; id: number }
  >;
};

/**
 * Retained identity of an already-POSTED deposit: confirmation retries re-check
 * by id and can never issue a second POST (Integrator duplicate guard).
 */
type PendingCreate = {
  id: number;
  accountId: number;
  intent: DepositIntent;
  draft: DepositDraft;
};

/**
 * Exact rate canonicalization mirroring the backend contract
 * (`PercentageRate.from_api` → integer basis points with ROUND_HALF_UP away
 * from zero → `to_api()` with two decimals; see `domain/values.py` and the
 * evidence tables in `tests/domain/test_values.py` /
 * `tests/test_scenario_lab_deposit_rate.py`: `12`→`12.00`, `12.3`→`12.30`,
 * `12.345`→`12.35`, `13.505`→`13.51`, `-0.005`→`-0.01`).
 *
 * Pure digit-string arithmetic with BigInt rounding — no binary-float
 * conversion and no numeric-prefix acceptance: `12garbage`, `NaN`, `Infinity`
 * and other non-decimal strings canonicalize to null and can never confirm.
 */
function canonicalRate(rate: string): string | null {
  const match = /^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(rate.trim());
  if (!match) return null;
  const negative = match[1] === "-";
  const mantissa = match[2];
  const exponent = match[3] === undefined ? 0 : Number.parseInt(match[3], 10);
  const dot = mantissa.indexOf(".");
  const intPart = dot === -1 ? mantissa : mantissa.slice(0, dot);
  const fracPart = dot === -1 ? "" : mantissa.slice(dot + 1);
  // Value = digits × 10^-scale, exact; the exponent only moves the point.
  let digits = `${intPart}${fracPart}`;
  let scale = fracPart.length - exponent;
  if (scale < 0) {
    digits += "0".repeat(-scale);
    scale = 0;
  }
  if (digits.length > 40 || scale > 40) return null;
  digits = digits.replace(/^0+/, "") || "0";
  digits = digits.padStart(scale, "0");
  if (scale > 2) {
    // Round to basis points (2 decimals): half-up on the magnitude, which for
    // negatives rounds ties away from zero — exactly like _scaled_half_up.
    const drop = scale - 2;
    const keep = digits.slice(0, digits.length - drop);
    const firstDropped = digits.charCodeAt(digits.length - drop) - 48;
    digits = (BigInt(keep) + (firstDropped >= 5 ? 1n : 0n)).toString();
    scale = 2;
  } else if (scale < 2) {
    digits += "0".repeat(2 - scale);
    scale = 2;
  }
  const padded = digits.padStart(3, "0");
  const magnitude = `${padded.slice(0, padded.length - 2)}.${padded.slice(-2)}`;
  if (magnitude === "0.00") return "0.00";
  return negative ? `-${magnitude}` : magnitude;
}

/** Exact rate equality on the canonical basis-points contract. */
function sameRate(left: string, right: string): boolean {
  const a = canonicalRate(left);
  return a !== null && a === canonicalRate(right);
}

/**
 * Complete write confirmation (Integrator B1): every submitted field — name,
 * type, balance amount+currency, rate and actual interest amount+currency —
 * must come back from the reread list; a stale row confirms nothing.
 */
function matchesDepositIntent(
  row: DepositSnapshot | undefined,
  intent: DepositIntent,
): row is DepositSnapshot {
  return (
    row !== undefined &&
    row.name === intent.name &&
    row.deposit_type === intent.deposit_type &&
    row.balance.currency === intent.balance.currency &&
    sameMoney(row.balance.amount, intent.balance.amount) &&
    sameRate(row.annual_rate, intent.annual_rate) &&
    row.actual_interest_received.currency === intent.actual_interest_received.currency &&
    sameMoney(row.actual_interest_received.amount, intent.actual_interest_received.amount)
  );
}

const DEPOSIT_CREATE_UNCONFIRMED =
  "Создание вклада не подтверждено: перечитанные данные не совпадают с отправленными. Вклад уже создан — повторное нажатие проверит его без нового создания.";
const DEPOSIT_EDIT_UNCONFIRMED =
  "Изменение вклада не подтверждено: перечитанные данные не совпадают с отправленными. Изменение оставлено в форме; повтори сохранение.";

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
  const closed = month.status === "closed";
  const [showEmptyDeposits, setShowEmptyDeposits] = useState(false);
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
  useQuery({
    queryKey: queryKeys.debts(monthId),
    queryFn: ({ signal }) => listDebts(monthId, signal),
  });
  useQuery({
    queryKey: queryKeys.dashboardBasic(monthId),
    queryFn: ({ signal }) => getDashboard(monthId, signal, false),
  });

  // Query-scoped recovery survives leaving and returning to this month within
  // the same client, without retaining data outside the local session.
  const depositRecovery = useQuery({
    queryKey: ["deposit-readback-recovery", monthId],
    queryFn: (): DepositRecovery => ({
      unconfirmed: false,
      version: 0,
      pendingCreate: null,
      createDraft: null,
      edits: new Map(),
      otherWrites: new Map(),
    }),
    enabled: false,
    gcTime: Infinity,
    initialData: (): DepositRecovery => ({
      unconfirmed: false,
      version: 0,
      pendingCreate: null,
      createDraft: null,
      edits: new Map(),
      otherWrites: new Map(),
    }),
  }).data;

  const unresolvedCreate = [...depositRecovery.otherWrites.values()].find(
    (item) => item.kind === "create" && item.id === null,
  );
  const [depositDraft, setDepositDraft] = useState<DepositDraft>(
    () =>
      ((depositRecovery.pendingCreate || unresolvedCreate) && depositRecovery.createDraft) ||
      depositRecovery.pendingCreate?.draft ||
      (unresolvedCreate?.kind === "create" ? unresolvedCreate.draft : emptyDeposit()),
  );
  const [cashDraft, setCashDraft] = useState<CashDraft>(emptyCash);
  const [depositDraftTouched, setDepositDraftTouched] = useState(
    Boolean(depositRecovery.pendingCreate || unresolvedCreate),
  );
  const [depositTotalsUnconfirmed, setDepositTotalsUnconfirmedState] = useState(
    depositRecovery.unconfirmed,
  );
  function setDepositTotalsUnconfirmed(value: boolean) {
    depositRecovery.unconfirmed = value;
    setDepositTotalsUnconfirmedState(value);
  }
  const [cashDraftTouched, setCashDraftTouched] = useState(false);
  const [editDeposits, setEditDeposits] = useState<Record<number, DepositDraft> | null>(null);
  const [editingDepositId, setEditingDepositId] = useState<number | null>(null);
  const [showNewDeposit, setShowNewDeposit] = useState(false);
  const [showNewCash, setShowNewCash] = useState(false);
  const [cashEdits, setCashEdits] = useState<Record<number, string>>({});
  const editBefore = useRef<DepositDraft | null>(null);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());
  function focusDepositMenu(id: number) {
    rowRefs.current.get(id)?.querySelector<HTMLButtonElement>("[aria-haspopup=menu]")?.focus();
  }
  useEffect(() => {
    if (editingDepositId !== null)
      rowRefs.current
        .get(editingDepositId)
        ?.nextElementSibling?.querySelector<HTMLInputElement>("input")
        ?.focus();
  }, [editingDepositId]);
  const [editOriginals, setEditOriginals] = useState<Record<number, DepositSnapshot>>({});
  const [pendingDeleteDeposit, setPendingDeleteDeposit] = useState<DepositSnapshot | null>(null);
  const [pendingDeleteCash, setPendingDeleteCash] = useState<CashBalance | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Cash aggregate authority: unconfirmed while a write is in flight or its
  // total readback failed — the pre-write value is never shown as current (B1).
  const [totalUnconfirmed, setTotalUnconfirmed] = useState(false);
  const [totalWarning, setTotalWarning] = useState<string | null>(null);
  // A successful POST is retained here until confirmed: retries re-check by id
  // without ever repeating the create (duplicate-POST guard).
  const [pendingCreated, setPendingCreatedState] = useState<PendingCreate | null>(
    depositRecovery.pendingCreate,
  );
  function setPendingCreated(value: PendingCreate | null) {
    depositRecovery.pendingCreate = value;
    setPendingCreatedState(value);
  }
  useEffect(() => {
    depositRecovery.createDraft = pendingCreated || unresolvedCreate ? depositDraft : null;
  }, [depositDraft, depositRecovery, pendingCreated, unresolvedCreate]);
  // Retain attempted writes until a fresh list establishes their outcome.
  const pendingDepositEdits = useRef(depositRecovery.edits);
  const pendingOtherDepositWrites = useRef(depositRecovery.otherWrites);
  const busyRef = useRef(false);
  const operation = useRef(0);

  const localDirty =
    depositDraftTouched ||
    cashDraftTouched ||
    editDeposits !== null ||
    Object.keys(cashEdits).length > 0;

  useEffect(() => {
    context.setPending?.(DIRTY_SECTION, busy || pendingCreated !== null);
    return () => context.setPending?.(DIRTY_SECTION, false);
  }, [context.setPending, busy, pendingCreated]);
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
  const depositRows = useMemo(
    () =>
      [...(depositsQuery.data ?? [])].sort((a, b) => {
        const left = toKopecks(moneyAmount(a.balance));
        const right = toKopecks(moneyAmount(b.balance));
        return left === right ? 0 : left > right ? -1 : 1;
      }),
    [depositsQuery.data],
  );
  const showDepositType = closed && new Set(depositRows.map((row) => row.deposit_type)).size > 1;
  const changedDepositFields = Object.entries(editDeposits ?? {}).reduce((count, [id, draft]) => {
    const original = editOriginals[Number(id)];
    if (!original) return count;
    const before = depositDraftFor(original);
    return (
      count +
      (Object.keys(draft) as Array<keyof DepositDraft>).filter((key) => draft[key] !== before[key])
        .length
    );
  }, 0);
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
          (account.account_type === "deposit" || account.account_type === "savings"),
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

  const emptyDeposits = depositRows.filter(
    (row) =>
      normalizeMoneyInput(row.balance.amount) !== null && toKopecks(row.balance.amount) === 0n,
  );
  const visibleDeposits = !showEmptyDeposits
    ? depositRows.filter((row) => !emptyDeposits.includes(row))
    : depositRows;
  const showCashCapital = !closed || cashRows.some((row) => !row.include_in_capital);

  const defaultAccountId = depositAccounts[0]?.id ?? null;
  const effectiveAccountId =
    depositDraft.account_id || (defaultAccountId === null ? "" : String(defaultAccountId));

  const loading = accountsQuery.isPending || depositsQuery.isPending || cashRowsQuery.isPending;
  const loadError = [accountsQuery, depositsQuery, cashRowsQuery].find(
    (query) => query.isError && (query !== depositsQuery || query.data === undefined),
  );

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

  async function refetchDepositRows(): Promise<DepositSnapshot[]> {
    const version = depositRecovery.version;
    const result = await depositsQuery.refetch();
    if (!result.isSuccess || !result.data) {
      throw new Error("Список вкладов не удалось перечитать.");
    }
    if (version !== depositRecovery.version) {
      throw new Error("Список вкладов изменился во время чтения. Обнови данные ещё раз.");
    }
    const rows = requireMonthRows(result.data, monthId, "вкладов");
    const editsConfirmed = [...pendingDepositEdits.current].every(([id, intent]) =>
      matchesDepositIntent(
        rows.find((row) => row.id === id),
        intent,
      ),
    );
    for (const [token, other] of pendingOtherDepositWrites.current) {
      const confirmed =
        other.kind === "delete"
          ? !rows.some((row) => row.id === other.id)
          : other.id !== null &&
            matchesDepositIntent(
              rows.find((row) => row.id === other.id),
              other.intent,
            );
      if (confirmed) pendingOtherDepositWrites.current.delete(token);
    }
    setDepositTotalsUnconfirmed(!editsConfirmed || pendingOtherDepositWrites.current.size > 0);
    return rows;
  }

  async function refreshDepositDisplay() {
    if (busyRef.current) return;
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await refetchDepositRows();
    } catch (cause) {
      reportFailure(token, cause);
    } finally {
      finishAction(token);
    }
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
    await queryClient.invalidateQueries({ queryKey: queryKeys.dashboardBasic(monthId) });
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
    if (busyRef.current || unresolvedCreate) return;
    if (readOnly) {
      setActionError("Месяц закрыт: изменения активов недоступны.");
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    let writeId: number | null = null;
    let writeAcknowledged = false;
    try {
      if (pendingCreated) {
        // Identity retained from a successful POST: confirm by id only — a
        // retry can never repeat the create (duplicate-POST guard).
        await confirmCreatedDeposit(pendingCreated, token);
        return;
      }
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
      const intent: DepositIntent = {
        name: depositDraft.name.trim(),
        deposit_type: depositDraft.deposit_type,
        balance: moneyValue(depositDraft.balance, "RUB"),
        annual_rate: depositDraft.annual_rate.trim() || "0.00",
        actual_interest_received: moneyValue(
          depositDraft.actual_interest.trim() === "" ? "0" : depositDraft.actual_interest,
          "RUB",
        ),
      };
      writeId = ++depositRecovery.version;
      pendingOtherDepositWrites.current.set(writeId, {
        kind: "create",
        id: null,
        intent,
        draft: { ...depositDraft },
      });
      setDepositTotalsUnconfirmed(true);
      const created = await createDeposit({
        reporting_month_id: monthId,
        account_id: accountId,
        name: intent.name,
        deposit_type: intent.deposit_type,
        balance: intent.balance,
        annual_rate: intent.annual_rate,
        actual_interest_received: intent.actual_interest_received,
      });
      writeAcknowledged = true;
      if (created.reporting_month_id !== monthId) {
        throw new Error("API сохранил вклад в другом месяце.");
      }
      pendingOtherDepositWrites.current.set(writeId, {
        kind: "create",
        id: created.id,
        intent,
        draft: { ...depositDraft },
      });
      const pending: PendingCreate = {
        id: created.id,
        accountId,
        intent,
        draft: { ...depositDraft },
      };
      setPendingCreated(pending);
      await confirmCreatedDeposit(pending, token);
    } catch (cause) {
      if (writeId !== null && !writeAcknowledged && isDefiniteWriteRejection(cause)) {
        pendingOtherDepositWrites.current.delete(writeId);
      }
      reportFailure(token, cause);
      void refetchDepositRows().catch(() => {});
    } finally {
      finishAction(token);
    }
  }

  /**
   * Readback-only confirmation of a retained create: re-checks the row by its
   * stored id and intent without ever issuing another POST. The draft is
   * cleared only when it still equals what was submitted — newer input stays.
   */
  async function confirmCreatedDeposit(pending: PendingCreate, token: number): Promise<void> {
    const fresh = await refetchDepositRows();
    const confirmed = fresh.find((row) => row.id === pending.id);
    if (!matchesDepositIntent(confirmed, pending.intent)) {
      throw new Error(DEPOSIT_CREATE_UNCONFIRMED);
    }
    await markDataStale();
    if (operation.current !== token) return;
    setPendingCreated(null);
    const draft = depositDraft;
    const unchanged =
      draft.name === pending.draft.name &&
      draft.account_id === pending.draft.account_id &&
      draft.deposit_type === pending.draft.deposit_type &&
      draft.balance === pending.draft.balance &&
      draft.annual_rate === pending.draft.annual_rate &&
      draft.actual_interest === pending.draft.actual_interest;
    if (unchanged) {
      setDepositDraft({ ...emptyDeposit(), account_id: String(pending.accountId) });
      setDepositDraftTouched(false);
    }
    setNotice(
      `Вклад «${confirmed.name}» сохранён; данные перечитаны.${unchanged ? "" : " Введённые данные оставлены в форме."}`,
    );
  }

  function depositDraftFor(row: DepositSnapshot): DepositDraft {
    return {
      name: row.name,
      account_id: String(row.account_id),
      deposit_type: row.deposit_type,
      balance: moneyAmount(row.balance),
      annual_rate: row.annual_rate,
      actual_interest: moneyAmount(row.actual_interest_received),
    };
  }
  function patchDeposit(row: DepositSnapshot, patch: Partial<DepositDraft>) {
    setNotice(null);
    if (!editDeposits?.[row.id]) setEditOriginals((previous) => ({ ...previous, [row.id]: row }));
    setEditDeposits((previous) => ({
      ...previous,
      [row.id]: { ...(previous?.[row.id] ?? depositDraftFor(row)), ...patch },
    }));
  }
  function cancelDeposit(row: DepositSnapshot) {
    if (busyRef.current) return;
    setEditDeposits((previous) => {
      const next = { ...previous };
      if (editBefore.current) next[row.id] = editBefore.current;
      else delete next[row.id];
      return Object.keys(next).length ? next : null;
    });
    setEditingDepositId(null);
    focusDepositMenu(row.id);
  }

  async function handleSaveDepositEdit(onlyId?: number) {
    if (busyRef.current || readOnly) return;
    if (!editDeposits) {
      if (onlyId !== undefined) {
        setEditingDepositId(null);
        focusDepositMenu(onlyId);
      }
      return;
    }
    if (depositsForeign) {
      setActionError(DEPOSITS_FOREIGN_MESSAGE);
      return;
    }
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    const failed: Record<number, DepositDraft> = {};
    const saved: string[] = [];
    const errors: string[] = [];
    for (const [idText, draft] of Object.entries(editDeposits)) {
      if (operation.current !== token) return;
      const id = Number(idText);
      if (onlyId !== undefined && id !== onlyId) {
        failed[id] = draft;
        continue;
      }
      const current = editOriginals[id];
      let writeAcknowledged = false;
      try {
        if (!current || !draft.name.trim()) throw new Error("Укажи название вклада");
        const intent: DepositIntent = {
          name: draft.name.trim(),
          deposit_type: draft.deposit_type,
          balance: moneyValue(draft.balance, current.balance.currency),
          annual_rate: draft.annual_rate.trim() || "0.00",
          actual_interest_received: moneyValue(
            draft.actual_interest.trim() === "" ? "0" : draft.actual_interest,
            current.actual_interest_received.currency,
          ),
        };
        const pending = pendingDepositEdits.current.get(id);
        if (pending) {
          const fresh = (await refetchDepositRows()).find((row) => row.id === id);
          if (operation.current !== token) return;
          const matchesCurrent: boolean = matchesDepositIntent(fresh, intent);
          const matchesPending: boolean = matchesDepositIntent(fresh, pending);
          if (matchesCurrent) {
            pendingDepositEdits.current.delete(id);
            saved.push(intent.name);
            continue;
          }
          if (fresh && matchesPending) {
            // The previous write landed, but the user has since changed the
            // draft. Keep the new draft and use the confirmed version next time.
            pendingDepositEdits.current.delete(id);
            setEditOriginals((originals) => ({ ...originals, [id]: fresh }));
            throw new Error(
              "Предыдущее изменение сохранено. Новые данные оставлены в форме; сохрани их ещё раз.",
            );
          }
          if (!fresh || fresh.updated_at !== current.updated_at) {
            throw new Error(
              "Данные вклада изменились. Проверь их перед повторным сохранением; введённые значения оставлены в форме.",
            );
          }
          // The original version is still current, so the prior attempt did
          // not change this row and a new write can use the same precondition.
          pendingDepositEdits.current.delete(id);
        }
        const unchanged =
          draft.name === current.name &&
          draft.deposit_type === current.deposit_type &&
          draft.balance === moneyAmount(current.balance) &&
          draft.annual_rate === current.annual_rate &&
          draft.actual_interest === moneyAmount(current.actual_interest_received);
        if (unchanged) continue;
        depositRecovery.version += 1;
        pendingDepositEdits.current.set(id, intent);
        setDepositTotalsUnconfirmed(true);
        const changed = await updateDeposit(id, intent, current.updated_at);
        writeAcknowledged = true;
        if (operation.current !== token) return;
        if (changed.id !== id || changed.reporting_month_id !== monthId) {
          throw new Error("Ответ сохранения не подтверждает выбранный вклад.");
        }
        const fresh = await refetchDepositRows();
        if (
          !matchesDepositIntent(
            fresh.find((row) => row.id === id),
            intent,
          )
        ) {
          throw new Error(DEPOSIT_EDIT_UNCONFIRMED);
        }
        pendingDepositEdits.current.delete(id);
        saved.push(intent.name);
      } catch (cause) {
        if (!writeAcknowledged && isDefiniteWriteRejection(cause))
          pendingDepositEdits.current.delete(id);
        failed[id] = draft;
        errors.push(`«${draft.name || id}»: ${formatApiError(cause)}`);
      }
    }
    if (saved.length) await markDataStale();
    if (operation.current !== token) return;
    setEditDeposits(Object.keys(failed).length ? failed : null);
    if (saved.length) setNotice(`Сохранено: ${saved.join(", ")}.`);
    else if (!errors.length) setNotice("Изменений нет.");
    if (errors.length)
      setActionError(
        `Не удалось подтвердить: ${errors.join("; ")}. Проверь данные и повтори сохранение.`,
      );
    finishAction(token);
    if (editingDepositId !== null && !failed[editingDepositId]) {
      setEditingDepositId(null);
      focusDepositMenu(editingDepositId);
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
    let writeId: number | null = null;
    let writeAcknowledged = false;
    try {
      writeId = ++depositRecovery.version;
      pendingOtherDepositWrites.current.set(writeId, { kind: "delete", id: target.id });
      setDepositTotalsUnconfirmed(true);
      await deleteDeposit(target.id);
      writeAcknowledged = true;
      const fresh = await refetchDepositRows();
      if (fresh.some((row) => row.id === target.id)) {
        throw new Error("Удаление не подтверждено перечитыванием списка.");
      }
      await markDataStale();
      if (operation.current !== token) return;
      setNotice(`Вклад «${target.name}» удалён; данные перечитаны.`);
    } catch (cause) {
      if (writeId !== null && !writeAcknowledged && isDefiniteWriteRejection(cause)) {
        pendingOtherDepositWrites.current.delete(writeId);
      }
      reportFailure(token, cause);
      void refetchDepositRows().catch(() => {});
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

  async function handleToggleCashCapital(row: CashBalance, amount?: string) {
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
      const target = amount === undefined ? !row.include_in_capital : row.include_in_capital;
      const amountValue = amount === undefined ? undefined : moneyValue(amount, row.currency);
      const changed = await updateCashBalance(
        row.id,
        amountValue ? { amount: amountValue } : { include_in_capital: target },
      );
      if (changed.id !== row.id || changed.reporting_month_id !== monthId) {
        throw new Error("Ответ API не подтверждает денежную позицию.");
      }
      const fresh = await refetchCashRows();
      const confirmed = fresh.find((item) => item.id === row.id);
      if (
        !confirmed ||
        confirmed.include_in_capital !== target ||
        (amountValue && !sameMoney(moneyAmount(confirmed.amount), amountValue.amount))
      ) {
        throw new Error("Изменение не подтверждено перечитыванием списка.");
      }
      await refreshCashTotal();
      await markDataStale();
      if (operation.current !== token) return;
      if (amountValue)
        setCashEdits((previous) => {
          const next = { ...previous };
          delete next[row.id];
          return next;
        });
      setNotice(
        amountValue
          ? "Сохранено"
          : `«${confirmed.name}»: ${target ? "включена" : "исключена"} из ликвидного капитала.`,
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
      <details open={!context.workspace}>
        <summary>Подробнее об источнике и снимке</summary>
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
        </section>
      </details>

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
        <LoadingState description="Загружаем депозиты и деньги…" inline />
      ) : loadError ? (
        <ErrorState
          description={formatApiError(loadError.error)}
          inline
          title="Не удалось загрузить активы"
        />
      ) : (
        <>
          {!readOnly || depositRows.length > 0 || depositsForeign ? (
            <Panel
              action={
                <Badge>
                  {depositsForeign || depositTotalsUnconfirmed ? (
                    <>итог — · данные уточняются</>
                  ) : (
                    <>
                      итог {totalText(depositTotals.balance, depositTotals.currency)} ·{" "}
                      {depositRows.length} шт.
                    </>
                  )}
                </Badge>
              }
              label=""
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
                <Table
                  aria-label="Вклады месяца"
                  className={`month-deposits-table ${styles.depositsTable} ${!readOnly ? styles.editable : ""}`}
                >
                  <thead>
                    <tr>
                      <Th scope="col" className="month-deposits-table__name">
                        Название
                      </Th>
                      {showDepositType ? (
                        <Th scope="col" className="month-deposits-table__type">
                          Тип
                        </Th>
                      ) : null}
                      <Th scope="col" numeric>
                        Баланс
                      </Th>
                      <Th scope="col" numeric>
                        Ставка
                      </Th>
                      <Th scope="col" numeric>
                        Прогноз в месяц
                      </Th>
                      <Th scope="col" numeric>
                        Получено
                      </Th>
                      {!readOnly ? (
                        <Th
                          scope="col"
                          className="month-deposits-table__actions"
                          aria-label="Действия"
                        />
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleDeposits.map((row) => {
                      const draft = editDeposits?.[row.id] ?? depositDraftFor(row);
                      const editing = editingDepositId === row.id;
                      return (
                        <Fragment key={row.id}>
                          <tr
                            key={row.id}
                            ref={(element) => {
                              if (element) rowRefs.current.set(row.id, element);
                              else rowRefs.current.delete(row.id);
                            }}
                            onKeyDown={(event) => {
                              if (busy) return;
                              if (event.key === "Escape" && editing) {
                                event.preventDefault();
                                cancelDeposit(row);
                              }
                              if (
                                event.key === "Enter" &&
                                (event.target as HTMLElement).tagName === "INPUT"
                              ) {
                                event.preventDefault();
                                void handleSaveDepositEdit(row.id);
                              }
                            }}
                          >
                            <Td data-label="Название">
                              {row.name}
                              {!readOnly ? (
                                <small className={styles.cashAccount}>
                                  {labelOf(DEPOSIT_TYPE_LABELS, row.deposit_type)}
                                </small>
                              ) : null}
                              {!readOnly ? (
                                <small className={styles.compactForecast}>
                                  {formatPercent(row.annual_rate, { digits: 2 })} · прогноз{" "}
                                  {formatMoney(moneyAmount(row.expected_monthly_interest), {
                                    currency: currencySuffix(
                                      row.expected_monthly_interest.currency,
                                    ),
                                  })}
                                </small>
                              ) : null}
                            </Td>
                            {showDepositType ? (
                              <Td data-label="Тип">
                                {labelOf(DEPOSIT_TYPE_LABELS, row.deposit_type)}
                              </Td>
                            ) : null}
                            <Td numeric data-label="Баланс">
                              {!readOnly ? (
                                <MonthMoneyInput
                                  aria-label={`Баланс — ${row.name}`}
                                  disabled={busy}
                                  suffix={currencySuffix(row.balance.currency)}
                                  value={draft.balance}
                                  onChange={(value) => patchDeposit(row, { balance: value })}
                                />
                              ) : (
                                formatMoney(moneyAmount(row.balance), {
                                  currency: currencySuffix(row.balance.currency),
                                })
                              )}
                            </Td>
                            <Td numeric data-label="Ставка">
                              {formatPercent(row.annual_rate, { digits: 2 })}
                            </Td>
                            <Td numeric data-label="Прогноз в месяц">
                              <span className="muted">
                                {formatMoney(moneyAmount(row.expected_monthly_interest), {
                                  currency: currencySuffix(row.expected_monthly_interest.currency),
                                })}
                              </span>
                            </Td>
                            <Td numeric data-label="Получено">
                              {!readOnly ? (
                                <MonthMoneyInput
                                  aria-label={`Получено — ${row.name}`}
                                  disabled={busy}
                                  suffix={currencySuffix(row.actual_interest_received.currency)}
                                  value={draft.actual_interest}
                                  onChange={(value) =>
                                    patchDeposit(row, { actual_interest: value })
                                  }
                                />
                              ) : (
                                formatMoney(moneyAmount(row.actual_interest_received), {
                                  currency: currencySuffix(row.actual_interest_received.currency),
                                })
                              )}
                            </Td>
                            {!readOnly ? (
                              <Td className="month-deposits-table__actions" data-label="Действия">
                                <OverflowMenu label={`Действия для вклада «${row.name}»`}>
                                  <OverflowMenuItem
                                    disabled={busy}
                                    onClick={() => {
                                      editBefore.current = editDeposits?.[row.id] ?? null;
                                      setEditingDepositId(row.id);
                                    }}
                                  >
                                    Изменить
                                  </OverflowMenuItem>
                                  <OverflowMenuItem
                                    danger
                                    disabled={busy}
                                    onClick={() => setPendingDeleteDeposit(row)}
                                  >
                                    Удалить
                                  </OverflowMenuItem>
                                </OverflowMenu>
                              </Td>
                            ) : null}
                          </tr>
                          {editing ? (
                            <tr
                              onKeyDown={(event) => {
                                if (busy) return;
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  cancelDeposit(row);
                                }
                                if (
                                  event.key === "Enter" &&
                                  (event.target as HTMLElement).tagName === "INPUT"
                                ) {
                                  event.preventDefault();
                                  void handleSaveDepositEdit(row.id);
                                }
                              }}
                            >
                              <td colSpan={6}>
                                <div className={styles.metadataEdit}>
                                  <Field htmlFor={`deposit-name-${row.id}`} label="Название">
                                    <Input
                                      id={`deposit-name-${row.id}`}
                                      aria-label={`Название — ${row.name}`}
                                      disabled={busy}
                                      value={draft.name}
                                      onChange={(event) =>
                                        patchDeposit(row, { name: event.target.value })
                                      }
                                    />
                                  </Field>
                                  <Field htmlFor={`deposit-type-${row.id}`} label="Тип">
                                    <Select
                                      id={`deposit-type-${row.id}`}
                                      aria-label={`Тип — ${row.name}`}
                                      disabled={busy}
                                      value={draft.deposit_type}
                                      onChange={(event) =>
                                        patchDeposit(row, { deposit_type: event.target.value })
                                      }
                                    >
                                      <option value="deposit">Депозит</option>
                                      <option value="savings">Накопления</option>
                                    </Select>
                                  </Field>
                                  <Field htmlFor={`deposit-rate-${row.id}`} label="Ставка">
                                    <MonthMoneyInput
                                      id={`deposit-rate-${row.id}`}
                                      aria-label={`Ставка — ${row.name}`}
                                      disabled={busy}
                                      suffix="%"
                                      value={draft.annual_rate}
                                      onChange={(value) =>
                                        patchDeposit(row, { annual_rate: value })
                                      }
                                    />
                                  </Field>
                                </div>
                                <div className={styles.rowEditActions}>
                                  <Button
                                    disabled={busy}
                                    onClick={() => void handleSaveDepositEdit(row.id)}
                                    type="button"
                                    variant="primary"
                                  >
                                    Готово
                                  </Button>
                                  <Button
                                    disabled={busy}
                                    onClick={() => cancelDeposit(row)}
                                    type="button"
                                  >
                                    Отмена
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th scope="row" colSpan={showDepositType ? 2 : 1}>
                        Итого
                        {!readOnly ? (
                          <small className={styles.compactForecast}>
                            Прогноз:{" "}
                            {totalText(
                              depositTotalsUnconfirmed ? null : depositTotals.expected,
                              depositTotals.currency,
                            )}
                          </small>
                        ) : null}
                      </th>
                      <Td numeric data-label="Баланс">
                        {totalText(
                          depositTotalsUnconfirmed ? null : depositTotals.balance,
                          depositTotals.currency,
                        )}
                      </Td>
                      <Td data-label="Ставка" />
                      <Td numeric data-label="Прогноз">
                        {totalText(
                          depositTotalsUnconfirmed ? null : depositTotals.expected,
                          depositTotals.currency,
                        )}
                      </Td>
                      <Td numeric data-label="Получено">
                        {totalText(
                          depositTotalsUnconfirmed ? null : depositTotals.actual,
                          depositTotals.currency,
                        )}
                      </Td>
                    </tr>
                  </tfoot>
                </Table>
              )}

              {emptyDeposits.length > 0 ? (
                <button
                  type="button"
                  aria-expanded={showEmptyDeposits}
                  onClick={() => setShowEmptyDeposits(!showEmptyDeposits)}
                >
                  {showEmptyDeposits ? "Скрыть пустые" : `ещё ${emptyDeposits.length} пустых`}
                </button>
              ) : null}
              {editDeposits ? (
                <MonthSaveBar changed={changedDepositFields}>
                  <Button
                    disabled={busy || readOnly}
                    onClick={() => void handleSaveDepositEdit()}
                    type="button"
                    variant="primary"
                  >
                    Сохранить остатки
                  </Button>
                  <Button disabled={busy} onClick={() => setEditDeposits(null)} type="button">
                    Отмена
                  </Button>
                </MonthSaveBar>
              ) : null}
              {depositTotalsUnconfirmed ? (
                <p className={styles.hint} role="status">
                  {unresolvedCreate
                    ? "Не удалось подтвердить создание вклада. Проверь список вкладов и перезапусти приложение перед повторным добавлением."
                    : "Итоги вкладов уточняются."}{" "}
                  <button
                    disabled={busy}
                    onClick={() => void refreshDepositDisplay()}
                    type="button"
                  >
                    Обновить
                  </button>
                </p>
              ) : null}
              {depositTotals.mixed ? (
                <p className={styles.hint} role="status">
                  Строки в разных валютах: итог показан без конвертации.
                </p>
              ) : null}

              {!readOnly ? (
                <Button
                  type="button"
                  aria-expanded={showNewDeposit}
                  onClick={() => setShowNewDeposit(!showNewDeposit)}
                >
                  + Добавить вклад
                </Button>
              ) : null}
              {!readOnly && showNewDeposit ? (
                <form className="form-stack asset-form" onSubmit={handleCreateDeposit}>
                  <p className="panel__label" style={{ marginBottom: 0 }}>
                    Новый вклад
                  </p>
                  <div className="editor-grid">
                    <Field htmlFor="dep-name" label="Название вклада">
                      <Input
                        disabled={busy}
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
                        disabled={busy}
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
                        disabled={busy}
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
                      <MonthMoneyInput
                        className="input--money"
                        disabled={busy}
                        id="dep-balance"
                        inputMode="decimal"
                        onChange={(value) => {
                          setDepositDraft({ ...depositDraft, balance: value });
                          setDepositDraftTouched(true);
                        }}
                        required
                        value={depositDraft.balance}
                      />
                    </Field>
                    <Field htmlFor="dep-rate" label="Годовая ставка %">
                      <MonthMoneyInput
                        className="input--money"
                        disabled={busy}
                        id="dep-rate"
                        suffix="%"
                        onChange={(value) => {
                          setDepositDraft({ ...depositDraft, annual_rate: value });
                          setDepositDraftTouched(true);
                        }}
                        value={depositDraft.annual_rate}
                      />
                    </Field>
                    <Field htmlFor="dep-actual" label="Факт. процент">
                      <MonthMoneyInput
                        className="input--money"
                        disabled={busy}
                        id="dep-actual"
                        onChange={(value) => {
                          setDepositDraft({ ...depositDraft, actual_interest: value });
                          setDepositDraftTouched(true);
                        }}
                        value={depositDraft.actual_interest}
                      />
                    </Field>
                  </div>
                  <Button
                    disabled={busy || readOnly || Boolean(unresolvedCreate)}
                    type="submit"
                    variant="primary"
                  >
                    {pendingCreated ? "Проверить создание" : "Добавить вклад"}
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
          ) : null}

          {!readOnly || cashRows.length > 0 || cashForeign ? (
            <Panel
              action={
                cashTotalText !== cashInCapitalText ? (
                  <Badge>
                    деньги {cashTotalText} · в капитале {cashInCapitalText}
                  </Badge>
                ) : undefined
              }
              label=""
              title="Денежные средства"
            >
              {cashForeign ? (
                <div className="inline-alert inline-alert--error" role="alert">
                  {CASH_FOREIGN_MESSAGE}
                </div>
              ) : cashRows.length === 0 ? (
                <EmptyState description="Наличных позиций нет." inline title="Пусто" />
              ) : (
                <Table
                  aria-label="Деньги по счетам"
                  className={`month-cash-table ${styles.cashTable}`}
                >
                  <thead>
                    <tr>
                      <Th scope="col">Название</Th>
                      <Th scope="col" numeric>
                        Сумма
                      </Th>
                      {showCashCapital ? <Th scope="col">В капитале</Th> : null}
                      {!readOnly ? (
                        <Th scope="col" className="month-cash-table__actions">
                          Действия
                        </Th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {cashRows.map((row) => (
                      <tr key={row.id}>
                        <Td>
                          {row.name}
                          {!readOnly && !row.include_in_capital ? (
                            <small className={styles.cashAccount}>не в капитале</small>
                          ) : null}
                          {cashRows.filter((cash) => cash.name === row.name).length > 1 &&
                          row.account_id != null ? (
                            <small className={styles.cashAccount}>
                              {accounts.find((account) => account.id === row.account_id)?.name}
                            </small>
                          ) : null}
                        </Td>
                        <Td numeric>
                          {!readOnly ? (
                            <MonthMoneyInput
                              aria-label={`Сумма — ${row.name}`}
                              disabled={busy}
                              suffix={currencySuffix(row.currency)}
                              value={cashEdits[row.id] ?? moneyAmount(row.amount)}
                              onChange={(value) => {
                                setNotice(null);
                                setCashEdits((previous) => ({ ...previous, [row.id]: value }));
                              }}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" && cashEdits[row.id] !== undefined) {
                                  event.preventDefault();
                                  void handleToggleCashCapital(row, cashEdits[row.id]);
                                }
                                if (event.key === "Escape" && !busy)
                                  setCashEdits((previous) => {
                                    const next = { ...previous };
                                    delete next[row.id];
                                    return next;
                                  });
                              }}
                            />
                          ) : (
                            formatMoney(moneyAmount(row.amount), {
                              currency: currencySuffix(row.currency),
                            })
                          )}
                        </Td>
                        {readOnly && showCashCapital ? (
                          <Td>{row.include_in_capital ? "да" : "нет"}</Td>
                        ) : null}
                        {!readOnly ? (
                          <Td className="month-cash-table__actions">
                            <OverflowMenu label={`Действия для денежной позиции «${row.name}»`}>
                              <OverflowMenuItem
                                disabled={busy}
                                onClick={() => void handleToggleCashCapital(row)}
                              >
                                {row.include_in_capital
                                  ? "Исключить из капитала"
                                  : "Включить в капитал"}
                              </OverflowMenuItem>
                              <OverflowMenuItem
                                danger
                                disabled={busy || readOnly}
                                onClick={() => setPendingDeleteCash(row)}
                              >
                                Удалить
                              </OverflowMenuItem>
                            </OverflowMenu>
                          </Td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <Td>Всего денег</Td>
                      <Td numeric>{cashTotalText}</Td>
                      {readOnly && showCashCapital ? (
                        <Td>В капитале: {cashInCapitalText}</Td>
                      ) : null}
                      {!readOnly ? (
                        <Td>{showCashCapital ? `В капитале: ${cashInCapitalText}` : null}</Td>
                      ) : null}
                    </tr>
                  </tfoot>
                </Table>
              )}

              {cashRows.length === 0 || cashForeign ? (
                <p>
                  Всего денег: <strong>{cashTotalText}</strong>
                </p>
              ) : null}
              {!readOnly
                ? cashRows
                    .filter((row) => cashEdits[row.id] !== undefined)
                    .map((row) => (
                      <MonthSaveBar key={row.id} changed={1}>
                        <Button
                          disabled={busy}
                          onClick={() => void handleToggleCashCapital(row, cashEdits[row.id])}
                          type="button"
                          variant="primary"
                        >
                          Сохранить сумму — {row.name}
                        </Button>
                      </MonthSaveBar>
                    ))
                : null}
              {!cashTotalQuery.isPending &&
              !totalUnconfirmed &&
              !(cashTotal && cashTotalQuery.isSuccess) ? (
                <div className="inline-alert inline-alert--warn" role="status">
                  Итоги денег за выбранный месяц недоступны: сумма не подменяется нулём, полнота
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
                <Button
                  type="button"
                  aria-expanded={showNewCash}
                  onClick={() => setShowNewCash(!showNewCash)}
                >
                  + Добавить денежную позицию
                </Button>
              ) : null}
              {!readOnly && showNewCash ? (
                <form className="form-stack asset-form" onSubmit={handleCreateCash}>
                  <p className="panel__label section-form-label">Новая денежная позиция</p>
                  <div className="editor-grid">
                    <Field htmlFor="cash-name" label="Название денежной позиции">
                      <Input
                        disabled={busy}
                        id="cash-name"
                        onChange={(event) => {
                          setCashDraft({ ...cashDraft, name: event.target.value });
                          setCashDraftTouched(true);
                        }}
                        required
                        value={cashDraft.name}
                      />
                    </Field>
                    <Field htmlFor="cash-amount" label="Сумма денег">
                      <MonthMoneyInput
                        className="input--money"
                        disabled={busy}
                        id="cash-amount"
                        inputMode="decimal"
                        onChange={(value) => {
                          setCashDraft({ ...cashDraft, amount: value });
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
                      disabled={busy}
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
          ) : null}

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
