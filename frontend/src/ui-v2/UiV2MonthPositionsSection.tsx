import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router";

import { createAccount, listAccounts } from "../api/accounts";
import { ApiClientError, formatApiError } from "../api/client";
import {
  deleteInstrumentMapping,
  deleteInstrumentMappingExclusion,
  discoverInstrumentMapping,
  getInstrumentMapping,
  putInstrumentMapping,
  putInstrumentMappingExclusion,
} from "../api/instrumentMappings";
import { createInstrument, listInstruments } from "../api/instruments";
import { getMonth } from "../api/months";
import { createPosition, deletePosition, listPositions, updatePosition } from "../api/positions";
import { applyMonthQuotes, previewMonthQuotes } from "../api/quotePreview";
import type {
  Account,
  Instrument,
  InstrumentMarketMapping,
  MarketDiscoverResult,
  MarketIdentityWrite,
  MoneyValue,
  PositionSnapshot,
  QuoteApplyResult,
  QuoteApplyRowRequest,
  QuotePreview,
  QuotePreviewRow,
} from "../api/types";
import { formatDate, formatMoney, formatPercent, formatQuantity } from "../lib/format";
import {
  ACCOUNT_TYPE_LABELS,
  INSTRUMENT_TYPE_LABELS,
  labelOf,
  PRICE_SOURCE_LABELS,
} from "../lib/labels";
import {
  moneyAmount,
  moneySharePercent,
  normalizeMoneyInput,
  rub,
  sumMoneyAmounts,
  toKopecks,
} from "../lib/money";
import {
  InstrumentMappingDialog,
  type InstrumentMappingSubject,
} from "../components/InstrumentMappingDialog";
import { QuotePreviewPanel } from "../components/QuotePreviewPanel";
import {
  Button,
  ConfirmDialog,
  EmptyState,
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
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import styles from "./UiV2MonthPositionsSection.module.css";
import { shortInstrumentName } from "./instrumentName";
import { MonthMoneyInput } from "./MonthMoneyInput";
import { MonthSaveBar } from "./MonthSaveBar";
import { MonthPanelTotal } from "./MonthPanelTotal";
import { moneyWholeText, moneyWholeDeltaText, moneyTone } from "./valueFormat";
import { validIsin } from "./returns/navigation";

export function UiV2MonthPositionsSection({ context }: { context: MonthEditorContext }) {
  return <PositionsLeaf key={context.month.id} context={context} />;
}

type PositionDraft = {
  account_id: string;
  instrument_id: string;
  quantity: string;
  average_cost: string;
  market_price: string;
  accrued_interest: string;
  price_source: string;
  price_date: string;
};

function emptyDraft(priceDate: string): PositionDraft {
  return {
    account_id: "",
    instrument_id: "",
    quantity: "",
    average_cost: "",
    market_price: "",
    accrued_interest: "",
    price_source: "manual",
    price_date: priceDate,
  };
}

function normalizeQuantity(value: string, instrumentType?: string): string | null {
  const cleaned = value.trim().replace(",", ".").replace(/\s/g, "");
  if (!cleaned) {
    return null;
  }
  const pattern = instrumentType === "stock" ? /^\d+$/ : /^\d+(\.\d{1,6})?$/;
  if (!pattern.test(cleaned) || /^0+(\.0+)?$/.test(cleaned)) {
    return null;
  }
  return cleaned;
}

function quantityError(instrumentType?: string): string {
  return instrumentType === "stock"
    ? "Количество акций должно быть целым числом не меньше 1"
    : "Количество должно быть больше нуля и содержать не более 6 знаков после запятой";
}

function instrumentLabel(instrument: Instrument): string {
  const ticker = instrument.ticker ? ` (${instrument.ticker})` : "";
  return `${instrument.name}${ticker} · ${labelOf(INSTRUMENT_TYPE_LABELS, instrument.instrument_type)} · ${instrument.currency}`;
}

function safeTotal(
  rows: PositionSnapshot[],
  field: "market_value" | "cost_basis" | "unrealized_result",
) {
  if (
    rows.some(
      (row) =>
        row[field]?.currency !== "RUB" || normalizeMoneyInput(row[field]?.amount ?? "") == null,
    )
  )
    return null;
  return sumMoneyAmounts(rows.map((row) => row[field]?.amount ?? ""));
}

function valueKopecks(value: MoneyValue | null | undefined): bigint | null {
  return value?.currency === "RUB" && normalizeMoneyInput(value.amount) !== null
    ? toKopecks(value.amount)
    : null;
}

function descendingValue(a: MoneyValue | null, b: MoneyValue | null): number {
  const left = valueKopecks(a);
  const right = valueKopecks(b);
  if (left === right) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return left > right ? -1 : 1;
}

function displayShare(value: MoneyValue | null, total: string | null): string {
  const part = valueKopecks(value);
  if (value === null || part === null || part < 0n || total === null || toKopecks(total) <= 0n)
    return "";
  return formatPercent(moneySharePercent(value.amount, total), { digits: 1 });
}

function fromStatement(row: PositionSnapshot): boolean {
  return row.price_source === "broker_statement_native";
}

function displayCell(value: MoneyValue | null, hasValues = true): string {
  return value == null ? (hasValues ? "—" : "") : moneyWholeText({ ...value, currency: "" }).trim();
}

function editDraftFromPosition(row: PositionSnapshot): PositionDraft {
  return {
    account_id: String(row.account_id),
    instrument_id: String(row.instrument_id),
    quantity: formatQuantity(row.quantity),
    average_cost: moneyAmount(row.average_cost_per_unit),
    market_price: moneyAmount(row.market_price_per_unit),
    accrued_interest: moneyAmount(row.accrued_interest),
    price_source: row.price_source === "t_invest" ? "manual" : row.price_source,
    price_date: row.price_date,
  };
}

function PositionsLeaf({ context }: { context: MonthEditorContext }) {
  const location = useLocation();
  const { month, readOnly, refresh, setDirty } = context;
  const monthId = month.id;
  const defaultPriceDate = month.snapshot_date;
  const active = useRef(true);
  const readOnlyNow = useRef(readOnly);
  readOnlyNow.current = readOnly;
  const pending = useRef(false);
  const quoteBusy = useRef(false);
  const sequence = useRef(0);
  const request = useRef<AbortController | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (loading || location.hash !== "#month-quotes") return;
    const quotes = document.getElementById("month-quotes");
    quotes?.scrollIntoView?.({ block: "start" });
    quotes?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
  }, [loading, location.hash]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [filterAccountId, setFilterAccountId] = useState("");
  const [filterType, setFilterType] = useState("");
  const [draft, setDraft] = useState<PositionDraft>(() => emptyDraft(defaultPriceDate));
  const [newInstrumentName, setNewInstrumentName] = useState("");
  const [newInstrumentType, setNewInstrumentType] = useState("stock");
  const [newInstrumentTicker, setNewInstrumentTicker] = useState("");
  const [draftTouched, setDraftTouched] = useState(false);
  const [newInstrumentTouched, setNewInstrumentTouched] = useState(false);

  const [adding, setAdding] = useState(false);
  const [creatingInstrument, setCreatingInstrument] = useState(false);
  const [quotesOpen, setQuotesOpen] = useState(location.hash === "#month-quotes");
  const [priceOnly, setPriceOnly] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<PositionDraft | null>(null);
  useEffect(() => {
    if (editingId !== null && !priceOnly)
      document.querySelector<HTMLInputElement>(".position-inline-edit input")?.focus();
  }, [editingId, priceOnly]);
  const [pendingDelete, setPendingDelete] = useState<PositionSnapshot | null>(null);
  const [quotePreview, setQuotePreview] = useState<QuotePreview | null>(null);
  const [quoteApplyResult, setQuoteApplyResult] = useState<QuoteApplyResult | null>(null);
  const [previewApplying, setPreviewApplying] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [mappingRow, setMappingRow] = useState<QuotePreviewRow | null>(null);
  const [mappingInstrument, setMappingInstrument] = useState<InstrumentMappingSubject | null>(null);
  const [mappingView, setMappingView] = useState<InstrumentMarketMapping | null>(null);
  const [mappingLoading, setMappingLoading] = useState(false);
  const [mappingBusy, setMappingBusy] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [mappingNotice, setMappingNotice] = useState<string | null>(null);

  const localDirty = draftTouched || newInstrumentTouched || editingId !== null;

  useEffect(() => {
    context.setPending?.("positions", busy || previewApplying || mappingBusy);
    return () => context.setPending?.("positions", false);
  }, [context.setPending, busy, previewApplying, mappingBusy]);
  useEffect(() => setDirty("positions", localDirty), [localDirty, setDirty]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      sequence.current += 1;
      request.current?.abort();
      setDirty("positions", false);
    };
  }, [setDirty]);
  useEffect(() => {
    if (!draftTouched) setDraft((current) => ({ ...current, price_date: defaultPriceDate }));
  }, [defaultPriceDate, draftTouched]);
  useEffect(() => {
    sequence.current += 1;
    request.current?.abort();
    request.current = null;
    quoteBusy.current = false;
    setPreviewLoading(false);
    setPreviewApplying(false);
    setQuotePreview(null);
    setMappingRow(null);
    setMappingInstrument(null);
    setMappingView(null);
    setMappingError(null);
    setMappingNotice(null);
    if (readOnly || month.status === "closed") {
      setPendingDelete(null);
      setEditingId(null);
      setEditDraft(null);
    }
  }, [readOnly, month.status]);

  async function assertDraft() {
    if (!active.current || readOnlyNow.current) throw new Error("Месяц закрыт для изменений.");
    const current = await getMonth(monthId);
    if (
      !active.current ||
      readOnlyNow.current ||
      current.id !== monthId ||
      current.status !== "draft"
    ) {
      throw new Error("Месяц изменился или закрыт. Перечитай данные перед сохранением.");
    }
  }

  async function confirmMonth() {
    const current = await refresh();
    if (!active.current || current.id !== monthId)
      throw new Error("Ответ относится к другому месяцу.");
    return current;
  }

  function beginWrite(): boolean {
    if (pending.current || quoteBusy.current || readOnlyNow.current || !active.current)
      return false;
    pending.current = true;
    setBusy(true);
    setActionError(null);
    setQuotePreview(null);
    setQuoteApplyResult(null);
    return true;
  }

  function endWrite() {
    pending.current = false;
    if (active.current) setBusy(false);
  }

  const load = useCallback(
    async (signal?: AbortSignal): Promise<PositionSnapshot[]> => {
      setLoading(true);
      setError(null);
      try {
        const [accs, instrs, rows] = await Promise.all([
          listAccounts(signal),
          listInstruments({ active: true }, signal),
          listPositions(monthId, undefined, signal),
        ]);
        if (signal?.aborted || !active.current) return [];
        if (rows.some((row) => row.reporting_month_id !== monthId))
          throw new Error("Список позиций относится к другому месяцу.");
        setAccounts(accs);
        setInstruments(instrs);
        setPositions(rows);

        const brokerAccounts = accs.filter(
          (a) =>
            a.status === "active" &&
            (a.account_type === "brokerage" ||
              a.account_type === "iis" ||
              a.account_type === "other"),
        );
        setDraft((prev) => {
          let next = prev;
          if (!prev.account_id && brokerAccounts[0]) {
            next = { ...next, account_id: String(brokerAccounts[0].id) };
          }
          if (!prev.instrument_id && instrs[0]) {
            next = { ...next, instrument_id: String(instrs[0].id) };
          }
          if (!prev.price_date) {
            next = { ...next, price_date: defaultPriceDate };
          }
          return next;
        });
        return rows;
      } catch (err) {
        if (!signal?.aborted && active.current) {
          setError(formatApiError(err));
        }
        throw err;
      } finally {
        if (!signal?.aborted && active.current) {
          setLoading(false);
        }
      }
    },
    [defaultPriceDate, monthId],
  );

  useEffect(() => {
    setQuotePreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
    const controller = new AbortController();
    void load(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [load]);

  const brokerAccounts = useMemo(
    () =>
      accounts.filter(
        (a) =>
          a.status === "active" &&
          (a.account_type === "brokerage" ||
            a.account_type === "iis" ||
            a.account_type === "other"),
      ),
    [accounts],
  );

  const instrumentById = useMemo(() => {
    const map = new Map<number, Instrument>();
    for (const item of instruments) {
      map.set(item.id, item);
    }
    return map;
  }, [instruments]);

  const accountById = useMemo(() => {
    const map = new Map<number, Account>();
    for (const item of accounts) {
      map.set(item.id, item);
    }
    return map;
  }, [accounts]);

  const filteredPositions = useMemo(() => {
    return positions.filter((row) => {
      if (filterAccountId && String(row.account_id) !== filterAccountId) {
        return false;
      }
      if (filterType) {
        const instrument = instrumentById.get(row.instrument_id);
        if (!instrument || instrument.instrument_type !== filterType) {
          return false;
        }
      }
      return true;
    });
  }, [filterAccountId, filterType, instrumentById, positions]);

  const totals = useMemo(() => {
    return {
      market: safeTotal(filteredPositions, "market_value"),
      cost: safeTotal(filteredPositions, "cost_basis"),
      result: safeTotal(filteredPositions, "unrealized_result"),
    };
  }, [filteredPositions]);

  const positionAccounts = accounts.filter((a) => positions.some((row) => row.account_id === a.id));
  const positionTypes = [
    ...new Set(positions.map((row) => instrumentById.get(row.instrument_id)?.instrument_type)),
  ].filter((type): type is string => type !== undefined);
  const hasMarket = filteredPositions.some((row) => row.market_value != null);
  const showActions =
    !readOnly &&
    month.status !== "closed" &&
    filteredPositions.some((row) => row.price_source !== "broker_statement_native");
  const showCurrency =
    new Set(positions.map((row) => instrumentById.get(row.instrument_id)?.currency)).size > 1;
  const groups = [...new Set(filteredPositions.map((row) => row.account_id))]
    .map((accountId) => {
      const rows = filteredPositions
        .filter((row) => row.account_id === accountId)
        .sort((a, b) => descendingValue(a.market_value, b.market_value) || a.id - b.id);
      return { accountId, rows, total: safeTotal(rows, "market_value") };
    })
    .sort(
      (a, b) =>
        descendingValue(
          a.total === null ? null : rub(a.total),
          b.total === null ? null : rub(b.total),
        ) || a.accountId - b.accountId,
    );
  const statementExplanation = filteredPositions.some(
    (row) => row.price_source === "broker_statement_native" && row.average_cost_per_unit === null,
  );
  const back = `${location.pathname}${location.search}${location.hash}`;

  async function ensureBrokerAccount(): Promise<number> {
    if (brokerAccounts[0]) {
      return brokerAccounts[0].id;
    }
    const created = await createAccount({
      name: "Брокерский",
      account_type: "brokerage",
      status: "active",
      include_in_capital: true,
      include_in_returns: true,
    });
    setAccounts((prev) => [...prev, created]);
    return created.id;
  }

  async function handleCreateInstrument(event: FormEvent) {
    event.preventDefault();
    if (!beginWrite()) return;
    try {
      await assertDraft();
      if (!newInstrumentName.trim()) {
        throw new Error("Укажи название инструмента");
      }
      const created = await createInstrument({
        name: newInstrumentName.trim(),
        instrument_type: newInstrumentType,
        ticker: newInstrumentTicker.trim() || null,
        currency: "RUB",
        is_active: true,
        manual_price_allowed: true,
      });
      if (!active.current || readOnlyNow.current) return;
      const catalog = await listInstruments({ active: true });
      if (!catalog.some((item) => item.id === created.id))
        throw new Error("Инструмент не подтверждён повторной загрузкой.");
      if (!active.current || readOnlyNow.current) return;
      setInstruments(catalog);
      setDraft((prev) => ({ ...prev, instrument_id: String(created.id) }));
      setDraftTouched(true);
      setNewInstrumentName("");
      setNewInstrumentTicker("");
      setNewInstrumentTouched(false);
    } catch (err) {
      if (active.current) setActionError(formatApiError(err));
    } finally {
      endWrite();
    }
  }

  async function handleCreatePosition(event: FormEvent) {
    event.preventDefault();
    if (!beginWrite()) return;
    try {
      await assertDraft();
      if (!normalizeMoneyInput(draft.average_cost) || !normalizeMoneyInput(draft.market_price)) {
        throw new Error("Укажи среднюю стоимость и рыночную цену");
      }
      let accountId = Number(draft.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) {
        accountId = await ensureBrokerAccount();
      }
      await assertDraft();
      const instrumentId = Number(draft.instrument_id);
      if (!Number.isInteger(instrumentId) || instrumentId < 1) {
        throw new Error("Выбери или создай инструмент");
      }
      const instrumentType = instrumentById.get(instrumentId)?.instrument_type;
      const qty = normalizeQuantity(draft.quantity, instrumentType);
      if (!qty) {
        throw new Error(quantityError(instrumentType));
      }
      const payload = {
        reporting_month_id: monthId,
        account_id: accountId,
        instrument_id: instrumentId,
        quantity: qty,
        average_cost_per_unit: rub(draft.average_cost),
        market_price_per_unit: rub(draft.market_price),
        price_source: draft.price_source || "manual",
        price_date: draft.price_date || defaultPriceDate,
        ...(draft.accrued_interest.trim() === ""
          ? {}
          : { accrued_interest: rub(draft.accrued_interest) }),
      };
      const created = await createPosition(payload);
      if (created.reporting_month_id !== monthId)
        throw new Error("Ответ относится к другому месяцу.");
      const fresh = await load();
      if (!fresh.some((row) => row.id === created.id && row.reporting_month_id === monthId))
        throw new Error("Позиция не подтверждена повторной загрузкой.");
      await confirmMonth();
      if (!active.current || readOnlyNow.current) return;
      setDraft(() => ({
        ...emptyDraft(defaultPriceDate),
        account_id: String(accountId),
        instrument_id: String(instrumentId),
      }));
      setDraftTouched(false);
    } catch (err) {
      if (active.current) setActionError(formatApiError(err));
    } finally {
      endWrite();
    }
  }

  async function handleSaveEdit() {
    if (editingId == null || !editDraft || !beginWrite()) {
      return;
    }
    const current = positions.find((p) => p.id === editingId);
    if (!current) {
      endWrite();
      return;
    }
    try {
      await assertDraft();
      const instrumentType = instrumentById.get(current.instrument_id)?.instrument_type;
      const qty = normalizeQuantity(editDraft.quantity, instrumentType);
      if (!qty) {
        throw new Error(quantityError(instrumentType));
      }
      const nextPrice = rub(editDraft.market_price);
      const quoteChanged =
        nextPrice.amount !== moneyAmount(current.market_price_per_unit) ||
        editDraft.price_date !== current.price_date;
      const nextSource =
        current.price_source === "t_invest" && quoteChanged && editDraft.price_source === "t_invest"
          ? "manual"
          : editDraft.price_source;
      const updated = await updatePosition(
        editingId,
        {
          quantity: qty,
          average_cost_per_unit: rub(editDraft.average_cost),
          accrued_interest:
            editDraft.accrued_interest.trim() === "" ? null : rub(editDraft.accrued_interest),
          ...(quoteChanged
            ? {
                market_price_per_unit: nextPrice,
                price_date: editDraft.price_date,
                price_source: nextSource === "t_invest" ? "manual" : nextSource,
              }
            : {}),
        },
        current.updated_at,
      );
      if (updated.id !== editingId || updated.reporting_month_id !== monthId)
        throw new Error("Ответ относится к другой позиции или месяцу.");
      const fresh = await load();
      const confirmed = fresh.find((row) => row.id === editingId);
      if (!confirmed || confirmed.updated_at !== updated.updated_at)
        throw new Error("Изменение позиции не подтверждено повторной загрузкой.");
      await confirmMonth();
      if (!active.current || readOnlyNow.current) return;
      setEditingId(null);
      setEditDraft(null);
    } catch (err) {
      if (active.current) setActionError(formatApiError(err));
    } finally {
      endWrite();
    }
  }

  function rememberMapping(view: InstrumentMarketMapping) {
    setMappingView(view);
  }

  function invalidatePreviewAfterMapping(firstLine: string) {
    setQuotePreview(null);
    setQuoteApplyResult(null);
    setPreviewError(null);
    setMappingNotice(
      `${firstLine} Предпросмотр сброшен: котировки не применяются автоматически. Запроси новый предпросмотр кнопкой «Обновить котировки».`,
    );
  }

  async function openQuoteMapping(row: QuotePreviewRow) {
    if (
      mappingLoading ||
      quoteBusy.current ||
      pending.current ||
      readOnlyNow.current ||
      !active.current
    )
      return;
    setMappingLoading(true);
    setMappingError(null);
    setActionError(null);
    try {
      const view = await getInstrumentMapping(row.instrument_id);
      if (!active.current || readOnlyNow.current) return;
      setMappingInstrument({
        id: row.instrument_id,
        name: row.instrument_name,
        instrument_type: row.instrument_type,
      });
      setMappingView(view);
      setMappingRow(row);
    } catch (err) {
      if (active.current) setActionError(formatApiError(err));
    } finally {
      if (active.current) setMappingLoading(false);
    }
  }

  async function handleMappingSave(payload: MarketIdentityWrite) {
    if (!mappingInstrument) return;
    setMappingBusy(true);
    setMappingError(null);
    try {
      const view = await putInstrumentMapping(mappingInstrument.id, payload);
      if (!active.current) return;
      rememberMapping(view);
      invalidatePreviewAfterMapping("Сопоставление сохранено.");
    } catch (err) {
      setMappingError(formatApiError(err));
    } finally {
      if (active.current) setMappingBusy(false);
    }
  }

  async function handleMappingClear() {
    if (!mappingInstrument) return;
    setMappingBusy(true);
    setMappingError(null);
    try {
      const view = await deleteInstrumentMapping(mappingInstrument.id);
      if (!active.current) return;
      rememberMapping(view);
      invalidatePreviewAfterMapping("Сопоставление удалено.");
    } catch (err) {
      setMappingError(formatApiError(err));
    } finally {
      if (active.current) setMappingBusy(false);
    }
  }

  async function handleMappingExclude() {
    if (!mappingInstrument) return;
    setMappingBusy(true);
    setMappingError(null);
    try {
      const view = await putInstrumentMappingExclusion(mappingInstrument.id);
      if (!active.current) return;
      rememberMapping(view);
      invalidatePreviewAfterMapping("Обновление котировок для инструмента отключено.");
    } catch (err) {
      setMappingError(formatApiError(err));
    } finally {
      if (active.current) setMappingBusy(false);
    }
  }

  async function handleMappingClearExclusion() {
    if (!mappingInstrument) return;
    setMappingBusy(true);
    setMappingError(null);
    try {
      const view = await deleteInstrumentMappingExclusion(mappingInstrument.id);
      if (!active.current) return;
      rememberMapping(view);
      invalidatePreviewAfterMapping("Обновление котировок для инструмента включено.");
    } catch (err) {
      setMappingError(formatApiError(err));
    } finally {
      if (active.current) setMappingBusy(false);
    }
  }

  async function handleMappingDiscover(query?: string | null): Promise<MarketDiscoverResult> {
    if (!mappingInstrument) throw new Error("Инструмент не выбран.");
    try {
      const normalizedQuery = query?.trim();
      return await discoverInstrumentMapping(mappingInstrument.id, {
        provider: "t_invest",
        ...(normalizedQuery ? { query: normalizedQuery } : {}),
      });
    } catch (err) {
      throw new Error(formatApiError(err));
    }
  }

  async function handleQuotePreview() {
    if (quoteBusy.current || pending.current || !active.current) return;
    quoteBusy.current = true;
    const token = ++sequence.current;
    const controller = new AbortController();
    request.current = controller;
    setPreviewLoading(true);
    setPreviewError(null);
    setQuotePreview(null);
    setQuoteApplyResult(null);
    setMappingNotice(null);
    try {
      const preview = await previewMonthQuotes(monthId, controller.signal);
      if (!active.current || sequence.current !== token) return;
      if (preview.reporting_month_id !== monthId)
        throw new Error("Предпросмотр относится к другому месяцу.");
      setQuotePreview(preview);
    } catch (err) {
      if (active.current && sequence.current === token) setPreviewError(formatApiError(err));
    } finally {
      if (request.current === controller) {
        quoteBusy.current = false;
        request.current = null;
        if (active.current && sequence.current === token) setPreviewLoading(false);
      }
    }
  }

  async function handleQuoteApply(rows: QuoteApplyRowRequest[]) {
    if (
      quoteBusy.current ||
      pending.current ||
      readOnlyNow.current ||
      !quotePreview ||
      rows.length === 0
    )
      return;
    quoteBusy.current = true;
    const token = ++sequence.current;
    const controller = new AbortController();
    request.current = controller;
    setPreviewApplying(true);
    setPreviewError(null);
    setQuoteApplyResult(null);
    try {
      await assertDraft();
      if (sequence.current !== token) return;
      const previewId = quotePreview.preview_id;
      setQuotePreview(null);
      const result = await applyMonthQuotes(monthId, rows, controller.signal, previewId);
      if (!active.current || sequence.current !== token) return;
      if (result.reporting_month_id !== monthId)
        throw new Error("Ответ применения относится к другому месяцу.");
      setQuotePreview(null);
      const fresh = await load();
      if (
        result.rows.some((applied) => {
          const position = fresh.find((row) => row.id === applied.position_snapshot_id);
          return (
            !position ||
            position.price_date !== applied.price_date ||
            position.market_price_per_unit?.amount !== applied.market_price_per_unit.amount ||
            position.price_source !== applied.price_source
          );
        })
      )
        throw new Error("Применённые котировки не подтверждены повторной загрузкой.");
      await confirmMonth();
      if (active.current && sequence.current === token && !readOnlyNow.current)
        setQuoteApplyResult(result);
    } catch (err) {
      if (!active.current || sequence.current !== token) return;
      setQuotePreview(null);
      setPreviewError(
        err instanceof ApiClientError && err.status >= 400 && err.status < 500 && err.status !== 408
          ? formatApiError(err)
          : "Результат применения не подтверждён. Обнови позиции и проверь сохранённые цены перед новым предпросмотром.",
      );
    } finally {
      if (request.current === controller) {
        quoteBusy.current = false;
        request.current = null;
        if (active.current && sequence.current === token) setPreviewApplying(false);
      }
    }
  }

  async function handleDelete() {
    if (!pendingDelete || !beginWrite()) {
      return;
    }
    try {
      await assertDraft();
      await deletePosition(pendingDelete.id);
      const fresh = await load();
      if (fresh.some((row) => row.id === pendingDelete.id))
        throw new Error("Удаление не подтверждено повторной загрузкой.");
      await confirmMonth();
      if (!active.current) return;
      setPendingDelete(null);
    } catch (err) {
      if (active.current) setActionError(formatApiError(err));
    } finally {
      endWrite();
    }
  }

  if (loading) {
    return <LoadingState description="Загружаем позиции…" inline />;
  }

  if (error) {
    return <EmptyState description={error} inline title="Не удалось загрузить позиции" />;
  }

  return (
    <div className={`stack-18 ${styles.root}`}>
      {context.workspace ? (
        <MonthPanelTotal
          value={moneyWholeText(totals.market === null ? null : rub(totals.market), "—")}
          title={formatMoney(totals.market)}
        />
      ) : null}
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={
          <span className={styles.total}>
            {!context.workspace ? (
              <span title={formatMoney(totals.market)}>
                Итого: {moneyWholeText(totals.market === null ? null : rub(totals.market), "—")} ·{" "}
              </span>
            ) : null}
            {filteredPositions.length} поз.
          </span>
        }
        label="Портфель"
        title="Позиции"
      >
        <div className="editor-grid filter-grid">
          <Field htmlFor="pos-filter-account" label="Фильтр: счёт">
            <Select
              id="pos-filter-account"
              onChange={(e) => setFilterAccountId(e.target.value)}
              value={filterAccountId}
            >
              <option value="">Все счета</option>
              {positionAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {positionAccounts.filter((item) => item.name === a.name).length > 1
                    ? ` (${labelOf(ACCOUNT_TYPE_LABELS, a.account_type)})`
                    : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field htmlFor="pos-filter-type" label="Фильтр: тип инструмента">
            <Select
              id="pos-filter-type"
              onChange={(e) => setFilterType(e.target.value)}
              value={filterType}
            >
              <option value="">Все типы</option>
              {positionTypes.map((type) => (
                <option key={type} value={type}>
                  {labelOf(INSTRUMENT_TYPE_LABELS, type)}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {filteredPositions.length === 0 ? (
          <EmptyState
            description="Позиций нет (или фильтр пуст). Добавь позицию формой ниже."
            inline
            title="Пусто"
          />
        ) : (
          <div className={styles.groups}>
            {groups.map((group) => {
              const showAverage = group.rows.some((row) => row.average_cost_per_unit != null);
              const showPrice = group.rows.some((row) => row.market_price_per_unit != null);
              const showResult = group.rows.some((row) => row.unrealized_result != null);
              const compact = !showAverage && !showPrice && !showResult;
              const columnCount =
                3 +
                Number(showAverage) +
                Number(showPrice) +
                Number(showResult) +
                Number(showActions) +
                Number(compact);
              const source = [
                ...new Set(
                  group.rows.map((row) =>
                    fromStatement(row)
                      ? "по выписке брокера"
                      : row.price_source === "manual"
                        ? "вручную"
                        : labelOf(PRICE_SOURCE_LABELS, row.price_source),
                  ),
                ),
              ].join(" · ");
              return (
                <Table
                  key={group.accountId}
                  className={`month-positions-table${editingId != null ? " is-editing" : ""}`}
                >
                  <caption className={styles.groupCaption}>
                    <span className={styles.groupHeading}>
                      <span>
                        {accountById.get(group.accountId)?.name ?? `#${group.accountId}`}{" "}
                        <small>
                          {group.rows.length} поз. · {source}
                        </small>
                      </span>
                      <span className={styles.groupValue} title={formatMoney(group.total)}>
                        {group.total === null ? "" : moneyWholeText(rub(group.total))}{" "}
                        <small>
                          {displayShare(
                            group.total === null ? null : rub(group.total),
                            totals.market,
                          )}
                        </small>
                      </span>
                    </span>
                  </caption>
                  <colgroup>
                    <col />
                    <col className={styles.quantityColumn} />
                    {showAverage ? <col className={styles.priceColumn} /> : null}
                    {showPrice ? <col className={styles.priceColumn} /> : null}
                    <col className={styles.valueColumn} />
                    {showResult ? <col className={styles.valueColumn} /> : null}
                    {compact ? <col className={styles.shareColumn} /> : null}
                    {showActions ? <col className={styles.actionsColumn} /> : null}
                  </colgroup>
                  <thead>
                    <tr>
                      <Th scope="col" className="month-positions-table__instrument">
                        Инструмент
                      </Th>
                      <Th scope="col" numeric title="Количество">
                        Кол-во
                      </Th>
                      {showAverage ? (
                        <Th scope="col" numeric title="Средняя цена приобретения">
                          Цена покупки, ₽
                        </Th>
                      ) : null}
                      {showPrice ? (
                        <Th scope="col" numeric>
                          Цена, ₽
                        </Th>
                      ) : null}
                      <Th scope="col" numeric title="Стоимость и доля в итоге">
                        Стоимость, ₽
                      </Th>
                      {showResult ? (
                        <Th scope="col" numeric>
                          Результат, ₽
                        </Th>
                      ) : null}
                      {compact ? (
                        <Th scope="col" numeric>
                          Доля
                        </Th>
                      ) : null}
                      {showActions ? (
                        <Th
                          scope="col"
                          className="month-positions-table__actions"
                          aria-label="Действия"
                        >
                          ⋯
                        </Th>
                      ) : null}
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((row) => {
                      const editing = editingId === row.id && editDraft;
                      const instrument = instrumentById.get(row.instrument_id);
                      const account = accountById.get(row.account_id);
                      const instrumentTitle = instrument
                        ? shortInstrumentName(instrument)
                        : `#${row.instrument_id}`;
                      if (editing && !priceOnly) {
                        return (
                          <tr className="month-positions-table__edit-row" key={row.id}>
                            <Td colSpan={columnCount}>
                              <form
                                className="position-inline-edit"
                                onKeyDown={(event) => {
                                  if (event.key === "Escape" && !busy) {
                                    event.preventDefault();
                                    setEditingId(null);
                                    setEditDraft(null);
                                  }
                                }}
                                onSubmit={(event) => {
                                  event.preventDefault();
                                  void handleSaveEdit();
                                }}
                              >
                                <div className="position-inline-edit__identity">
                                  <strong>{account?.name ?? `#${row.account_id}`}</strong>
                                  <span>{instrumentTitle}</span>
                                  <span className="muted tiny">
                                    {labelOf(
                                      INSTRUMENT_TYPE_LABELS,
                                      instrument?.instrument_type ?? "—",
                                    )}
                                  </span>
                                </div>
                                <div className="position-inline-edit__grid">
                                  <Field htmlFor={`pos-edit-${row.id}-qty`} label="Количество">
                                    <Input
                                      className="input--money"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-qty`}
                                      value={editDraft.quantity}
                                      onChange={(e) =>
                                        setEditDraft({ ...editDraft, quantity: e.target.value })
                                      }
                                    />
                                  </Field>
                                  <Field
                                    htmlFor={`pos-edit-${row.id}-avg`}
                                    label="Средняя цена приобретения"
                                  >
                                    <Input
                                      className="input--money"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-avg`}
                                      value={editDraft.average_cost}
                                      onChange={(e) =>
                                        setEditDraft({ ...editDraft, average_cost: e.target.value })
                                      }
                                    />
                                  </Field>
                                  <Field htmlFor={`pos-edit-${row.id}-price`} label="Рыночная цена">
                                    <Input
                                      className="input--money"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-price`}
                                      value={editDraft.market_price}
                                      onChange={(e) =>
                                        setEditDraft({ ...editDraft, market_price: e.target.value })
                                      }
                                    />
                                  </Field>
                                  <Field htmlFor={`pos-edit-${row.id}-nkd`} label="НКД">
                                    <Input
                                      aria-label="НКД"
                                      className="input--money"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-nkd`}
                                      placeholder="НКД"
                                      value={editDraft.accrued_interest}
                                      onChange={(e) =>
                                        setEditDraft({
                                          ...editDraft,
                                          accrued_interest: e.target.value,
                                        })
                                      }
                                    />
                                  </Field>
                                  <Field htmlFor={`pos-edit-${row.id}-date`} label="Дата оценки">
                                    <Input
                                      aria-label="Дата оценки"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-date`}
                                      type="date"
                                      value={editDraft.price_date}
                                      onChange={(e) =>
                                        setEditDraft({ ...editDraft, price_date: e.target.value })
                                      }
                                    />
                                  </Field>
                                  <Field
                                    htmlFor={`pos-edit-${row.id}-source`}
                                    label="Источник оценки"
                                  >
                                    <Select
                                      aria-label="Источник оценки"
                                      disabled={busy || readOnly}
                                      id={`pos-edit-${row.id}-source`}
                                      value={editDraft.price_source}
                                      onChange={(e) =>
                                        setEditDraft({ ...editDraft, price_source: e.target.value })
                                      }
                                    >
                                      <option value="manual">Вручную</option>
                                      <option value="moex">Мосбиржа</option>
                                      <option value="alfa_pdf">Выписка Альфа-Банка</option>
                                    </Select>
                                  </Field>
                                  <div className="position-inline-edit__readonly">
                                    <span className="field__label">Рыночная стоимость</span>
                                    <span className="position-inline-edit__readonly-value muted">
                                      {formatMoney(moneyAmount(row.market_value))}
                                    </span>
                                  </div>
                                  <div className="position-inline-edit__readonly">
                                    <span className="field__label">Результат</span>
                                    <span className="position-inline-edit__readonly-value muted">
                                      {formatMoney(moneyAmount(row.unrealized_result))}
                                    </span>
                                  </div>
                                </div>
                                <div className="position-inline-edit__actions">
                                  <Button
                                    disabled={busy || readOnly}
                                    size="sm"
                                    type="submit"
                                    variant="primary"
                                  >
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
                            </Td>
                          </tr>
                        );
                      }
                      return (
                        <tr key={row.id}>
                          <Td
                            className={styles.instrument}
                            title={[instrument?.name, instrument?.ticker, instrument?.isin]
                              .filter(Boolean)
                              .join(" · ")}
                          >
                            {validIsin(instrument?.isin) ? (
                              <Link
                                className={styles.instrumentTitle}
                                to={`/v2/returns/instrument/${instrument?.isin}?${new URLSearchParams({ capital_account: String(row.account_id), back })}`}
                              >
                                {instrumentTitle}
                              </Link>
                            ) : (
                              <span className={styles.instrumentTitle}>{instrumentTitle}</span>
                            )}
                            <div
                              className={styles.meta}
                              title={
                                row.price_date !== defaultPriceDate
                                  ? `Цена от ${formatDate(row.price_date)}`
                                  : undefined
                              }
                            >
                              {labelOf(INSTRUMENT_TYPE_LABELS, instrument?.instrument_type ?? "—")}
                              {showCurrency || !instrument?.currency
                                ? ` · ${instrument?.currency ?? "валюта неизвестна"}`
                                : ""}
                              {row.price_date !== defaultPriceDate
                                ? ` · цена от ${formatDate(row.price_date)}`
                                : ""}
                            </div>
                          </Td>
                          <Td numeric data-label="Количество">
                            {formatQuantity(row.quantity)}
                          </Td>
                          {showAverage ? (
                            <Td
                              numeric
                              data-label="Цена покупки"
                              title={formatMoney(row.average_cost_per_unit?.amount)}
                            >
                              {displayCell(row.average_cost_per_unit, !fromStatement(row))}
                            </Td>
                          ) : null}
                          {showPrice ? (
                            <Td
                              numeric
                              className={styles.priceCell}
                              data-label="Цена"
                              title={formatMoney(row.market_price_per_unit?.amount)}
                            >
                              {!readOnly && !fromStatement(row) ? (
                                <MonthMoneyInput
                                  suffix=""
                                  aria-label={`Цена позиции ${instrumentTitle}`}
                                  disabled={busy || (editingId !== null && editingId !== row.id)}
                                  value={
                                    editing && priceOnly
                                      ? editDraft.market_price
                                      : moneyAmount(row.market_price_per_unit)
                                  }
                                  onChange={(value) => {
                                    setPriceOnly(true);
                                    setEditingId(row.id);
                                    setEditDraft({
                                      ...(editing ? editDraft : editDraftFromPosition(row)),
                                      market_price: value,
                                    });
                                  }}
                                  onKeyDown={(event) => {
                                    if (event.key === "Enter" && editing) {
                                      event.preventDefault();
                                      void handleSaveEdit();
                                    }
                                    if (event.key === "Escape" && !busy) {
                                      event.preventDefault();
                                      setEditingId(null);
                                      setEditDraft(null);
                                    }
                                  }}
                                />
                              ) : (
                                displayCell(row.market_price_per_unit, !fromStatement(row))
                              )}
                              {row.accrued_interest !== null ? (
                                <div
                                  className={styles.meta}
                                  title={formatMoney(moneyAmount(row.accrued_interest))}
                                >
                                  НКД {moneyWholeText(row.accrued_interest)}
                                </div>
                              ) : null}
                            </Td>
                          ) : null}
                          <Td
                            numeric
                            className={styles.marketValue}
                            title={formatMoney(row.market_value?.amount)}
                          >
                            {displayCell(row.market_value, hasMarket)}
                            {!compact && displayShare(row.market_value, totals.market) ? (
                              <div className={`${styles.meta} ${styles.share}`}>
                                {displayShare(row.market_value, totals.market)}
                              </div>
                            ) : null}
                          </Td>
                          {compact ? (
                            <Td numeric className={styles.mobileShare}>
                              {displayShare(row.market_value, totals.market) || "—"}
                            </Td>
                          ) : null}
                          {showResult ? (
                            <Td
                              numeric
                              data-label="Результат"
                              title={formatMoney(row.unrealized_result?.amount)}
                            >
                              <span
                                className={styles.result}
                                data-tone={moneyTone(row.unrealized_result)}
                              >
                                {row.unrealized_result
                                  ? moneyWholeDeltaText({ ...row.unrealized_result, currency: "" })
                                  : displayCell(row.unrealized_result, !fromStatement(row))}
                              </span>
                            </Td>
                          ) : null}
                          {showActions ? (
                            <Td className="month-positions-table__actions">
                              {row.price_source !== "broker_statement_native" ? (
                                <div className="row-actions">
                                  <OverflowMenu
                                    label={`Действия для позиции ${instrument?.name ?? `#${row.instrument_id}`}`}
                                  >
                                    <OverflowMenuItem
                                      disabled={
                                        busy ||
                                        readOnly ||
                                        row.price_source === "broker_statement_native"
                                      }
                                      onClick={() => {
                                        setPriceOnly(false);
                                        setEditingId(row.id);
                                        setEditDraft(editDraftFromPosition(row));
                                      }}
                                    >
                                      Изменить
                                    </OverflowMenuItem>
                                    <OverflowMenuItem
                                      danger
                                      disabled={
                                        busy ||
                                        readOnly ||
                                        row.price_source === "broker_statement_native"
                                      }
                                      onClick={() => setPendingDelete(row)}
                                    >
                                      Удалить
                                    </OverflowMenuItem>
                                  </OverflowMenu>
                                </div>
                              ) : null}
                            </Td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              );
            })}
          </div>
        )}

        {statementExplanation ? (
          <p className={styles.explanation}>
            Брокерская выписка даёт количество и стоимость. Цена покупки и доходность по бумаге — на
            странице инструмента в <Link to="/v2/returns">«Доходности»</Link>.
          </p>
        ) : null}
        {filteredPositions.length > 0 && (totals.cost !== null || totals.result !== null) ? (
          <div className={styles.knownTotals}>
            {totals.cost !== null ? (
              <span>
                Себестоимость:{" "}
                <strong title={formatMoney(totals.cost)}>{moneyWholeText(rub(totals.cost))}</strong>
              </span>
            ) : null}
            {totals.result !== null ? (
              <span>
                Нереализованный результат:{" "}
                <strong
                  className={styles.result}
                  data-tone={moneyTone(rub(totals.result))}
                  title={formatMoney(totals.result)}
                >
                  {moneyWholeDeltaText(rub(totals.result))}
                </strong>
              </span>
            ) : null}
          </div>
        ) : null}

        {!readOnly ? (
          <>
            <MonthSaveBar changed={priceOnly && editingId !== null ? 1 : 0}>
              {priceOnly && editingId !== null ? (
                <>
                  <Button disabled={busy} onClick={() => void handleSaveEdit()} variant="primary">
                    Сохранить цены
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={() => {
                      setEditingId(null);
                      setEditDraft(null);
                    }}
                  >
                    Отмена
                  </Button>
                </>
              ) : null}
              <Button onClick={() => setQuotesOpen((open) => !open)} aria-expanded={quotesOpen}>
                Подтянуть котировки
              </Button>
              <Button onClick={() => setAdding((open) => !open)} aria-expanded={adding}>
                + Добавить позицию
              </Button>
            </MonthSaveBar>
            <div hidden={!adding}>
              <div hidden={!creatingInstrument}>
                <form className="form-stack asset-form" onSubmit={handleCreateInstrument}>
                  <p className="panel__label section-form-label">Быстрый инструмент (словарь)</p>
                  <div className={styles.addGrid}>
                    <Field htmlFor="instr-name" label="Название инструмента">
                      <Input
                        disabled={busy}
                        id="instr-name"
                        onChange={(e) => {
                          setNewInstrumentName(e.target.value);
                          setNewInstrumentTouched(true);
                        }}
                        value={newInstrumentName}
                      />
                    </Field>
                    <Field htmlFor="instr-type" label="Тип инструмента">
                      <Select
                        disabled={busy}
                        id="instr-type"
                        onChange={(e) => {
                          setNewInstrumentType(e.target.value);
                          setNewInstrumentTouched(true);
                        }}
                        value={newInstrumentType}
                      >
                        <option value="stock">Акции</option>
                        <option value="bond">Облигации</option>
                        <option value="fund">Фонды</option>
                        <option value="currency">Валюта</option>
                        <option value="gold">Золото</option>
                        <option value="other">Прочее</option>
                      </Select>
                    </Field>
                    <Field htmlFor="instr-ticker" label="Тикер">
                      <Input
                        disabled={busy}
                        id="instr-ticker"
                        onChange={(e) => {
                          setNewInstrumentTicker(e.target.value);
                          setNewInstrumentTouched(true);
                        }}
                        value={newInstrumentTicker}
                      />
                    </Field>
                  </div>
                  <Button disabled={busy || !newInstrumentName.trim()} type="submit">
                    Создать инструмент
                  </Button>
                </form>
              </div>
              <form className="form-stack asset-form" onSubmit={handleCreatePosition}>
                <p className="panel__label section-form-label">Новая позиция</p>
                <div className={styles.addGrid}>
                  <Field htmlFor="pos-account" label="Счёт позиции">
                    <Select
                      disabled={busy}
                      id="pos-account"
                      onChange={(e) => {
                        setDraft({ ...draft, account_id: e.target.value });
                        setDraftTouched(true);
                      }}
                      value={draft.account_id}
                    >
                      <option value="">авто (создать «Брокерский»)</option>
                      {brokerAccounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name} ({labelOf(ACCOUNT_TYPE_LABELS, a.account_type)})
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field htmlFor="pos-instrument" label="Инструмент позиции">
                    <Select
                      disabled={busy}
                      id="pos-instrument"
                      onChange={(e) => {
                        setDraft({ ...draft, instrument_id: e.target.value });
                        setDraftTouched(true);
                      }}
                      required
                      value={draft.instrument_id}
                    >
                      <option value="">— выбери —</option>
                      {instruments.map((item) => (
                        <option key={item.id} value={item.id}>
                          {instrumentLabel(item)}
                        </option>
                      ))}
                    </Select>
                    <button
                      className={styles.textAction}
                      type="button"
                      onClick={() => setCreatingInstrument((open) => !open)}
                      aria-expanded={creatingInstrument}
                    >
                      Создать инструмент
                    </button>
                  </Field>
                  <Field htmlFor="pos-qty" label="Количество">
                    <Input
                      className="input--money"
                      disabled={busy}
                      id="pos-qty"
                      inputMode="decimal"
                      onChange={(e) => {
                        setDraft({ ...draft, quantity: e.target.value });
                        setDraftTouched(true);
                      }}
                      required
                      value={draft.quantity}
                    />
                  </Field>
                  <Field htmlFor="pos-avg" label="Средняя цена приобретения">
                    <MonthMoneyInput
                      disabled={busy}
                      id="pos-avg"
                      onChange={(value) => {
                        setDraft({ ...draft, average_cost: value });
                        setDraftTouched(true);
                      }}
                      required
                      value={draft.average_cost}
                    />
                  </Field>
                  <Field htmlFor="pos-price" label="Рыночная цена">
                    <MonthMoneyInput
                      disabled={busy}
                      id="pos-price"
                      onChange={(value) => {
                        setDraft({ ...draft, market_price: value });
                        setDraftTouched(true);
                      }}
                      required
                      value={draft.market_price}
                    />
                  </Field>
                  <Field htmlFor="pos-price-date" label="Дата цены">
                    <Input
                      disabled={busy}
                      id="pos-price-date"
                      onChange={(e) => {
                        setDraft({ ...draft, price_date: e.target.value });
                        setDraftTouched(true);
                      }}
                      required
                      type="date"
                      value={draft.price_date}
                    />
                  </Field>
                  <details className={styles.more}>
                    <summary>Ещё параметры</summary>{" "}
                    <Field htmlFor="pos-nkd" label="НКД (облигации, необязательно)">
                      <MonthMoneyInput
                        disabled={busy}
                        id="pos-nkd"
                        onChange={(value) => {
                          setDraft({ ...draft, accrued_interest: value });
                          setDraftTouched(true);
                        }}
                        value={draft.accrued_interest}
                      />
                    </Field>
                    <Field htmlFor="pos-source" label="Источник цены">
                      <Select
                        disabled={busy}
                        id="pos-source"
                        onChange={(e) => {
                          setDraft({ ...draft, price_source: e.target.value });
                          setDraftTouched(true);
                        }}
                        value={draft.price_source}
                      >
                        <option value="manual">Вручную</option>
                        <option value="moex">Мосбиржа</option>
                        <option value="alfa_pdf">Выписка Альфа-Банка</option>
                      </Select>
                    </Field>
                  </details>
                </div>
                <Button disabled={busy} type="submit" variant="primary">
                  Добавить позицию
                </Button>
              </form>
            </div>
          </>
        ) : null}
      </Panel>

      {!readOnly ? (
        <div
          id="month-quotes"
          tabIndex={-1}
          hidden={!quotesOpen && location.hash !== "#month-quotes"}
        >
          <QuotePreviewPanel
            applying={previewApplying}
            applyResult={quoteApplyResult}
            closedMonthHint={readOnly}
            error={previewError}
            loading={previewLoading}
            mappingNotice={mappingNotice}
            onApply={readOnly ? undefined : (rows) => void handleQuoteApply(rows)}
            onMapInstrument={readOnly ? undefined : (row) => void openQuoteMapping(row)}
            onRefresh={() => void handleQuotePreview()}
            preview={quotePreview}
          />
        </div>
      ) : null}

      <InstrumentMappingDialog
        busy={mappingBusy}
        error={mappingError}
        instrument={mappingInstrument}
        mapping={mappingView}
        onCancel={() => {
          if (mappingBusy) return;
          setMappingRow(null);
          setMappingInstrument(null);
          setMappingView(null);
          setMappingError(null);
        }}
        onClear={handleMappingClear}
        onClearExclusion={handleMappingClearExclusion}
        onDiscover={handleMappingDiscover}
        onExclude={handleMappingExclude}
        onSave={handleMappingSave}
        open={mappingRow !== null && mappingInstrument !== null}
      />

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDelete
            ? `Удалить позицию #${pendingDelete.id} (${instrumentById.get(pendingDelete.instrument_id)?.name ?? pendingDelete.instrument_id})?`
            : ""
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void handleDelete()}
        open={pendingDelete !== null}
        title="Удалить позицию?"
      />
    </div>
  );
}
