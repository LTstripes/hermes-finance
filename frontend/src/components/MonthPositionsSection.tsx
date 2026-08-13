import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { createAccount, listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { createInstrument, listInstruments } from "../api/instruments";
import { createPosition, deletePosition, listPositions, updatePosition } from "../api/positions";
import { previewMonthQuotes } from "../api/quotePreview";
import type { Account, Instrument, PositionSnapshot, QuotePreview } from "../api/types";
import { QuotePreviewPanel } from "./QuotePreviewPanel";
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
  OverflowMenu,
  OverflowMenuItem,
} from "./ui";
import { formatDate, formatMoney, formatQuantity } from "../lib/format";
import {
  ACCOUNT_TYPE_LABELS,
  INSTRUMENT_TYPE_LABELS,
  PRICE_SOURCE_LABELS,
  labelOf,
} from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type MonthPositionsSectionProps = {
  monthId: number;
  readOnly: boolean;
  defaultPriceDate: string;
  onDirtyChange?: (dirty: boolean) => void;
};

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
  return `${instrument.name}${ticker} · ${labelOf(INSTRUMENT_TYPE_LABELS, instrument.instrument_type)}`;
}

export function MonthPositionsSection({
  monthId,
  readOnly,
  defaultPriceDate,
  onDirtyChange,
}: MonthPositionsSectionProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
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
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const localDirty = draftTouched || newInstrumentTouched || editingId !== null;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [accs, instrs, rows] = await Promise.all([
          listAccounts(signal),
          listInstruments({ active: true }, signal),
          listPositions(monthId, undefined, signal),
        ]);
        if (signal?.aborted) {
          return;
        }
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
    [defaultPriceDate, monthId],
  );

  useEffect(() => {
    setQuotePreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
    const controller = new AbortController();
    void load(controller.signal);
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
      market: sumMoneyAmounts(filteredPositions.map((p) => moneyAmount(p.market_value))),
      cost: sumMoneyAmounts(filteredPositions.map((p) => moneyAmount(p.cost_basis))),
      result: sumMoneyAmounts(filteredPositions.map((p) => moneyAmount(p.unrealized_result))),
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
    setActionError(null);
    setBusy(true);
    try {
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
      setInstruments((prev) => [...prev, created]);
      setDraft((prev) => ({ ...prev, instrument_id: String(created.id) }));
      setDraftTouched(true);
      setNewInstrumentName("");
      setNewInstrumentTicker("");
      setNewInstrumentTouched(false);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreatePosition(event: FormEvent) {
    event.preventDefault();
    setActionError(null);
    setBusy(true);
    try {
      if (!normalizeMoneyInput(draft.average_cost) || !normalizeMoneyInput(draft.market_price)) {
        throw new Error("Укажи среднюю стоимость и рыночную цену");
      }
      let accountId = Number(draft.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) {
        accountId = await ensureBrokerAccount();
      }
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
      await createPosition(payload);
      setDraft(() => ({
        ...emptyDraft(defaultPriceDate),
        account_id: String(accountId),
        instrument_id: String(instrumentId),
      }));
      setDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveEdit() {
    if (editingId == null || !editDraft) {
      return;
    }
    const current = positions.find((p) => p.id === editingId);
    if (!current) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const instrumentType = instrumentById.get(current.instrument_id)?.instrument_type;
      const qty = normalizeQuantity(editDraft.quantity, instrumentType);
      if (!qty) {
        throw new Error(quantityError(instrumentType));
      }
      await updatePosition(
        editingId,
        {
          quantity: qty,
          average_cost_per_unit: rub(editDraft.average_cost),
          market_price_per_unit: rub(editDraft.market_price),
          accrued_interest:
            editDraft.accrued_interest.trim() === "" ? null : rub(editDraft.accrued_interest),
          price_source: editDraft.price_source,
          price_date: editDraft.price_date,
        },
        current.updated_at,
      );
      setEditingId(null);
      setEditDraft(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleQuotePreview() {
    if (previewLoading) {
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      setQuotePreview(await previewMonthQuotes(monthId));
    } catch (err) {
      setPreviewError(formatApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleDelete() {
    if (!pendingDelete) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deletePosition(pendingDelete.id);
      setPendingDelete(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDelete(null);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <LoadingState description="Загружаем позиции…" inline />;
  }

  if (error) {
    return <EmptyState description={error} inline title="Не удалось загрузить позиции" />;
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
            MV {formatMoney(totals.market)} · {filteredPositions.length} поз.
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
          <Table className="month-positions-table">
            <thead>
              <tr>
                <Th>Счёт</Th>
                <Th>Инструмент</Th>
                <Th numeric>Количество</Th>
                <Th numeric>Средняя цена приобретения</Th>
                <Th numeric>Цена</Th>
                <Th numeric>Рыночная стоимость</Th>
                <Th numeric>Результат</Th>
                <Th>Детали оценки</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {filteredPositions.map((row) => {
                const editing = editingId === row.id && editDraft;
                const instrument = instrumentById.get(row.instrument_id);
                const account = accountById.get(row.account_id);
                return (
                  <tr key={row.id}>
                    <Td>{account?.name ?? `#${row.account_id}`}</Td>
                    <Td>
                      {instrument
                        ? `${instrument.name}${instrument.ticker ? ` (${instrument.ticker})` : ""}`
                        : `#${row.instrument_id}`}
                      <div className="muted tiny">
                        {labelOf(INSTRUMENT_TYPE_LABELS, instrument?.instrument_type ?? "—")}
                      </div>
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDraft.quantity}
                          onChange={(e) => setEditDraft({ ...editDraft, quantity: e.target.value })}
                        />
                      ) : (
                        formatQuantity(row.quantity)
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDraft.average_cost}
                          onChange={(e) =>
                            setEditDraft({ ...editDraft, average_cost: e.target.value })
                          }
                        />
                      ) : (
                        formatMoney(moneyAmount(row.average_cost_per_unit))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          className="input--money"
                          value={editDraft.market_price}
                          onChange={(e) =>
                            setEditDraft({ ...editDraft, market_price: e.target.value })
                          }
                        />
                      ) : (
                        formatMoney(moneyAmount(row.market_price_per_unit))
                      )}
                    </Td>
                    <Td numeric>
                      <span className="muted">{formatMoney(moneyAmount(row.market_value))}</span>
                    </Td>
                    <Td numeric>
                      <span className="muted">
                        {formatMoney(moneyAmount(row.unrealized_result))}
                      </span>
                    </Td>
                    <Td>
                      {editing ? (
                        <div className="stack-8">
                          <Input
                            type="date"
                            value={editDraft.price_date}
                            onChange={(e) =>
                              setEditDraft({ ...editDraft, price_date: e.target.value })
                            }
                          />
                          <Select
                            value={editDraft.price_source}
                            onChange={(e) =>
                              setEditDraft({ ...editDraft, price_source: e.target.value })
                            }
                          >
                            <option value="manual">Вручную</option>
                            <option value="moex">Мосбиржа</option>
                            <option value="alfa_pdf">Выписка Альфа-Банка</option>
                          </Select>
                          <Input
                            className="input--money"
                            placeholder="НКД"
                            value={editDraft.accrued_interest}
                            onChange={(e) =>
                              setEditDraft({
                                ...editDraft,
                                accrued_interest: e.target.value,
                              })
                            }
                          />
                        </div>
                      ) : (
                        <>
                          {row.price_date !== defaultPriceDate ? (
                            <div>Оценка на {formatDate(row.price_date)}</div>
                          ) : null}
                          <div className="muted tiny">
                            Источник: {labelOf(PRICE_SOURCE_LABELS, row.price_source)}
                          </div>
                          {row.accrued_interest ? (
                            <div className="muted tiny">
                              НКД {formatMoney(moneyAmount(row.accrued_interest))}
                            </div>
                          ) : null}
                        </>
                      )}
                    </Td>
                    <Td>
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveEdit()}
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
                              disabled={busy || readOnly}
                              onClick={() => {
                                setEditingId(row.id);
                                setEditDraft({
                                  account_id: String(row.account_id),
                                  instrument_id: String(row.instrument_id),
                                  quantity: row.quantity,
                                  average_cost: moneyAmount(row.average_cost_per_unit),
                                  market_price: moneyAmount(row.market_price_per_unit),
                                  accrued_interest: moneyAmount(row.accrued_interest),
                                  price_source: row.price_source,
                                  price_date: row.price_date,
                                });
                              }}
                              size="sm"
                              type="button"
                            >
                              Изменить
                            </Button>
                            <OverflowMenu
                              label={`Действия для позиции ${instrument?.name ?? `#${row.instrument_id}`}`}
                            >
                              <OverflowMenuItem
                                danger
                                disabled={busy || readOnly}
                                onClick={() => setPendingDelete(row)}
                              >
                                Удалить
                              </OverflowMenuItem>
                            </OverflowMenu>
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

        <div className="totals-bar">
          <span>
            Рыночная стоимость: <strong>{formatMoney(totals.market)}</strong>
          </span>
          <span>
            Себестоимость: <strong>{formatMoney(totals.cost)}</strong>
          </span>
          <span>
            Нереализованный результат: <strong>{formatMoney(totals.result)}</strong>
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

      <QuotePreviewPanel
        closedMonthHint={readOnly}
        error={previewError}
        loading={previewLoading}
        onRefresh={() => void handleQuotePreview()}
        preview={quotePreview}
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
