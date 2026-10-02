import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import {
  createDebt,
  deleteDebt,
  linkDebtToAccount,
  listDebts,
  unlinkDebtFromAccount,
  updateDebt,
} from "../api/debts";
import { createProperty, deleteProperty, listProperties, updateProperty } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import type {
  Account,
  DashboardMortgage,
  DebtEntry,
  MoneyValue,
  PropertySnapshot,
} from "../api/types";
import { LinkedPairContext } from "../components/LinkedPairContext";
import {
  Badge,
  Button,
  ConfirmDialog,
  Field,
  Input,
  MoneyAmount,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatPercent, normalizeRateInput } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, DEBT_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";
import { queryKeys } from "../queryClient";
import editorStyles from "./UiV2MonthEditor.module.css";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import leafStyles from "./UiV2MonthLiabilities.module.css";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

/** Section id this leaf registers with the month editor frame (#554/#564). */
export const MONTH_LIABILITIES_SECTION_ID = "liabilities";

const LINK_ACCOUNT_EMPTY_HINT =
  "Нет доступных счетов для связи: нужны наличные, депозит или накопительный счёт, включённые в капитал.";
const LINK_ACCOUNT_STALE_HINT =
  "Текущая связь сохранена, но этот счёт нельзя выбрать заново. Выбери другой доступный счёт.";
const LINK_AVAILABLE_HINT = "Связь доступна для кредитки, включённой в ликвидный капитал.";

const DEBT_CONFIRM_ERROR = "Долг не подтверждён повторной загрузкой.";
const PROPERTY_CONFIRM_ERROR = "Объект недвижимости не подтверждён повторной загрузкой.";
const LINK_CONFIRM_ERROR = "Связь не подтверждена повторной загрузкой.";
const UNLINK_CONFIRM_ERROR = "Отвязка не подтверждена повторной загрузкой.";
const DEBT_DELETE_CONFIRM_ERROR = "Удаление долга не подтверждено повторной загрузкой.";
const PROPERTY_DELETE_CONFIRM_ERROR = "Удаление объекта не подтверждено повторной загрузкой.";
const FOREIGN_DEBTS_ERROR = "Долги относятся к другому месяцу: чтение отклонено.";
const FOREIGN_PROPERTIES_ERROR = "Недвижимость относится к другому месяцу: чтение отклонено.";
const FOREIGN_CONTEXT_ERROR = "Сводка выбранного месяца недоступна: чтение отклонено.";

type DebtAddDraft = {
  name: string;
  debt_type: string;
  current_balance: string;
  annual_rate: string;
  next_due_date: string;
  contract_end_date: string;
};

type DebtDraft = DebtAddDraft & { include_in_liquid_capital: boolean };

type DebtWrite = {
  debt_type: string;
  name: string;
  current_balance: MoneyValue;
  include_in_liquid_capital: boolean;
  annual_rate: string | null;
  next_due_date: string | null;
  contract_end_date: string | null;
};

type PropertyDraft = {
  name: string;
  estimated_value: string;
  mortgage_balance: string;
  monthly_payment: string;
  mortgage_annual_rate: string;
};

type PropertyWrite = {
  name: string;
  estimated_value: MoneyValue;
  mortgage_balance: MoneyValue;
  monthly_payment: MoneyValue;
  mortgage_annual_rate: string | null;
};

type MonthLiabilitiesKeys = {
  accounts: QueryKey;
  dashboard: QueryKey;
  debts: QueryKey;
  properties: QueryKey;
  summary: QueryKey;
};

const INITIAL_DEBT_DRAFT: DebtAddDraft = {
  name: "Кредитка",
  debt_type: "credit_card",
  current_balance: "",
  annual_rate: "",
  next_due_date: "",
  contract_end_date: "",
};

const INITIAL_PROPERTY_DRAFT: PropertyDraft = {
  name: "",
  estimated_value: "",
  mortgage_balance: "",
  monthly_payment: "",
  mortgage_annual_rate: "",
};

function isLinkableAccount(account: Account): boolean {
  return (
    (account.account_type === "cash" ||
      account.account_type === "deposit" ||
      account.account_type === "savings") &&
    account.include_in_capital
  );
}

function accountOptionLabel(account: Account): string {
  return `${account.name} · ${labelOf(ACCOUNT_TYPE_LABELS, account.account_type)}`;
}

/**
 * A rate is stored as integer basis points, so the API answers with two
 * fraction digits ("19.90") while the owner may have typed "19.9". Compare the
 * exact decimal text without binary float math and without losing digits.
 */
function sameRateText(expected: string | null, actual: string | null): boolean {
  if (expected === actual) return true;
  if (expected == null || actual == null) return false;
  const trim = (value: string): string => {
    const [whole = "0", fraction = ""] = value.split(".");
    return `${whole}.${fraction.replace(/0+$/, "")}`;
  };
  return trim(expected) === trim(actual);
}

function rowsBelongToMonth(rows: Array<{ reporting_month_id: number }>, monthId: number): boolean {
  return rows.every((row) => row.reporting_month_id === monthId);
}

/**
 * A month-scoped list is accepted only when it settled and every row belongs
 * to the selected month. A failed refresh and a foreign payload are declined
 * as unavailable — never rendered, never reduced to an authoritative empty
 * list, and never offered again as confirmed editable data.
 */
function readListError<T extends { reporting_month_id: number }>(
  query: { data: T[] | undefined; error: unknown; isError: boolean },
  monthId: number,
  foreignMessage: string,
): string | null {
  if (query.isError) return formatApiError(query.error);
  if (query.data !== undefined && !rowsBelongToMonth(query.data, monthId)) return foreignMessage;
  return null;
}

function assertDebtWriteConfirmed(
  rows: DebtEntry[],
  monthId: number,
  debtId: number,
  write: DebtWrite,
): void {
  const row = rows.find((candidate) => candidate.id === debtId);
  if (
    !rowsBelongToMonth(rows, monthId) ||
    row === undefined ||
    row.name !== write.name ||
    row.debt_type !== write.debt_type ||
    moneyAmount(row.current_balance) !== write.current_balance.amount ||
    row.include_in_liquid_capital !== write.include_in_liquid_capital ||
    !sameRateText(row.annual_rate, write.annual_rate) ||
    (row.next_due_date || null) !== write.next_due_date ||
    (row.contract_end_date || null) !== write.contract_end_date
  ) {
    throw new Error(DEBT_CONFIRM_ERROR);
  }
}

function assertPropertyWriteConfirmed(
  rows: PropertySnapshot[],
  monthId: number,
  propertyId: number,
  write: PropertyWrite,
): void {
  const row = rows.find((candidate) => candidate.id === propertyId);
  if (
    !rowsBelongToMonth(rows, monthId) ||
    row === undefined ||
    row.name !== write.name ||
    moneyAmount(row.estimated_value) !== write.estimated_value.amount ||
    moneyAmount(row.mortgage_balance) !== write.mortgage_balance.amount ||
    moneyAmount(row.monthly_payment) !== write.monthly_payment.amount ||
    !sameRateText(row.mortgage_annual_rate, write.mortgage_annual_rate)
  ) {
    throw new Error(PROPERTY_CONFIRM_ERROR);
  }
}

type BlockProps = {
  busy: boolean;
  commit: (work: () => Promise<void>) => Promise<boolean>;
  monthId: number;
  onDirtyChange: (dirty: boolean) => void;
  readOnly: boolean;
  retry: () => void;
  /** Declined read (failed refresh or foreign month) shown instead of rows. */
  unavailable: string | null;
};

/**
 * Native month-editor leaf for #564: debts, linked accounts and property with
 * the supported v1 operations, exact-money transport and a confirmed readback
 * of every write through the canonical API.
 */
export function UiV2MonthLiabilities({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, setDirty } = context;
  const monthId = month.id;
  const queryClient = useQueryClient();
  const keys = useMemo<MonthLiabilitiesKeys>(
    () => ({
      accounts: [...queryKeys.accounts, monthId],
      dashboard: queryKeys.dashboard(monthId),
      debts: queryKeys.debts(monthId),
      properties: queryKeys.properties(monthId),
      summary: ["month-summary", monthId],
    }),
    [monthId],
  );

  const debtsQuery = useQuery({
    queryKey: keys.debts,
    queryFn: ({ signal }) => listDebts(monthId, signal),
    retry: false,
  });
  const propertiesQuery = useQuery({
    queryKey: keys.properties,
    queryFn: ({ signal }) => listProperties(monthId, signal),
    retry: false,
  });
  const accountsQuery = useQuery({
    queryKey: keys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    retry: false,
  });
  const dashboardQuery = useQuery({
    queryKey: keys.dashboard,
    queryFn: ({ signal }) => getDashboard(monthId, signal),
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: keys.summary,
    queryFn: ({ signal }) => getMonthSummary(monthId, signal),
    retry: false,
  });

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [debtsDirty, setDebtsDirty] = useState(false);
  const [propertiesDirty, setPropertiesDirty] = useState(false);
  const operation = useRef(0);
  const busyRef = useRef(false);

  // A response started for another month identity must never touch this leaf.
  const activeMonth = useRef(monthId);
  useEffect(() => {
    if (activeMonth.current === monthId) return;
    activeMonth.current = monthId;
    operation.current += 1;
    busyRef.current = false;
    setBusy(false);
    setActionError(null);
  }, [monthId]);

  useEffect(() => {
    setDirty(MONTH_LIABILITIES_SECTION_ID, debtsDirty || propertiesDirty);
  }, [debtsDirty, propertiesDirty, setDirty]);

  useEffect(
    () => () => {
      operation.current += 1;
      busyRef.current = false;
      setDirty(MONTH_LIABILITIES_SECTION_ID, false);
    },
    [setDirty],
  );

  /**
   * Runs one mutation with its confirmed canonical readback. Derived month
   * reads are invalidated only after the readback passed, and a response that
   * arrives after another month was selected is dropped.
   */
  async function commit(work: () => Promise<void>): Promise<boolean> {
    if (readOnly || busyRef.current) return false;
    const token = ++operation.current;
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await work();
      if (operation.current !== token) return false;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.dashboard }),
        queryClient.invalidateQueries({ queryKey: keys.summary }),
      ]);
      return operation.current === token;
    } catch (cause) {
      if (operation.current === token) setActionError(formatApiError(cause));
      return false;
    } finally {
      if (operation.current === token) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  function retryAll() {
    void Promise.all([
      debtsQuery.refetch(),
      propertiesQuery.refetch(),
      accountsQuery.refetch(),
      dashboardQuery.refetch(),
      summaryQuery.refetch(),
    ]);
  }

  const accounts = accountsQuery.data ?? [];
  const dashboard = dashboardQuery.data;
  const summaryRead = summaryQuery.data;

  // Month identity is checked before anything is rendered, totals are derived
  // or a row action is offered: a declined list reaches the blocks as empty
  // and the block shows an explicit unavailable state instead of rows.
  const debtsUnavailable = readListError(debtsQuery, monthId, FOREIGN_DEBTS_ERROR);
  const propertiesUnavailable = readListError(propertiesQuery, monthId, FOREIGN_PROPERTIES_ERROR);
  const debts = debtsUnavailable === null ? (debtsQuery.data ?? []) : [];
  const properties = propertiesUnavailable === null ? (propertiesQuery.data ?? []) : [];

  // Month-scoped dashboard/summary context keeps the same identity gate.
  const dashboardForeign = dashboard !== undefined && dashboard.month?.id !== monthId;
  const summaryForeign = summaryRead !== undefined && summaryRead.month?.id !== monthId;
  const linkedPairs = dashboardForeign
    ? null
    : dashboard
      ? (dashboard.summary?.liquid_capital?.linked_pairs ?? [])
      : null;
  const mortgage: DashboardMortgage | null = dashboardForeign
    ? null
    : (dashboard?.mortgage ?? null);
  const coveragePct = summaryForeign ? null : (summaryRead?.coverage?.coverage_pct ?? null);
  let linkedPairError: string | null = null;
  if (dashboardQuery.isError) {
    linkedPairError = formatApiError(dashboardQuery.error);
  } else if (dashboardForeign) {
    linkedPairError = FOREIGN_CONTEXT_ERROR;
  } else if (accountsQuery.isError) {
    linkedPairError = formatApiError(accountsQuery.error);
  }

  if (
    debtsQuery.isPending ||
    propertiesQuery.isPending ||
    accountsQuery.isPending ||
    dashboardQuery.isPending ||
    summaryQuery.isPending
  ) {
    return <UiV2Loading label="Загружаем долги и недвижимость…" />;
  }

  const paused = [debtsQuery, propertiesQuery, accountsQuery, dashboardQuery, summaryQuery].some(
    (query) => query.fetchStatus === "paused",
  );
  if (paused) {
    return (
      <UiV2Notice title="Не удалось подтвердить долги и недвижимость" retry={retryAll}>
        Проверь соединение с локальным приложением и повтори чтение.
      </UiV2Notice>
    );
  }

  return (
    <div className={leafStyles.leaf}>
      {actionError ? (
        <p className={editorStyles.warning} role="alert">
          {actionError}
        </p>
      ) : null}
      <DebtBlock
        accounts={accounts}
        busy={busy}
        commit={commit}
        debts={debts}
        key={`debts-${monthId}`}
        monthId={monthId}
        onDirtyChange={setDebtsDirty}
        readOnly={readOnly}
        retry={() => void debtsQuery.refetch()}
        unavailable={debtsUnavailable}
      />
      <LinkedPairContext
        accounts={accounts}
        debts={debts}
        error={linkedPairError}
        label="Связи"
        pairs={linkedPairs}
        title="Контекст связанных пар"
      />
      <PropertyBlock
        busy={busy}
        commit={commit}
        coveragePct={coveragePct}
        key={`properties-${monthId}`}
        monthId={monthId}
        mortgage={mortgage}
        onDirtyChange={setPropertiesDirty}
        properties={properties}
        readOnly={readOnly}
        retry={() => void propertiesQuery.refetch()}
        unavailable={propertiesUnavailable}
      />
    </div>
  );
}

function DebtBlock({
  accounts,
  busy,
  commit,
  debts,
  monthId,
  onDirtyChange,
  readOnly,
  retry,
  unavailable,
}: BlockProps & { accounts: Account[]; debts: DebtEntry[] }) {
  const queryClient = useQueryClient();
  const debtsKey = useMemo<QueryKey>(() => queryKeys.debts(monthId), [monthId]);
  const [addDraft, setAddDraft] = useState<DebtAddDraft>(INITIAL_DEBT_DRAFT);
  const [addTouched, setAddTouched] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<DebtDraft | null>(null);
  const [linkingId, setLinkingId] = useState<number | null>(null);
  const [linkAccountId, setLinkAccountId] = useState("");
  const [unlinkTarget, setUnlinkTarget] = useState<DebtEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DebtEntry | null>(null);

  const dirty = addTouched || editingId !== null;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(
    () => () => {
      onDirtyChange(false);
    },
    [onDirtyChange],
  );

  const eligibleAccounts = useMemo(() => accounts.filter(isLinkableAccount), [accounts]);
  const cardDebtTotal = useMemo(
    () =>
      sumMoneyAmounts(
        debts
          .filter((debt) => debt.debt_type === "credit_card")
          .map((debt) => moneyAmount(debt.current_balance)),
      ),
    [debts],
  );

  function accountNameFor(accountId: number | null): string {
    if (accountId == null) return "Не связан";
    return accounts.find((account) => account.id === accountId)?.name ?? "Счёт не найден";
  }

  function cancelLinkingDebt() {
    setLinkingId(null);
    setLinkAccountId("");
  }

  function startLinkingDebt(row: DebtEntry) {
    setLinkingId(row.id);
    setLinkAccountId(row.linked_account_id == null ? "" : String(row.linked_account_id));
  }

  function startEditingDebt(row: DebtEntry) {
    cancelLinkingDebt();
    setEditingId(row.id);
    setEditDraft({
      name: row.name,
      debt_type: row.debt_type,
      current_balance: moneyAmount(row.current_balance),
      include_in_liquid_capital: row.include_in_liquid_capital,
      annual_rate: row.annual_rate ?? "",
      next_due_date: row.next_due_date ?? "",
      contract_end_date: row.contract_end_date ?? "",
    });
  }

  async function confirmReadback(rows: DebtEntry[]): Promise<void> {
    if (!rowsBelongToMonth(rows, monthId)) throw new Error(DEBT_CONFIRM_ERROR);
    queryClient.setQueryData(debtsKey, rows);
  }

  async function addDebt(event: FormEvent) {
    event.preventDefault();
    const draft = addDraft;
    const saved = await commit(async () => {
      const name = draft.name.trim();
      const balance = normalizeMoneyInput(draft.current_balance);
      if (!name || !balance) throw new Error("Имя и баланс долга обязательны");
      if (draft.annual_rate.trim() !== "" && normalizeRateInput(draft.annual_rate) === null) {
        throw new Error("Ставка — неотрицательное число, пусто — неизвестно");
      }
      const write: DebtWrite = {
        debt_type: draft.debt_type,
        name,
        current_balance: rub(balance),
        include_in_liquid_capital: true,
        annual_rate: normalizeRateInput(draft.annual_rate),
        next_due_date: draft.next_due_date || null,
        contract_end_date: draft.contract_end_date || null,
      };
      const created = await createDebt({ reporting_month_id: monthId, ...write });
      const rows = await listDebts(monthId);
      assertDebtWriteConfirmed(rows, monthId, created.id, write);
      await confirmReadback(rows);
    });
    if (saved) {
      setAddDraft((previous) => ({
        ...previous,
        current_balance: "",
        annual_rate: "",
        next_due_date: "",
        contract_end_date: "",
      }));
      setAddTouched(false);
    }
  }

  async function saveDebtEdit() {
    if (editingId === null || editDraft === null) return;
    const debtId = editingId;
    const draft = editDraft;
    const saved = await commit(async () => {
      const name = draft.name.trim();
      const balance = normalizeMoneyInput(draft.current_balance);
      if (!name || !balance) throw new Error("Имя и баланс долга обязательны");
      if (draft.annual_rate.trim() !== "" && normalizeRateInput(draft.annual_rate) === null) {
        throw new Error("Ставка — неотрицательное число, пусто — неизвестно");
      }
      const write: DebtWrite = {
        debt_type: draft.debt_type,
        name,
        current_balance: rub(balance),
        include_in_liquid_capital: draft.include_in_liquid_capital,
        annual_rate: normalizeRateInput(draft.annual_rate),
        next_due_date: draft.next_due_date || null,
        contract_end_date: draft.contract_end_date || null,
      };
      await updateDebt(debtId, write);
      const rows = await listDebts(monthId);
      assertDebtWriteConfirmed(rows, monthId, debtId, write);
      await confirmReadback(rows);
    });
    if (saved) {
      setEditingId(null);
      setEditDraft(null);
    }
  }

  async function saveDebtLink(row: DebtEntry) {
    const accountId = Number(linkAccountId);
    const saved = await commit(async () => {
      if (!Number.isInteger(accountId) || accountId < 1) {
        throw new Error("Выбери счёт для связи.");
      }
      await linkDebtToAccount(row.id, accountId);
      const rows = await listDebts(monthId);
      const linked = rows.find((candidate) => candidate.id === row.id);
      if (!rowsBelongToMonth(rows, monthId) || linked === undefined) {
        throw new Error(LINK_CONFIRM_ERROR);
      }
      if (linked.linked_account_id !== accountId) throw new Error(LINK_CONFIRM_ERROR);
      await confirmReadback(rows);
    });
    if (saved) cancelLinkingDebt();
  }

  async function confirmDebtUnlink(target: DebtEntry) {
    await commit(async () => {
      await unlinkDebtFromAccount(target.id);
      const rows = await listDebts(monthId);
      const unlinked = rows.find((candidate) => candidate.id === target.id);
      if (!rowsBelongToMonth(rows, monthId) || unlinked === undefined) {
        throw new Error(UNLINK_CONFIRM_ERROR);
      }
      if (unlinked.linked_account_id != null) throw new Error(UNLINK_CONFIRM_ERROR);
      await confirmReadback(rows);
    });
    setUnlinkTarget(null);
  }

  async function confirmDebtDelete(target: DebtEntry) {
    await commit(async () => {
      await deleteDebt(target.id);
      const rows = await listDebts(monthId);
      if (!rowsBelongToMonth(rows, monthId) || rows.some((row) => row.id === target.id)) {
        throw new Error(DEBT_DELETE_CONFIRM_ERROR);
      }
      await confirmReadback(rows);
    });
    setDeleteTarget(null);
  }

  // A declined read never reaches rows, totals or a write path.
  if (unavailable !== null) {
    return (
      <section aria-label="Долги месяца" className={editorStyles.panel}>
        <div className={leafStyles.heading}>
          <div>
            <p className={leafStyles.eyebrow}>Обязательства</p>
            <h2>Долги</h2>
          </div>
          <Badge>—</Badge>
        </div>
        <UiV2Notice title="Не удалось загрузить обязательства" retry={retry}>
          {unavailable}
        </UiV2Notice>
      </section>
    );
  }

  return (
    <section aria-label="Долги месяца" className={editorStyles.panel}>
      <div className={leafStyles.heading}>
        <div>
          <p className={leafStyles.eyebrow}>Обязательства</p>
          <h2>Долги</h2>
        </div>
        <Badge>
          Кредитные карты: <MoneyAmount amount={cardDebtTotal} />
        </Badge>
      </div>
      {dirty ? (
        <p className={leafStyles.savedNote} role="note">
          Итоги ниже посчитаны по сохранённым данным и не учитывают несохранённые правки.
        </p>
      ) : null}
      {debts.length === 0 ? (
        <p className={leafStyles.empty}>Долгов нет.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Название</Th>
              <Th>Тип</Th>
              <Th numeric>Баланс</Th>
              <Th>Ставка</Th>
              <Th>Ближайший платёж</Th>
              <Th>Окончание</Th>
              <Th>Учёт</Th>
              <Th>Связанный счёт</Th>
              <Th>Действия</Th>
            </tr>
          </thead>
          <tbody>
            {debts.map((row) => {
              return (
                <tr key={row.id}>
                  <Td>{row.name}</Td>
                  <Td>{labelOf(DEBT_TYPE_LABELS, row.debt_type)}</Td>
                  <Td numeric>
                    <MoneyAmount amount={moneyAmount(row.current_balance)} />
                  </Td>
                  <Td>
                    <span className={leafStyles.muted}>
                      {formatPercent(row.annual_rate, { digits: 2, empty: "не указано" })}
                    </span>
                  </Td>
                  <Td>
                    <span className={leafStyles.muted}>{formatDate(row.next_due_date)}</span>
                  </Td>
                  <Td>
                    <span className={leafStyles.muted}>{formatDate(row.contract_end_date)}</span>
                  </Td>
                  <Td>
                    <Badge tone={row.include_in_liquid_capital ? "ok" : "neutral"}>
                      {row.include_in_liquid_capital ? "В капитале" : "Отдельно"}
                    </Badge>
                  </Td>
                  <Td>
                    <div className={leafStyles.linkControl}>
                      <div className={leafStyles.linkAccount}>
                        <Badge tone={row.linked_account_id == null ? "neutral" : "ok"}>
                          {row.linked_account_id == null ? "Не связано" : "Связано"}
                        </Badge>
                        {row.linked_account_id != null ? (
                          <strong className={leafStyles.linkName}>
                            {accountNameFor(row.linked_account_id)}
                          </strong>
                        ) : null}
                      </div>
                      {row.linked_account_id != null ? (
                        <div className={leafStyles.rowActions}>
                          <Button
                            disabled={busy || readOnly || editingId !== null}
                            onClick={() => startLinkingDebt(row)}
                            size="sm"
                            type="button"
                          >
                            Изменить связь
                          </Button>
                          <Button
                            disabled={busy || readOnly || editingId !== null}
                            onClick={() => setUnlinkTarget(row)}
                            size="sm"
                            type="button"
                          >
                            Отвязать
                          </Button>
                        </div>
                      ) : row.debt_type === "credit_card" && row.include_in_liquid_capital ? (
                        <div className={leafStyles.linkControl}>
                          <div className={leafStyles.rowActions}>
                            <Button
                              disabled={
                                busy ||
                                readOnly ||
                                editingId !== null ||
                                eligibleAccounts.length === 0
                              }
                              onClick={() => startLinkingDebt(row)}
                              size="sm"
                              type="button"
                            >
                              Связать счёт
                            </Button>
                          </div>
                          {eligibleAccounts.length === 0 ? (
                            <span className={leafStyles.hint}>{LINK_ACCOUNT_EMPTY_HINT}</span>
                          ) : null}
                        </div>
                      ) : (
                        <span className={leafStyles.hint}>{LINK_AVAILABLE_HINT}</span>
                      )}
                    </div>
                  </Td>
                  <Td>
                    <div className={leafStyles.rowActions}>
                      <Button
                        aria-label={`Изменить долг «${row.name}»`}
                        disabled={busy || readOnly}
                        onClick={() => startEditingDebt(row)}
                        size="sm"
                        type="button"
                      >
                        Изменить
                      </Button>
                      <Button
                        aria-label={`Удалить долг «${row.name}»`}
                        disabled={busy || readOnly}
                        onClick={() => setDeleteTarget(row)}
                        size="sm"
                        type="button"
                      >
                        Удалить
                      </Button>
                    </div>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {(() => {
        const editingRow = debts.find((candidate) => candidate.id === editingId) ?? null;
        const linkingRow = debts.find((candidate) => candidate.id === linkingId) ?? null;
        const edit = editingId !== null ? editDraft : null;
        return (
          <>
            {editingRow && edit ? (
              <form
                aria-label={`Редактирование долга «${editingRow.name}»`}
                className={leafStyles.stackedEditor}
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveDebtEdit();
                }}
              >
                <div className={leafStyles.stackedEditorHeading}>
                  <strong>Редактирование: {editingRow.name}</strong>
                  <Badge tone="info">Черновик</Badge>
                </div>
                <p className={leafStyles.hint}>
                  Сохранённые значения строки и итоги ниже не меняются до нажатия «Сохранить».
                </p>
                <div className={leafStyles.stackedEditorGrid}>
                  <Field htmlFor={`debt-edit-${editingRow.id}-name`} label="Название долга">
                    <Input
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-name`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous ? { ...previous, name: event.target.value } : previous,
                        )
                      }
                      value={edit.name}
                    />
                  </Field>
                  <Field htmlFor={`debt-edit-${editingRow.id}-type`} label="Тип долга">
                    <Select
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-type`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous ? { ...previous, debt_type: event.target.value } : previous,
                        )
                      }
                      value={edit.debt_type}
                    >
                      <option value="credit_card">Кредитная карта</option>
                      <option value="other">Прочее</option>
                    </Select>
                  </Field>
                  <Field
                    htmlFor={`debt-edit-${editingRow.id}-balance`}
                    label="Текущий баланс долга"
                  >
                    <Input
                      className="input--money"
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-balance`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous
                            ? { ...previous, current_balance: event.target.value }
                            : previous,
                        )
                      }
                      value={edit.current_balance}
                    />
                  </Field>
                  <Field htmlFor={`debt-edit-${editingRow.id}-rate`} label="Годовая ставка, %">
                    <Input
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-rate`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous ? { ...previous, annual_rate: event.target.value } : previous,
                        )
                      }
                      placeholder="неизвестно"
                      value={edit.annual_rate}
                    />
                  </Field>
                  <Field
                    htmlFor={`debt-edit-${editingRow.id}-due`}
                    label="Ближайший обязательный платёж"
                  >
                    <Input
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-due`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous ? { ...previous, next_due_date: event.target.value } : previous,
                        )
                      }
                      type="date"
                      value={edit.next_due_date}
                    />
                  </Field>
                  <Field htmlFor={`debt-edit-${editingRow.id}-end`} label="Окончание договора">
                    <Input
                      disabled={busy || readOnly}
                      id={`debt-edit-${editingRow.id}-end`}
                      onChange={(event) =>
                        setEditDraft((previous) =>
                          previous
                            ? { ...previous, contract_end_date: event.target.value }
                            : previous,
                        )
                      }
                      type="date"
                      value={edit.contract_end_date}
                    />
                  </Field>
                  <div className={leafStyles.stackedCheck}>
                    <label
                      className={leafStyles.checkRow}
                      htmlFor={`debt-edit-${editingRow.id}-inc`}
                    >
                      <input
                        checked={edit.include_in_liquid_capital}
                        disabled={busy || readOnly}
                        id={`debt-edit-${editingRow.id}-inc`}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous
                              ? { ...previous, include_in_liquid_capital: event.target.checked }
                              : previous,
                          )
                        }
                        type="checkbox"
                      />
                      Учитывать в ликвидном капитале
                    </label>
                  </div>
                </div>
                <div className={leafStyles.rowActions}>
                  <Button disabled={busy || readOnly} size="sm" type="submit" variant="primary">
                    Сохранить
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() => {
                      setEditingId(null);
                      setEditDraft(null);
                    }}
                    size="sm"
                    type="button"
                  >
                    Отмена
                  </Button>
                </div>
              </form>
            ) : null}
            {linkingRow && linkingId !== null && editingId === null ? (
              <form
                aria-label={`Связь долга «${linkingRow.name}» со счётом`}
                className={leafStyles.stackedEditor}
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveDebtLink(linkingRow);
                }}
              >
                <div className={leafStyles.stackedEditorHeading}>
                  <strong>Связь долга: {linkingRow.name}</strong>
                  <Badge tone={linkingRow.linked_account_id == null ? "neutral" : "ok"}>
                    {linkingRow.linked_account_id == null ? "Не связано" : "Связано"}
                  </Badge>
                </div>
                {linkingRow.linked_account_id != null ? (
                  <p className={leafStyles.hint}>
                    Текущий счёт: {accountNameFor(linkingRow.linked_account_id)}. Итоги посчитаны по
                    сохранённой связи.
                  </p>
                ) : (
                  <p className={leafStyles.hint}>
                    Итоги посчитаны по сохранённым данным и не учитывают несохранённый выбор.
                  </p>
                )}
                <div className={leafStyles.stackedEditorGrid}>
                  <Field
                    htmlFor={`debt-link-${linkingRow.id}-account`}
                    label="Счёт для связи с долгом"
                  >
                    <Select
                      disabled={busy || readOnly || eligibleAccounts.length === 0}
                      id={`debt-link-${linkingRow.id}-account`}
                      onChange={(event) => setLinkAccountId(event.target.value)}
                      value={linkAccountId}
                    >
                      <option value="">Выбери счёт</option>
                      {linkingRow.linked_account_id != null &&
                      !eligibleAccounts.some(
                        (account) => account.id === linkingRow.linked_account_id,
                      ) ? (
                        <option disabled value={linkingRow.linked_account_id}>
                          Текущий связанный счёт · недоступен для новой связи
                        </option>
                      ) : null}
                      {eligibleAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {accountOptionLabel(account)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
                {eligibleAccounts.length === 0 ? (
                  <p className={leafStyles.hint}>{LINK_ACCOUNT_EMPTY_HINT}</p>
                ) : null}
                {linkingRow.linked_account_id != null &&
                !eligibleAccounts.some((account) => account.id === linkingRow.linked_account_id) ? (
                  <p className={leafStyles.hint}>{LINK_ACCOUNT_STALE_HINT}</p>
                ) : null}
                <div className={leafStyles.rowActions}>
                  <Button
                    disabled={
                      busy ||
                      readOnly ||
                      !eligibleAccounts.some((account) => account.id === Number(linkAccountId))
                    }
                    size="sm"
                    type="submit"
                    variant="primary"
                  >
                    Сохранить связь
                  </Button>
                  <Button disabled={busy} onClick={cancelLinkingDebt} size="sm" type="button">
                    Отмена
                  </Button>
                </div>
              </form>
            ) : null}
          </>
        );
      })()}
      <div className={leafStyles.totals}>
        <span>
          Долг по кредитным картам:{" "}
          <strong>
            <MoneyAmount amount={cardDebtTotal} />
          </strong>
        </span>
      </div>
      {!readOnly ? (
        <form className={leafStyles.form} onSubmit={(event) => void addDebt(event)}>
          <div className={leafStyles.formGrid}>
            <Field htmlFor="debt-name" label="Название долга">
              <Input
                disabled={busy || readOnly}
                id="debt-name"
                onChange={(event) => {
                  setAddDraft((previous) => ({ ...previous, name: event.target.value }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.name}
              />
            </Field>
            <Field htmlFor="debt-type" label="Тип долга">
              <Select
                disabled={busy || readOnly}
                id="debt-type"
                onChange={(event) => {
                  setAddDraft((previous) => ({ ...previous, debt_type: event.target.value }));
                  setAddTouched(true);
                }}
                value={addDraft.debt_type}
              >
                <option value="credit_card">Кредитная карта</option>
                <option value="other">Прочее</option>
              </Select>
            </Field>
            <Field htmlFor="debt-bal" label="Текущий баланс долга">
              <Input
                className="input--money"
                disabled={busy || readOnly}
                id="debt-bal"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    current_balance: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.current_balance}
              />
            </Field>
            <Field htmlFor="debt-rate" label="Годовая ставка, % (пусто — неизвестно)">
              <Input
                disabled={busy || readOnly}
                id="debt-rate"
                onChange={(event) => {
                  setAddDraft((previous) => ({ ...previous, annual_rate: event.target.value }));
                  setAddTouched(true);
                }}
                placeholder="неизвестно"
                value={addDraft.annual_rate}
              />
            </Field>
            <Field htmlFor="debt-due" label="Ближайший платёж">
              <Input
                disabled={busy || readOnly}
                id="debt-due"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    next_due_date: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                type="date"
                value={addDraft.next_due_date}
              />
            </Field>
            <Field htmlFor="debt-end" label="Окончание договора">
              <Input
                disabled={busy || readOnly}
                id="debt-end"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    contract_end_date: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                type="date"
                value={addDraft.contract_end_date}
              />
            </Field>
          </div>
          <Button disabled={busy} type="submit" variant="primary">
            Добавить долг
          </Button>
        </form>
      ) : null}
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Отвязать"
        description={
          unlinkTarget
            ? `Отвязать долг «${unlinkTarget.name}» от счёта «${accountNameFor(unlinkTarget.linked_account_id)}»?`
            : ""
        }
        onCancel={() => setUnlinkTarget(null)}
        onConfirm={() => {
          if (unlinkTarget) void confirmDebtUnlink(unlinkTarget);
        }}
        open={unlinkTarget !== null}
        title="Отвязать счёт?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={deleteTarget ? `Удалить долг «${deleteTarget.name}»?` : ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) void confirmDebtDelete(deleteTarget);
        }}
        open={deleteTarget !== null}
        title="Удалить долг?"
      />
    </section>
  );
}

function PropertyBlock({
  busy,
  commit,
  coveragePct,
  monthId,
  mortgage,
  onDirtyChange,
  properties,
  readOnly,
  retry,
  unavailable,
}: BlockProps & {
  coveragePct: string | null;
  mortgage: DashboardMortgage | null;
  properties: PropertySnapshot[];
}) {
  const queryClient = useQueryClient();
  const propertiesKey = useMemo<QueryKey>(() => queryKeys.properties(monthId), [monthId]);
  const [addDraft, setAddDraft] = useState<PropertyDraft>(INITIAL_PROPERTY_DRAFT);
  const [addTouched, setAddTouched] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<PropertyDraft | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PropertySnapshot | null>(null);

  const dirty = addTouched || editingId !== null;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(
    () => () => {
      onDirtyChange(false);
    },
    [onDirtyChange],
  );

  const propertyValueTotal = useMemo(
    () => sumMoneyAmounts(properties.map((row) => moneyAmount(row.estimated_value))),
    [properties],
  );
  const mortgageBalanceTotal = useMemo(
    () => sumMoneyAmounts(properties.map((row) => moneyAmount(row.mortgage_balance))),
    [properties],
  );
  const paymentTotal = useMemo(
    () => sumMoneyAmounts(properties.map((row) => moneyAmount(row.monthly_payment))),
    [properties],
  );

  function startEditingProperty(row: PropertySnapshot) {
    setEditingId(row.id);
    setEditDraft({
      name: row.name,
      estimated_value: moneyAmount(row.estimated_value),
      mortgage_balance: moneyAmount(row.mortgage_balance),
      monthly_payment: moneyAmount(row.monthly_payment),
      mortgage_annual_rate: row.mortgage_annual_rate ?? "",
    });
  }

  async function confirmReadback(rows: PropertySnapshot[]): Promise<void> {
    if (!rowsBelongToMonth(rows, monthId)) throw new Error(PROPERTY_CONFIRM_ERROR);
    queryClient.setQueryData(propertiesKey, rows);
  }

  async function addProperty(event: FormEvent) {
    event.preventDefault();
    const draft = addDraft;
    const saved = await commit(async () => {
      const name = draft.name.trim();
      const value = normalizeMoneyInput(draft.estimated_value);
      const balance = normalizeMoneyInput(draft.mortgage_balance);
      const payment = normalizeMoneyInput(draft.monthly_payment);
      if (!name || !value || !balance || !payment) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      if (
        draft.mortgage_annual_rate.trim() !== "" &&
        normalizeRateInput(draft.mortgage_annual_rate) === null
      ) {
        throw new Error("Ставка ипотеки — неотрицательное число, пусто — неизвестно");
      }
      const write: PropertyWrite = {
        name,
        estimated_value: rub(value),
        mortgage_balance: rub(balance),
        monthly_payment: rub(payment),
        mortgage_annual_rate: normalizeRateInput(draft.mortgage_annual_rate),
      };
      const created = await createProperty({ reporting_month_id: monthId, ...write });
      const rows = await listProperties(monthId);
      assertPropertyWriteConfirmed(rows, monthId, created.id, write);
      await confirmReadback(rows);
    });
    if (saved) {
      setAddDraft(INITIAL_PROPERTY_DRAFT);
      setAddTouched(false);
    }
  }

  async function savePropertyEdit() {
    if (editingId === null || editDraft === null) return;
    const propertyId = editingId;
    const draft = editDraft;
    const saved = await commit(async () => {
      const name = draft.name.trim();
      const value = normalizeMoneyInput(draft.estimated_value);
      const balance = normalizeMoneyInput(draft.mortgage_balance);
      const payment = normalizeMoneyInput(draft.monthly_payment);
      if (!name || !value || !balance || !payment) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      if (
        draft.mortgage_annual_rate.trim() !== "" &&
        normalizeRateInput(draft.mortgage_annual_rate) === null
      ) {
        throw new Error("Ставка ипотеки — неотрицательное число, пусто — неизвестно");
      }
      const write: PropertyWrite = {
        name,
        estimated_value: rub(value),
        mortgage_balance: rub(balance),
        monthly_payment: rub(payment),
        mortgage_annual_rate: normalizeRateInput(draft.mortgage_annual_rate),
      };
      await updateProperty(propertyId, write);
      const rows = await listProperties(monthId);
      assertPropertyWriteConfirmed(rows, monthId, propertyId, write);
      await confirmReadback(rows);
    });
    if (saved) {
      setEditingId(null);
      setEditDraft(null);
    }
  }

  async function confirmPropertyDelete(target: PropertySnapshot) {
    await commit(async () => {
      await deleteProperty(target.id);
      const rows = await listProperties(monthId);
      if (!rowsBelongToMonth(rows, monthId) || rows.some((row) => row.id === target.id)) {
        throw new Error(PROPERTY_DELETE_CONFIRM_ERROR);
      }
      await confirmReadback(rows);
    });
    setDeleteTarget(null);
  }

  // A declined read never reaches rows, totals or a write path.
  if (unavailable !== null) {
    return (
      <section aria-label="Недвижимость месяца" className={editorStyles.panel}>
        <div className={leafStyles.heading}>
          <div>
            <p className={leafStyles.eyebrow}>Обязательства</p>
            <h2>Недвижимость</h2>
          </div>
          <Badge>—</Badge>
        </div>
        <UiV2Notice title="Не удалось загрузить недвижимость" retry={retry}>
          {unavailable}
        </UiV2Notice>
      </section>
    );
  }

  return (
    <section aria-label="Недвижимость месяца" className={editorStyles.panel}>
      <div className={leafStyles.heading}>
        <div>
          <p className={leafStyles.eyebrow}>Обязательства</p>
          <h2>Недвижимость</h2>
        </div>
        <Badge>
          Недвижимость: <MoneyAmount amount={propertyValueTotal} />
        </Badge>
      </div>
      <details className={leafStyles.details}>
        <summary>О недвижимости и покрытии</summary>
        <p>
          Недвижимость не входит в ликвидный капитал. Покрытие ипотеки показывается как ориентир из
          сводки месяца.
        </p>
      </details>
      {properties.length === 0 ? (
        <p className={leafStyles.empty}>Объектов нет.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Объект</Th>
              <Th numeric>Стоимость</Th>
              <Th numeric>Ипотека</Th>
              <Th numeric>Платёж / мес</Th>
              <Th>Ставка</Th>
              <Th>Действия</Th>
            </tr>
          </thead>
          <tbody>
            {properties.map((row) => {
              const editing = editingId === row.id ? editDraft : null;
              return (
                <tr key={row.id}>
                  <Td>
                    {editing ? (
                      <Input
                        aria-label="Название объекта"
                        disabled={busy || readOnly}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous ? { ...previous, name: event.target.value } : previous,
                          )
                        }
                        value={editing.name}
                      />
                    ) : (
                      row.name
                    )}
                  </Td>
                  <Td numeric>
                    {editing ? (
                      <Input
                        aria-label="Стоимость"
                        className="input--money"
                        disabled={busy || readOnly}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous
                              ? { ...previous, estimated_value: event.target.value }
                              : previous,
                          )
                        }
                        value={editing.estimated_value}
                      />
                    ) : (
                      <MoneyAmount amount={moneyAmount(row.estimated_value)} />
                    )}
                  </Td>
                  <Td numeric>
                    {editing ? (
                      <Input
                        aria-label="Остаток ипотеки"
                        className="input--money"
                        disabled={busy || readOnly}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous
                              ? { ...previous, mortgage_balance: event.target.value }
                              : previous,
                          )
                        }
                        value={editing.mortgage_balance}
                      />
                    ) : (
                      <MoneyAmount amount={moneyAmount(row.mortgage_balance)} />
                    )}
                  </Td>
                  <Td numeric>
                    {editing ? (
                      <Input
                        aria-label="Ежемесячный платёж"
                        className="input--money"
                        disabled={busy || readOnly}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous
                              ? { ...previous, monthly_payment: event.target.value }
                              : previous,
                          )
                        }
                        value={editing.monthly_payment}
                      />
                    ) : (
                      <MoneyAmount amount={moneyAmount(row.monthly_payment)} />
                    )}
                  </Td>
                  <Td>
                    {editing ? (
                      <Input
                        aria-label="Годовая ставка ипотеки"
                        disabled={busy || readOnly}
                        onChange={(event) =>
                          setEditDraft((previous) =>
                            previous
                              ? { ...previous, mortgage_annual_rate: event.target.value }
                              : previous,
                          )
                        }
                        placeholder="неизвестно"
                        value={editing.mortgage_annual_rate}
                      />
                    ) : (
                      <span className={leafStyles.muted}>
                        {formatPercent(row.mortgage_annual_rate, {
                          digits: 2,
                          empty: "не указано",
                        })}
                      </span>
                    )}
                  </Td>
                  <Td>
                    <div className={leafStyles.rowActions}>
                      {editing ? (
                        <>
                          <Button
                            disabled={busy || readOnly}
                            onClick={() => void savePropertyEdit()}
                            size="sm"
                            type="button"
                            variant="primary"
                          >
                            OK
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() => {
                              setEditingId(null);
                              setEditDraft(null);
                            }}
                            size="sm"
                            type="button"
                          >
                            Отмена
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            aria-label={`Изменить объект «${row.name}»`}
                            disabled={busy || readOnly}
                            onClick={() => startEditingProperty(row)}
                            size="sm"
                            type="button"
                          >
                            Изменить
                          </Button>
                          <Button
                            aria-label={`Удалить объект «${row.name}»`}
                            disabled={busy || readOnly}
                            onClick={() => setDeleteTarget(row)}
                            size="sm"
                            type="button"
                          >
                            Удалить
                          </Button>
                        </>
                      )}
                    </div>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      <div className={leafStyles.totals}>
        <span>
          Стоимость:{" "}
          <strong>
            <MoneyAmount amount={propertyValueTotal} />
          </strong>
        </span>
        <span>
          Остаток ипотеки:{" "}
          <strong>
            <MoneyAmount amount={mortgageBalanceTotal} />
          </strong>
        </span>
        <span>
          Платёж:{" "}
          <strong>
            <MoneyAmount amount={paymentTotal} />
          </strong>
        </span>
      </div>
      <div className={leafStyles.totals}>
        <span>
          Покрытие ипотеки (ориентир):{" "}
          <strong>{mortgage?.coverage_pct != null ? `${mortgage.coverage_pct}%` : "—"}</strong>
        </span>
        <span>
          Недостаток покрытия:{" "}
          <strong>{mortgage ? <MoneyAmount amount={moneyAmount(mortgage.gap)} /> : "—"}</strong>
        </span>
        <span>
          Покрытие обязательных расходов: <strong>{coveragePct ?? "—"}</strong>
        </span>
      </div>
      {!readOnly ? (
        <form className={leafStyles.form} onSubmit={(event) => void addProperty(event)}>
          <div className={leafStyles.formGrid}>
            <Field htmlFor="prop-name" label="Название объекта">
              <Input
                disabled={busy || readOnly}
                id="prop-name"
                onChange={(event) => {
                  setAddDraft((previous) => ({ ...previous, name: event.target.value }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.name}
              />
            </Field>
            <Field htmlFor="prop-val" label="Стоимость">
              <Input
                className="input--money"
                disabled={busy || readOnly}
                id="prop-val"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    estimated_value: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.estimated_value}
              />
            </Field>
            <Field htmlFor="prop-mort" label="Остаток ипотеки">
              <Input
                className="input--money"
                disabled={busy || readOnly}
                id="prop-mort"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    mortgage_balance: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.mortgage_balance}
              />
            </Field>
            <Field htmlFor="prop-pay" label="Ежемесячный платёж">
              <Input
                className="input--money"
                disabled={busy || readOnly}
                id="prop-pay"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    monthly_payment: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                required
                value={addDraft.monthly_payment}
              />
            </Field>
            <Field htmlFor="prop-rate" label="Годовая ставка, % (пусто — неизвестно)">
              <Input
                disabled={busy || readOnly}
                id="prop-rate"
                onChange={(event) => {
                  setAddDraft((previous) => ({
                    ...previous,
                    mortgage_annual_rate: event.target.value,
                  }));
                  setAddTouched(true);
                }}
                placeholder="неизвестно"
                value={addDraft.mortgage_annual_rate}
              />
            </Field>
          </div>
          <Button disabled={busy} type="submit" variant="primary">
            Добавить объект
          </Button>
        </form>
      ) : null}
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={deleteTarget ? `Удалить «${deleteTarget.name}»?` : ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) void confirmPropertyDelete(deleteTarget);
        }}
        open={deleteTarget !== null}
        title="Удалить объект?"
      />
    </section>
  );
}
