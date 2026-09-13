import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

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
  DashboardLinkedPair,
  DashboardMortgage,
  DebtEntry,
  PropertySnapshot,
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
  Panel,
  Select,
  Table,
  Td,
  Th,
  OverflowMenu,
  OverflowMenuItem,
} from "./ui";
import { LinkedPairContext } from "./LinkedPairContext";
import { formatDate, formatMoney, formatPercent, normalizeRateInput } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, DEBT_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type Props = {
  monthId: number;
  readOnly: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  onLinkedPairChange?: () => void;
  linkedPairRefreshKey?: number;
};

type DebtDraft = {
  name: string;
  debt_type: string;
  current_balance: string;
  include_in_liquid_capital: boolean;
  annual_rate: string;
  next_due_date: string;
  contract_end_date: string;
};

type PropertyDraft = {
  name: string;
  estimated_value: string;
  mortgage_balance: string;
  monthly_payment: string;
  mortgage_annual_rate: string;
};

const LINK_ACCOUNT_EMPTY_HINT =
  "Нет доступных счетов для связи: нужны наличные, депозит или накопительный счёт, включённые в капитал.";
const LINK_ACCOUNT_STALE_HINT =
  "Текущая связь сохранена, но этот счёт нельзя выбрать заново. Выбери другой доступный счёт.";

function isLinkableAccount(account: Account): boolean {
  return (
    (account.account_type === "cash" ||
      account.account_type === "deposit" ||
      account.account_type === "savings") &&
    account.include_in_capital
  );
}

export function MonthLiabilitiesSection({
  monthId,
  readOnly,
  onDirtyChange,
  onLinkedPairChange,
  linkedPairRefreshKey,
}: Props) {
  const [debts, setDebts] = useState<DebtEntry[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [linkedPairs, setLinkedPairs] = useState<DashboardLinkedPair[] | null>(null);
  const [linkedPairError, setLinkedPairError] = useState<string | null>(null);
  const [properties, setProperties] = useState<PropertySnapshot[]>([]);
  const [mortgage, setMortgage] = useState<DashboardMortgage | null>(null);
  const [coveragePct, setCoveragePct] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [debtName, setDebtName] = useState("Кредитка");
  const [debtType, setDebtType] = useState("credit_card");
  const [debtBal, setDebtBal] = useState("");
  const [debtRate, setDebtRate] = useState("");
  const [debtDue, setDebtDue] = useState("");
  const [debtEnd, setDebtEnd] = useState("");
  const [propName, setPropName] = useState("");
  const [propValue, setPropValue] = useState("");
  const [propMortgage, setPropMortgage] = useState("");
  const [propPayment, setPropPayment] = useState("");
  const [propRate, setPropRate] = useState("");
  const [debtDraftTouched, setDebtDraftTouched] = useState(false);
  const [propertyDraftTouched, setPropertyDraftTouched] = useState(false);
  const [delDebt, setDelDebt] = useState<DebtEntry | null>(null);
  const [pendingUnlinkDebt, setPendingUnlinkDebt] = useState<DebtEntry | null>(null);
  const [linkingDebtId, setLinkingDebtId] = useState<number | null>(null);
  const [linkAccountId, setLinkAccountId] = useState("");
  const [delProp, setDelProp] = useState<PropertySnapshot | null>(null);
  const [editingDebtId, setEditingDebtId] = useState<number | null>(null);
  const [editDebt, setEditDebt] = useState<DebtDraft | null>(null);
  const [editingPropId, setEditingPropId] = useState<number | null>(null);
  const [editProp, setEditProp] = useState<PropertyDraft | null>(null);

  const localDirty =
    debtDraftTouched || propertyDraftTouched || editingDebtId !== null || editingPropId !== null;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        let dashboardError: string | null = null;
        let accountsError: string | null = null;
        const [d, p, dash, summary, accs] = await Promise.all([
          listDebts(monthId, signal),
          listProperties(monthId, signal),
          getDashboard(monthId, signal).catch((err) => {
            dashboardError = formatApiError(err);
            return null;
          }),
          getMonthSummary(monthId, signal).catch(() => null),
          listAccounts(signal).catch((err) => {
            accountsError = formatApiError(err);
            return [];
          }),
        ]);
        if (signal?.aborted) return;
        setDebts(d);
        setAccounts(accs);
        setLinkedPairs(dash?.summary?.liquid_capital?.linked_pairs ?? (dash ? [] : null));
        setLinkedPairError(dashboardError ?? accountsError);
        setProperties(p);
        setMortgage(dash?.mortgage ?? null);
        setCoveragePct(summary?.coverage?.coverage_pct ?? null);
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
    void linkedPairRefreshKey;
    void load(c.signal);
    return () => c.abort();
  }, [load, linkedPairRefreshKey]);

  const cardDebtTotal = useMemo(
    () =>
      sumMoneyAmounts(
        debts
          .filter((x) => x.debt_type === "credit_card")
          .map((x) => moneyAmount(x.current_balance)),
      ),
    [debts],
  );
  const eligibleAccounts = useMemo(() => accounts.filter(isLinkableAccount), [accounts]);
  const propertyValueTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.estimated_value))),
    [properties],
  );
  const mortgageBalanceTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.mortgage_balance))),
    [properties],
  );
  const paymentTotal = useMemo(
    () => sumMoneyAmounts(properties.map((x) => moneyAmount(x.monthly_payment))),
    [properties],
  );

  function accountNameFor(accountId: number | null): string {
    if (accountId == null) return "Не связан";
    return accounts.find((account) => account.id === accountId)?.name ?? "Счёт не найден";
  }

  function accountOptionLabel(account: Account): string {
    return `${account.name} · ${labelOf(ACCOUNT_TYPE_LABELS, account.account_type)}`;
  }

  function startLinkingDebt(row: DebtEntry) {
    setActionError(null);
    setLinkingDebtId(row.id);
    setLinkAccountId(row.linked_account_id == null ? "" : String(row.linked_account_id));
  }

  function cancelLinkingDebt() {
    setLinkingDebtId(null);
    setLinkAccountId("");
  }

  async function saveDebtLink(row: DebtEntry) {
    const accountId = Number(linkAccountId);
    if (!Number.isInteger(accountId) || accountId < 1) {
      setActionError("Выбери счёт для связи.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await linkDebtToAccount(row.id, accountId);
      cancelLinkingDebt();
      await load();
      onLinkedPairChange?.();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDebtUnlink() {
    if (!pendingUnlinkDebt) return;
    setBusy(true);
    setActionError(null);
    try {
      await unlinkDebtFromAccount(pendingUnlinkDebt.id);
      setPendingUnlinkDebt(null);
      await load();
      onLinkedPairChange?.();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingUnlinkDebt(null);
    } finally {
      setBusy(false);
    }
  }

  async function addDebt(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!debtName.trim() || !normalizeMoneyInput(debtBal)) {
        throw new Error("Имя и баланс долга обязательны");
      }
      if (debtRate.trim() !== "" && normalizeRateInput(debtRate) == null) {
        throw new Error("Ставка — неотрицательное число, пусто — неизвестно");
      }
      await createDebt({
        reporting_month_id: monthId,
        debt_type: debtType,
        name: debtName.trim(),
        current_balance: rub(debtBal),
        include_in_liquid_capital: true,
        annual_rate: normalizeRateInput(debtRate),
        next_due_date: debtDue || null,
        contract_end_date: debtEnd || null,
      });
      setDebtBal("");
      setDebtRate("");
      setDebtDue("");
      setDebtEnd("");
      setDebtDraftTouched(false);
      await load();
      onLinkedPairChange?.();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDebtEdit() {
    if (editingDebtId == null || !editDebt) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (!editDebt.name.trim() || !normalizeMoneyInput(editDebt.current_balance)) {
        throw new Error("Имя и баланс долга обязательны");
      }
      if (editDebt.annual_rate.trim() !== "" && normalizeRateInput(editDebt.annual_rate) == null) {
        throw new Error("Ставка — неотрицательное число, пусто — неизвестно");
      }
      await updateDebt(editingDebtId, {
        name: editDebt.name.trim(),
        debt_type: editDebt.debt_type,
        current_balance: rub(editDebt.current_balance),
        include_in_liquid_capital: editDebt.include_in_liquid_capital,
        annual_rate: normalizeRateInput(editDebt.annual_rate),
        next_due_date: editDebt.next_due_date || null,
        contract_end_date: editDebt.contract_end_date || null,
      });
      setEditingDebtId(null);
      setEditDebt(null);
      await load();
      onLinkedPairChange?.();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePropertyEdit() {
    if (editingPropId == null || !editProp) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      if (
        !editProp.name.trim() ||
        !normalizeMoneyInput(editProp.estimated_value) ||
        !normalizeMoneyInput(editProp.mortgage_balance) ||
        !normalizeMoneyInput(editProp.monthly_payment)
      ) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      if (
        editProp.mortgage_annual_rate.trim() !== "" &&
        normalizeRateInput(editProp.mortgage_annual_rate) == null
      ) {
        throw new Error("Ставка ипотеки — неотрицательное число, пусто — неизвестно");
      }
      await updateProperty(editingPropId, {
        name: editProp.name.trim(),
        estimated_value: rub(editProp.estimated_value),
        mortgage_balance: rub(editProp.mortgage_balance),
        monthly_payment: rub(editProp.monthly_payment),
        mortgage_annual_rate: normalizeRateInput(editProp.mortgage_annual_rate),
      });
      setEditingPropId(null);
      setEditProp(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addProperty(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (
        !propName.trim() ||
        !normalizeMoneyInput(propValue) ||
        !normalizeMoneyInput(propMortgage) ||
        !normalizeMoneyInput(propPayment)
      ) {
        throw new Error("Заполни название, стоимость, остаток ипотеки и платёж");
      }
      if (propRate.trim() !== "" && normalizeRateInput(propRate) == null) {
        throw new Error("Ставка ипотеки — неотрицательное число, пусто — неизвестно");
      }
      await createProperty({
        reporting_month_id: monthId,
        name: propName.trim(),
        estimated_value: rub(propValue),
        mortgage_balance: rub(propMortgage),
        monthly_payment: rub(propPayment),
        mortgage_annual_rate: normalizeRateInput(propRate),
      });
      setPropName("");
      setPropValue("");
      setPropMortgage("");
      setPropPayment("");
      setPropRate("");
      setPropertyDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем долги и недвижимость…" inline />;
  if (error)
    return <ErrorState description={error} inline title="Не удалось загрузить обязательства" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={<Badge>CC {formatMoney(cardDebtTotal)}</Badge>}
        label="Обязательства"
        title="Долги"
      >
        {debts.length === 0 ? (
          <EmptyState description="Долгов нет." inline title="Пусто" />
        ) : (
          <Table className="month-debts-table">
            <thead>
              <tr>
                <Th className="month-debts-table__name">Название</Th>
                <Th className="month-debts-table__type">Тип</Th>
                <Th numeric>Баланс</Th>
                <Th>Ставка</Th>
                <Th>Ближайший платёж</Th>
                <Th>Окончание</Th>
                <Th className="month-debts-table__inclusion">Учёт</Th>
                <Th className="month-debts-table__linked">Связанный счёт</Th>
                <Th className="month-debts-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {debts.map((row) => {
                const editing = editingDebtId === row.id && editDebt;
                const linking = linkingDebtId === row.id;
                const currentLinkedAccount =
                  row.linked_account_id == null
                    ? null
                    : accounts.find((account) => account.id === row.linked_account_id);
                const currentLinkedAccountIsEligible =
                  currentLinkedAccount != null && isLinkableAccount(currentLinkedAccount);
                const selectedAccountIsEligible = eligibleAccounts.some(
                  (account) => account.id === Number(linkAccountId),
                );
                const canSaveLink = eligibleAccounts.length > 0 && selectedAccountIsEligible;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Название долга"
                          onChange={(e) => setEditDebt({ ...editDebt, name: e.target.value })}
                          value={editDebt.name}
                        />
                      ) : (
                        row.name
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          aria-label="Тип долга"
                          onChange={(e) => setEditDebt({ ...editDebt, debt_type: e.target.value })}
                          value={editDebt.debt_type}
                        >
                          <option value="credit_card">Кредитная карта</option>
                          <option value="other">Прочее</option>
                        </Select>
                      ) : (
                        labelOf(DEBT_TYPE_LABELS, row.debt_type)
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Текущий баланс долга"
                          className="input--money"
                          onChange={(e) =>
                            setEditDebt({ ...editDebt, current_balance: e.target.value })
                          }
                          value={editDebt.current_balance}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.current_balance))
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Годовая ставка долга"
                          onChange={(e) =>
                            setEditDebt({ ...editDebt, annual_rate: e.target.value })
                          }
                          placeholder="неизвестно"
                          value={editDebt.annual_rate}
                        />
                      ) : (
                        <span className="muted tiny">
                          {formatPercent(row.annual_rate, { digits: 2, empty: "не указано" })}
                        </span>
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Ближайший обязательный платёж"
                          onChange={(e) =>
                            setEditDebt({ ...editDebt, next_due_date: e.target.value })
                          }
                          type="date"
                          value={editDebt.next_due_date}
                        />
                      ) : (
                        <span className="muted tiny">{formatDate(row.next_due_date)}</span>
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Окончание договора"
                          onChange={(e) =>
                            setEditDebt({ ...editDebt, contract_end_date: e.target.value })
                          }
                          type="date"
                          value={editDebt.contract_end_date}
                        />
                      ) : (
                        <span className="muted tiny">{formatDate(row.contract_end_date)}</span>
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <label className="check-row">
                          <input
                            checked={editDebt.include_in_liquid_capital}
                            onChange={(e) =>
                              setEditDebt({
                                ...editDebt,
                                include_in_liquid_capital: e.target.checked,
                              })
                            }
                            type="checkbox"
                          />
                          В капитале
                        </label>
                      ) : (
                        <Badge tone={row.include_in_liquid_capital ? "ok" : "neutral"}>
                          {row.include_in_liquid_capital ? "В капитале" : "Отдельно"}
                        </Badge>
                      )}
                    </Td>
                    <Td className="month-debts-table__linked">
                      {linking ? (
                        <div className="linked-debt-control">
                          <div className="linked-debt-control__account">
                            <Badge tone={row.linked_account_id == null ? "neutral" : "ok"}>
                              {row.linked_account_id == null ? "Не связано" : "Связано"}
                            </Badge>
                            {row.linked_account_id != null ? (
                              <strong>{accountNameFor(row.linked_account_id)}</strong>
                            ) : null}
                          </div>
                          <Select
                            aria-label={`Счёт для связи с долгом «${row.name}»`}
                            disabled={busy || readOnly || eligibleAccounts.length === 0}
                            onChange={(event) => setLinkAccountId(event.target.value)}
                            value={linkAccountId}
                          >
                            <option value="">Выбери счёт</option>
                            {row.linked_account_id != null && !currentLinkedAccountIsEligible ? (
                              <option disabled value={row.linked_account_id}>
                                {currentLinkedAccount
                                  ? `${accountOptionLabel(currentLinkedAccount)} · текущая связь недоступна для новой связи`
                                  : "Текущий связанный счёт · недоступен для новой связи"}
                              </option>
                            ) : null}
                            {eligibleAccounts.map((account) => (
                              <option key={account.id} value={account.id}>
                                {accountOptionLabel(account)}
                              </option>
                            ))}
                          </Select>
                          {eligibleAccounts.length === 0 ? (
                            <span className="linked-debt-control__hint">
                              {LINK_ACCOUNT_EMPTY_HINT}
                            </span>
                          ) : null}
                          {row.linked_account_id != null && !currentLinkedAccountIsEligible ? (
                            <span className="linked-debt-control__hint">
                              {LINK_ACCOUNT_STALE_HINT}
                            </span>
                          ) : null}
                          <div className="linked-debt-control__actions">
                            <Button
                              disabled={busy || readOnly || !canSaveLink}
                              onClick={() => void saveDebtLink(row)}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              Сохранить связь
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={cancelLinkingDebt}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </div>
                        </div>
                      ) : row.linked_account_id != null ? (
                        <div className="linked-debt-control">
                          <div className="linked-debt-control__account">
                            <Badge tone="ok">Связано</Badge>
                            <strong>{accountNameFor(row.linked_account_id)}</strong>
                          </div>
                          <div className="linked-debt-control__actions">
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => startLinkingDebt(row)}
                              size="sm"
                              type="button"
                            >
                              Изменить связь
                            </Button>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => setPendingUnlinkDebt(row)}
                              size="sm"
                              type="button"
                            >
                              Отвязать
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="linked-debt-control">
                          <Badge tone="neutral">Не связано</Badge>
                          {row.debt_type === "credit_card" && row.include_in_liquid_capital ? (
                            <>
                              <Button
                                disabled={busy || readOnly || eligibleAccounts.length === 0}
                                onClick={() => startLinkingDebt(row)}
                                size="sm"
                                type="button"
                              >
                                Связать счёт
                              </Button>
                              {eligibleAccounts.length === 0 ? (
                                <span className="linked-debt-control__hint">
                                  {LINK_ACCOUNT_EMPTY_HINT}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <span className="linked-debt-control__hint">
                              Связь доступна для кредитки, включённой в ликвидный капитал.
                            </span>
                          )}
                        </div>
                      )}
                    </Td>
                    <Td className="month-debts-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveDebtEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingDebtId(null);
                                setEditDebt(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для долга «${row.name}»`}>
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingDebtId(row.id);
                                setEditDebt({
                                  name: row.name,
                                  debt_type: row.debt_type,
                                  current_balance: moneyAmount(row.current_balance),
                                  include_in_liquid_capital: row.include_in_liquid_capital,
                                  annual_rate: row.annual_rate ?? "",
                                  next_due_date: row.next_due_date ?? "",
                                  contract_end_date: row.contract_end_date ?? "",
                                });
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelDebt(row)}
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
            Долг по кредитным картам: <strong>{formatMoney(cardDebtTotal)}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addDebt}>
            <div className="editor-grid">
              <Field htmlFor="debt-name" label="Название долга">
                <Input
                  id="debt-name"
                  onChange={(e) => {
                    setDebtName(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  required
                  value={debtName}
                />
              </Field>
              <Field htmlFor="debt-type" label="Тип долга">
                <Select
                  id="debt-type"
                  onChange={(e) => {
                    setDebtType(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  value={debtType}
                >
                  <option value="credit_card">Кредитная карта</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="debt-bal" label="Текущий баланс долга">
                <Input
                  className="input--money"
                  id="debt-bal"
                  onChange={(e) => {
                    setDebtBal(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  required
                  value={debtBal}
                />
              </Field>
              <Field htmlFor="debt-rate" label="Годовая ставка, % (пусто — неизвестно)">
                <Input
                  id="debt-rate"
                  onChange={(e) => {
                    setDebtRate(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  placeholder="неизвестно"
                  value={debtRate}
                />
              </Field>
              <Field htmlFor="debt-due" label="Ближайший платёж">
                <Input
                  id="debt-due"
                  onChange={(e) => {
                    setDebtDue(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  type="date"
                  value={debtDue}
                />
              </Field>
              <Field htmlFor="debt-end" label="Окончание договора">
                <Input
                  id="debt-end"
                  onChange={(e) => {
                    setDebtEnd(e.target.value);
                    setDebtDraftTouched(true);
                  }}
                  type="date"
                  value={debtEnd}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить долг
            </Button>
          </form>
        ) : null}
      </Panel>

      <LinkedPairContext
        accounts={accounts}
        debts={debts}
        error={linkedPairError}
        label="Связи"
        pairs={linkedPairs}
        title="Контекст связанных пар"
      />

      <Panel
        action={<Badge>RE {formatMoney(propertyValueTotal)}</Badge>}
        label="Обязательства"
        title="Недвижимость"
      >
        <details className="field-details">
          <summary>О недвижимости и покрытии</summary>
          <p>
            Недвижимость не входит в ликвидный капитал. Покрытие ипотеки показывается как ориентир
            из сводки месяца.
          </p>
        </details>
        {properties.length === 0 ? (
          <EmptyState description="Объектов нет." inline title="Пусто" />
        ) : (
          <Table className="month-property-table">
            <thead>
              <tr>
                <Th className="month-property-table__name">Объект</Th>
                <Th numeric>Стоимость</Th>
                <Th numeric>Ипотека</Th>
                <Th numeric>Платёж / мес</Th>
                <Th>Ставка</Th>
                <Th className="month-property-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {properties.map((row) => {
                const editing = editingPropId === row.id && editProp;
                return (
                  <tr key={row.id}>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Название объекта"
                          onChange={(e) => setEditProp({ ...editProp, name: e.target.value })}
                          value={editProp.name}
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
                          onChange={(e) =>
                            setEditProp({ ...editProp, estimated_value: e.target.value })
                          }
                          value={editProp.estimated_value}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.estimated_value))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Остаток ипотеки"
                          className="input--money"
                          onChange={(e) =>
                            setEditProp({ ...editProp, mortgage_balance: e.target.value })
                          }
                          value={editProp.mortgage_balance}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.mortgage_balance))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Ежемесячный платёж"
                          className="input--money"
                          onChange={(e) =>
                            setEditProp({ ...editProp, monthly_payment: e.target.value })
                          }
                          value={editProp.monthly_payment}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.monthly_payment))
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Input
                          aria-label="Годовая ставка ипотеки"
                          onChange={(e) =>
                            setEditProp({ ...editProp, mortgage_annual_rate: e.target.value })
                          }
                          placeholder="неизвестно"
                          value={editProp.mortgage_annual_rate}
                        />
                      ) : (
                        <span className="muted tiny">
                          {formatPercent(row.mortgage_annual_rate, {
                            digits: 2,
                            empty: "не указано",
                          })}
                        </span>
                      )}
                    </Td>
                    <Td className="month-property-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSavePropertyEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingPropId(null);
                                setEditProp(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : (
                          <OverflowMenu label={`Действия для объекта «${row.name}»`}>
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingPropId(row.id);
                                setEditProp({
                                  name: row.name,
                                  estimated_value: moneyAmount(row.estimated_value),
                                  mortgage_balance: moneyAmount(row.mortgage_balance),
                                  monthly_payment: moneyAmount(row.monthly_payment),
                                  mortgage_annual_rate: row.mortgage_annual_rate ?? "",
                                });
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setDelProp(row)}
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
            Стоимость: <strong>{formatMoney(propertyValueTotal)}</strong>
          </span>
          <span>
            Остаток ипотеки: <strong>{formatMoney(mortgageBalanceTotal)}</strong>
          </span>
          <span>
            Платёж: <strong>{formatMoney(paymentTotal)}</strong>
          </span>
        </div>
        <div className="totals-bar">
          <span>
            Покрытие ипотеки (ориентир):{" "}
            <strong>{mortgage?.coverage_pct != null ? `${mortgage.coverage_pct}%` : "—"}</strong>
          </span>
          <span>
            Недостаток покрытия:{" "}
            <strong>{mortgage ? formatMoney(moneyAmount(mortgage.gap)) : "—"}</strong>
          </span>
          <span>
            Покрытие обязательных расходов:{" "}
            <strong>{coveragePct != null ? `${coveragePct}%` : "—"}</strong>
          </span>
        </div>
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addProperty}>
            <div className="editor-grid">
              <Field htmlFor="prop-name" label="Название объекта">
                <Input
                  id="prop-name"
                  onChange={(e) => {
                    setPropName(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propName}
                />
              </Field>
              <Field htmlFor="prop-val" label="Стоимость">
                <Input
                  className="input--money"
                  id="prop-val"
                  onChange={(e) => {
                    setPropValue(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propValue}
                />
              </Field>
              <Field htmlFor="prop-mort" label="Остаток ипотеки">
                <Input
                  className="input--money"
                  id="prop-mort"
                  onChange={(e) => {
                    setPropMortgage(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propMortgage}
                />
              </Field>
              <Field htmlFor="prop-pay" label="Ежемесячный платёж">
                <Input
                  className="input--money"
                  id="prop-pay"
                  onChange={(e) => {
                    setPropPayment(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  required
                  value={propPayment}
                />
              </Field>
              <Field htmlFor="prop-rate" label="Годовая ставка, % (пусто — неизвестно)">
                <Input
                  id="prop-rate"
                  onChange={(e) => {
                    setPropRate(e.target.value);
                    setPropertyDraftTouched(true);
                  }}
                  placeholder="неизвестно"
                  value={propRate}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить объект
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Отвязать"
        description={
          pendingUnlinkDebt
            ? `Отвязать долг «${pendingUnlinkDebt.name}» от счёта «${accountNameFor(pendingUnlinkDebt.linked_account_id)}»?`
            : ""
        }
        onCancel={() => setPendingUnlinkDebt(null)}
        onConfirm={() => void confirmDebtUnlink()}
        open={pendingUnlinkDebt !== null}
        title="Отвязать счёт?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delDebt ? `Удалить долг «${delDebt.name}»?` : ""}
        onCancel={() => setDelDebt(null)}
        onConfirm={() => {
          if (!delDebt) return;
          setBusy(true);
          void deleteDebt(delDebt.id)
            .then(async () => {
              await load();
              onLinkedPairChange?.();
            })
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelDebt(null);
            });
        }}
        open={delDebt !== null}
        title="Удалить долг?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delProp ? `Удалить «${delProp.name}»?` : ""}
        onCancel={() => setDelProp(null)}
        onConfirm={() => {
          if (!delProp) return;
          setBusy(true);
          void deleteProperty(delProp.id)
            .then(() => load())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelProp(null);
            });
        }}
        open={delProp !== null}
        title="Удалить объект?"
      />
    </div>
  );
}
