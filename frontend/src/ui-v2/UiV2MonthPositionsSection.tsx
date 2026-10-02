import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";

import { createAccount, listAccounts } from "../api/accounts";
import { ApiClientError, formatApiError } from "../api/client";
import { createInstrument, listInstruments } from "../api/instruments";
import { getMonth } from "../api/months";
import { createPosition, deletePosition, listPositions, updatePosition } from "../api/positions";
import { applyMonthQuotes, previewMonthQuotes } from "../api/quotePreview";
import type {
  Account,
  Instrument,
  PositionSnapshot,
  QuoteApplyResult,
  QuoteApplyRowRequest,
  QuotePreview,
} from "../api/types";
import { formatDate, formatMoney, formatQuantity } from "../lib/format";
import {
  ACCOUNT_TYPE_LABELS,
  INSTRUMENT_TYPE_LABELS,
  labelOf,
  PRICE_SOURCE_LABELS,
} from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";
import { QuotePreviewPanel } from "../components/QuotePreviewPanel";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  HelpTip,
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
  return sumMoneyAmounts(rows.map((row) => row[field].amount));
}

function displayTotal(amount: string | null) {
  return amount === null ? "Нет подтверждённой суммы" : formatMoney(amount);
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

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<PositionDraft | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PositionSnapshot | null>(null);
  const [quotePreview, setQuotePreview] = useState<QuotePreview | null>(null);
  const [quoteApplyResult, setQuoteApplyResult] = useState<QuoteApplyResult | null>(null);
  const [previewApplying, setPreviewApplying] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const localDirty = draftTouched || newInstrumentTouched || editingId !== null;

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
            a.account_type === "other" ||
            a.account_type === "deposit"),
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
            position.market_price_per_unit.amount !== applied.market_price_per_unit.amount ||
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
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={
          <Badge>
            MV {displayTotal(totals.market)} · {filteredPositions.length} поз.
          </Badge>
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
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({labelOf(ACCOUNT_TYPE_LABELS, a.account_type)})
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
              <option value="stock">Акции</option>
              <option value="bond">Облигации</option>
              <option value="fund">Фонды</option>
              <option value="currency">Валюта</option>
              <option value="gold">Золото</option>
              <option value="other">Прочее</option>
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
          <>
            <p className={styles.scrollHint}>Таблицу позиций можно прокрутить вправо.</p>
            <Table className={`month-positions-table${editingId != null ? " is-editing" : ""}`}>
              <thead>
                <tr>
                  <Th className="month-positions-table__account">Счёт</Th>
                  <Th className="month-positions-table__instrument">Инструмент</Th>
                  <Th numeric>Количество</Th>
                  <Th numeric>Средняя цена приобретения</Th>
                  <Th numeric>Цена</Th>
                  <Th numeric>Рыночная стоимость</Th>
                  <Th numeric>Результат</Th>
                  <Th className="month-positions-table__actions">Действия</Th>
                </tr>
              </thead>
              <tbody>
                {filteredPositions.map((row) => {
                  const editing = editingId === row.id && editDraft;
                  const instrument = instrumentById.get(row.instrument_id);
                  const account = accountById.get(row.account_id);
                  const instrumentTitle = instrument
                    ? `${instrument.name}${instrument.ticker ? ` (${instrument.ticker})` : ""}`
                    : `#${row.instrument_id}`;
                  if (editing) {
                    return (
                      <tr className="month-positions-table__edit-row" key={row.id}>
                        <Td colSpan={8}>
                          <form
                            className="position-inline-edit"
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
                              <Field htmlFor={`pos-edit-${row.id}-source`} label="Источник оценки">
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
                      <Td>{account?.name ?? `#${row.account_id}`}</Td>
                      <Td>
                        {instrumentTitle}
                        <div className="muted tiny">
                          {labelOf(INSTRUMENT_TYPE_LABELS, instrument?.instrument_type ?? "—")} ·{" "}
                          {instrument?.currency ?? "валюта неизвестна"}
                        </div>
                      </Td>
                      <Td numeric>{formatQuantity(row.quantity)}</Td>
                      <Td numeric>{formatMoney(moneyAmount(row.average_cost_per_unit))}</Td>
                      <Td numeric>
                        <span className="position-price">
                          <span>{formatMoney(moneyAmount(row.market_price_per_unit))}</span>
                          <HelpTip
                            label={`Детали оценки для ${instrument?.name ?? `#${row.instrument_id}`}`}
                          >
                            <div>Источник: {labelOf(PRICE_SOURCE_LABELS, row.price_source)}</div>
                            <div>Дата оценки: {formatDate(row.price_date)}</div>
                            {row.accrued_interest ? (
                              <div>НКД {formatMoney(moneyAmount(row.accrued_interest))}</div>
                            ) : null}
                          </HelpTip>
                        </span>
                      </Td>
                      <Td numeric>
                        <span className="muted">{formatMoney(moneyAmount(row.market_value))}</span>
                      </Td>
                      <Td numeric>
                        <span className="muted">
                          {formatMoney(moneyAmount(row.unrealized_result))}
                        </span>
                      </Td>
                      <Td className="month-positions-table__actions">
                        <div className="row-actions">
                          <OverflowMenu
                            label={`Действия для позиции ${instrument?.name ?? `#${row.instrument_id}`}`}
                          >
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingId(row.id);
                                setEditDraft(editDraftFromPosition(row));
                              }}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setPendingDelete(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </>
        )}

        <div className="totals-bar">
          <span>
            Рыночная стоимость: <strong>{displayTotal(totals.market)}</strong>
          </span>
          <span>
            Себестоимость: <strong>{displayTotal(totals.cost)}</strong>
          </span>
          <span>
            Нереализованный результат: <strong>{displayTotal(totals.result)}</strong>
          </span>
        </div>
        <details className="field-details">
          <summary>Как читаются итоги позиции</summary>
          <p>
            Рыночная стоимость, себестоимость и нереализованный результат приходят из расчёта
            позиции.
          </p>
        </details>

        {!readOnly ? (
          <>
            <form className="form-stack asset-form" onSubmit={handleCreateInstrument}>
              <p className="panel__label section-form-label">Быстрый инструмент (словарь)</p>
              <div className="editor-grid">
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

            <form className="form-stack asset-form" onSubmit={handleCreatePosition}>
              <p className="panel__label section-form-label">Новая позиция</p>
              <div className="editor-grid">
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
                  <Input
                    className="input--money"
                    disabled={busy}
                    id="pos-avg"
                    inputMode="decimal"
                    onChange={(e) => {
                      setDraft({ ...draft, average_cost: e.target.value });
                      setDraftTouched(true);
                    }}
                    required
                    value={draft.average_cost}
                  />
                </Field>
                <Field htmlFor="pos-price" label="Рыночная цена">
                  <Input
                    className="input--money"
                    disabled={busy}
                    id="pos-price"
                    inputMode="decimal"
                    onChange={(e) => {
                      setDraft({ ...draft, market_price: e.target.value });
                      setDraftTouched(true);
                    }}
                    required
                    value={draft.market_price}
                  />
                </Field>
                <Field htmlFor="pos-nkd" label="НКД (облигации, необязательно)">
                  <Input
                    className="input--money"
                    disabled={busy}
                    id="pos-nkd"
                    inputMode="decimal"
                    onChange={(e) => {
                      setDraft({ ...draft, accrued_interest: e.target.value });
                      setDraftTouched(true);
                    }}
                    value={draft.accrued_interest}
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
              </div>
              <Button disabled={busy} type="submit" variant="primary">
                Добавить позицию
              </Button>
            </form>
          </>
        ) : null}
      </Panel>

      <div id="month-quotes" tabIndex={-1}>
        <QuotePreviewPanel
          applying={previewApplying}
          applyResult={quoteApplyResult}
          closedMonthHint={readOnly}
          error={previewError}
          loading={previewLoading}
          onApply={readOnly ? undefined : (rows) => void handleQuoteApply(rows)}
          onRefresh={() => void handleQuotePreview()}
          preview={quotePreview}
        />
      </div>

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
