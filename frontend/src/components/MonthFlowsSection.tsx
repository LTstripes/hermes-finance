import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import {
  createExpectedFlow,
  deleteExpectedFlow,
  listExpectedFlows,
  listExpectedFlowsCalendar,
} from "../api/expectedFlows";
import {
  createInvestmentFlow,
  deleteInvestmentFlow,
  listInvestmentFlows,
} from "../api/investmentFlows";
import { listInstruments } from "../api/instruments";
import type {
  Account,
  ExpectedCalendarMonth,
  ExpectedFlow,
  Instrument,
  InvestmentFlow,
} from "../api/types";
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
import { ExpectedPaymentsCalendar } from "./ExpectedPaymentsCalendar";
import { formatDate, formatMoney } from "../lib/format";
import { FLOW_TYPE_LABELS, labelOf } from "../lib/labels";
import {
  isPassiveExpectedFlowType,
  isPassiveInvestmentFlowType,
  isRedemptionFlowType,
} from "../lib/flowTypes";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";

type MonthFlowsSectionProps = {
  monthId: number;
  readOnly: boolean;
  defaultDate: string;
  onDirtyChange?: (dirty: boolean) => void;
};

type ActualDraft = {
  account_id: string;
  instrument_id: string;
  flow_type: string;
  event_date: string;
  gross: string;
  tax: string;
  commission: string;
  net: string;
  source: string;
};

type ExpectedDraft = {
  account_id: string;
  instrument_id: string;
  flow_type: string;
  expected_date: string;
  gross: string;
  tax: string;
  net: string;
  source: string;
  forecast_version: string;
};

function emptyActual(date: string): ActualDraft {
  return {
    account_id: "",
    instrument_id: "",
    flow_type: "coupon",
    event_date: date,
    gross: "",
    tax: "0.00",
    commission: "0.00",
    net: "",
    source: "manual",
  };
}

function emptyExpected(date: string): ExpectedDraft {
  return {
    account_id: "",
    instrument_id: "",
    flow_type: "coupon",
    expected_date: date,
    gross: "",
    tax: "",
    net: "",
    source: "manual",
    forecast_version: "v1",
  };
}

export function MonthFlowsSection({
  monthId,
  readOnly,
  defaultDate,
  onDirtyChange,
}: MonthFlowsSectionProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [actual, setActual] = useState<InvestmentFlow[]>([]);
  const [expected, setExpected] = useState<ExpectedFlow[]>([]);
  const [calendar, setCalendar] = useState<ExpectedCalendarMonth[]>([]);
  const [forecastVersion, setForecastVersion] = useState("v1");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actualDraft, setActualDraft] = useState<ActualDraft>(() => emptyActual(defaultDate));
  const [expectedDraft, setExpectedDraft] = useState<ExpectedDraft>(() =>
    emptyExpected(defaultDate),
  );
  const [actualDraftTouched, setActualDraftTouched] = useState(false);
  const [expectedDraftTouched, setExpectedDraftTouched] = useState(false);
  const [pendingDeleteActual, setPendingDeleteActual] = useState<InvestmentFlow | null>(null);
  const [pendingDeleteExpected, setPendingDeleteExpected] = useState<ExpectedFlow | null>(null);

  const localDirty = actualDraftTouched || expectedDraftTouched;

  useEffect(() => {
    onDirtyChange?.(localDirty);
  }, [localDirty, onDirtyChange]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [accs, instrs, flows, exp, cal] = await Promise.all([
          listAccounts(signal),
          listInstruments({ active: true }, signal),
          listInvestmentFlows(monthId, undefined, signal),
          listExpectedFlows(monthId, forecastVersion, signal),
          listExpectedFlowsCalendar(monthId, forecastVersion, signal),
        ]);
        if (signal?.aborted) {
          return;
        }
        setAccounts(accs);
        setInstruments(instrs);
        setActual(flows);
        setExpected(exp);
        setCalendar(cal);

        const firstAccount = accs.find((a) => a.status === "active");
        const firstInstrument = instrs[0];
        setActualDraft((prev) => ({
          ...prev,
          account_id: prev.account_id || (firstAccount ? String(firstAccount.id) : ""),
          event_date: prev.event_date || defaultDate,
        }));
        setExpectedDraft((prev) => ({
          ...prev,
          account_id: prev.account_id || (firstAccount ? String(firstAccount.id) : ""),
          instrument_id: prev.instrument_id || (firstInstrument ? String(firstInstrument.id) : ""),
          expected_date: prev.expected_date || defaultDate,
          forecast_version: forecastVersion,
        }));
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
    [defaultDate, forecastVersion, monthId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const accountName = useMemo(() => {
    const map = new Map(accounts.map((a) => [a.id, a.name]));
    return (id: number) => map.get(id) ?? `#${id}`;
  }, [accounts]);

  const instrumentName = useMemo(() => {
    const map = new Map(
      instruments.map((i) => [i.id, i.ticker ? `${i.name} (${i.ticker})` : i.name]),
    );
    return (id: number | null) => (id == null ? "—" : (map.get(id) ?? `#${id}`));
  }, [instruments]);

  const sortedActual = useMemo(
    () => [...actual].sort((a, b) => a.event_date.localeCompare(b.event_date) || a.id - b.id),
    [actual],
  );
  const sortedExpected = useMemo(
    () =>
      [...expected].sort((a, b) => a.expected_date.localeCompare(b.expected_date) || a.id - b.id),
    [expected],
  );

  const passiveActualTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedActual
          .filter((f) => isPassiveInvestmentFlowType(f.flow_type))
          .map((f) => moneyAmount(f.net_amount)),
      ),
    [sortedActual],
  );
  const redemptionActualTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedActual
          .filter((f) => isRedemptionFlowType(f.flow_type))
          .map((f) => moneyAmount(f.net_amount)),
      ),
    [sortedActual],
  );
  const expectedPassiveTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedExpected
          .filter((f) => isPassiveExpectedFlowType(f.flow_type))
          .map((f) => moneyAmount(f.expected_net_amount)),
      ),
    [sortedExpected],
  );

  async function handleCreateActual(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!normalizeMoneyInput(actualDraft.gross) || !normalizeMoneyInput(actualDraft.net)) {
        throw new Error("Укажи gross и net");
      }
      const accountId = Number(actualDraft.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) {
        throw new Error("Выбери счёт");
      }
      const instrumentId = actualDraft.instrument_id ? Number(actualDraft.instrument_id) : null;
      await createInvestmentFlow({
        reporting_month_id: monthId,
        account_id: accountId,
        flow_type: actualDraft.flow_type,
        event_date: actualDraft.event_date,
        gross_amount: rub(actualDraft.gross),
        tax_amount: rub(actualDraft.tax.trim() === "" ? "0" : actualDraft.tax),
        commission_amount: rub(actualDraft.commission.trim() === "" ? "0" : actualDraft.commission),
        net_amount: rub(actualDraft.net),
        instrument_id: instrumentId && instrumentId > 0 ? instrumentId : null,
        source: actualDraft.source.trim() || "manual",
      });
      setActualDraft((prev) => ({
        ...emptyActual(defaultDate),
        account_id: prev.account_id,
      }));
      setActualDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateExpected(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!normalizeMoneyInput(expectedDraft.gross)) {
        throw new Error("Укажи expected gross");
      }
      const accountId = Number(expectedDraft.account_id);
      const instrumentId = Number(expectedDraft.instrument_id);
      if (!Number.isInteger(accountId) || accountId < 1) {
        throw new Error("Выбери счёт");
      }
      if (!Number.isInteger(instrumentId) || instrumentId < 1) {
        throw new Error("Выбери инструмент для ожидаемой выплаты");
      }
      const payload = {
        reporting_month_id: monthId,
        account_id: accountId,
        instrument_id: instrumentId,
        flow_type: expectedDraft.flow_type,
        expected_date: expectedDraft.expected_date,
        gross_amount: rub(expectedDraft.gross),
        source: expectedDraft.source.trim() || "manual",
        source_as_of_date: defaultDate,
        forecast_version: expectedDraft.forecast_version.trim() || forecastVersion,
        ...(expectedDraft.tax.trim() === "" ? {} : { expected_tax_amount: rub(expectedDraft.tax) }),
        ...(expectedDraft.net.trim() === "" ? {} : { expected_net_amount: rub(expectedDraft.net) }),
      };
      await createExpectedFlow(payload);
      setForecastVersion(payload.forecast_version);
      setExpectedDraft((prev) => ({
        ...emptyExpected(defaultDate),
        account_id: prev.account_id,
        instrument_id: prev.instrument_id,
        forecast_version: payload.forecast_version,
      }));
      setExpectedDraftTouched(false);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteActual() {
    if (!pendingDeleteActual) return;
    setBusy(true);
    setActionError(null);
    try {
      await deleteInvestmentFlow(pendingDeleteActual.id);
      setPendingDeleteActual(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDeleteActual(null);
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteExpected() {
    if (!pendingDeleteExpected) return;
    setBusy(true);
    setActionError(null);
    try {
      await deleteExpectedFlow(pendingDeleteExpected.id);
      setPendingDeleteExpected(null);
      await load();
    } catch (err) {
      setActionError(formatApiError(err));
      setPendingDeleteExpected(null);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <LoadingState description="Загружаем выплаты…" inline />;
  }
  if (error) {
    return <EmptyState description={error} inline title="Не удалось загрузить выплаты" />;
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
          <Badge tone="draft">пассивный доход, нетто {formatMoney(passiveActualTotal)}</Badge>
        }
        label="Выплаты"
        title="Фактические потоки"
      >
        {sortedActual.length === 0 ? (
          <EmptyState
            description="Фактических купонов, дивидендов и процентов ещё нет."
            inline
            title="Пусто"
          />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Счёт / инструмент</Th>
                <Th numeric>Брутто</Th>
                <Th numeric>Налог</Th>
                <Th numeric>Комиссия</Th>
                <Th numeric>Нетто</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {sortedActual.map((row) => {
                const redemption = isRedemptionFlowType(row.flow_type);
                const passive = isPassiveInvestmentFlowType(row.flow_type);
                return (
                  <tr
                    className={redemption ? "row--muted" : passive ? "row--income" : undefined}
                    key={row.id}
                  >
                    <Td>{formatDate(row.event_date)}</Td>
                    <Td>
                      <span className={redemption ? "badge badge--closed" : "badge badge--draft"}>
                        {labelOf(FLOW_TYPE_LABELS, row.flow_type)}
                      </span>
                      {redemption ? <div className="muted tiny">не доход (погашение)</div> : null}
                      {passive ? <div className="muted tiny">пассивный доход</div> : null}
                    </Td>
                    <Td>
                      <div>{accountName(row.account_id)}</div>
                      <div className="muted tiny">{instrumentName(row.instrument_id)}</div>
                    </Td>
                    <Td numeric>{formatMoney(moneyAmount(row.gross_amount))}</Td>
                    <Td numeric>{formatMoney(moneyAmount(row.tax_amount))}</Td>
                    <Td numeric>{formatMoney(moneyAmount(row.commission_amount))}</Td>
                    <Td numeric>{formatMoney(moneyAmount(row.net_amount))}</Td>
                    <Td>
                      <Button
                        disabled={busy || readOnly}
                        onClick={() => setPendingDeleteActual(row)}
                        size="sm"
                        type="button"
                        variant="danger"
                      >
                        Удал.
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}

        <div className="totals-bar">
          <span>
            Пассивный доход (нетто): <strong>{formatMoney(passiveActualTotal)}</strong>
          </span>
          <span>
            Погашение (не доход): <strong>{formatMoney(redemptionActualTotal)}</strong>
          </span>
        </div>
        <details className="field-details">
          <summary>О классификации выплат</summary>
          <p>
            Погашение — возврат номинала, а не доход. Фактический процент по депозиту вводится в
            разделе активов.
          </p>
        </details>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateActual}>
            <p className="panel__label section-form-label">Новая фактическая выплата</p>
            <div className="editor-grid">
              <Field htmlFor="act-type" label="Тип потока">
                <Select
                  id="act-type"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, flow_type: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  value={actualDraft.flow_type}
                >
                  <option value="coupon">Купон</option>
                  <option value="dividend">Дивиденды</option>
                  <option value="interest">Проценты</option>
                  <option value="redemption">Погашение</option>
                  <option value="commission">Комиссия</option>
                  <option value="tax">Налог</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="act-date" label="Дата события">
                <Input
                  id="act-date"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, event_date: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  required
                  type="date"
                  value={actualDraft.event_date}
                />
              </Field>
              <Field htmlFor="act-account" label="Счёт фактической выплаты">
                <Select
                  id="act-account"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, account_id: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  required
                  value={actualDraft.account_id}
                >
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="act-instr" label="Инструмент (необязательно)">
                <Select
                  id="act-instr"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, instrument_id: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  value={actualDraft.instrument_id}
                >
                  <option value="">—</option>
                  {instruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.ticker ? ` (${i.ticker})` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="act-gross" label="Брутто">
                <Input
                  className="input--money"
                  id="act-gross"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, gross: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  required
                  value={actualDraft.gross}
                />
              </Field>
              <Field htmlFor="act-tax" label="Налог">
                <Input
                  className="input--money"
                  id="act-tax"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, tax: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  value={actualDraft.tax}
                />
              </Field>
              <Field htmlFor="act-comm" label="Комиссия">
                <Input
                  className="input--money"
                  id="act-comm"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, commission: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  value={actualDraft.commission}
                />
              </Field>
              <Field htmlFor="act-net" label="Нетто">
                <Input
                  className="input--money"
                  id="act-net"
                  onChange={(e) => {
                    setActualDraft({ ...actualDraft, net: e.target.value });
                    setActualDraftTouched(true);
                  }}
                  required
                  value={actualDraft.net}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить выплату
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>прогноз пассивного дохода {formatMoney(expectedPassiveTotal)}</Badge>}
        label="Календарь"
        title="Ожидаемые потоки"
      >
        <div className="editor-grid filter-grid">
          <Field htmlFor="exp-version" label="Версия прогноза">
            <Input
              id="exp-version"
              onChange={(e) => setForecastVersion(e.target.value || "v1")}
              onBlur={() => void load()}
              value={forecastVersion}
            />
          </Field>
        </div>

        {sortedExpected.length === 0 ? (
          <EmptyState
            description={`Нет ожидаемых выплат для версии «${forecastVersion}».`}
            inline
            title="Пусто"
          />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Инструмент</Th>
                <Th numeric>Брутто</Th>
                <Th numeric>Прогноз налога</Th>
                <Th numeric>Прогноз нетто</Th>
                <Th>Статус</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {sortedExpected.map((row) => {
                const redemption = isRedemptionFlowType(row.flow_type);
                return (
                  <tr className={redemption ? "row--muted" : "row--income"} key={row.id}>
                    <Td>{formatDate(row.expected_date)}</Td>
                    <Td>
                      <span className={redemption ? "badge badge--closed" : "badge badge--draft"}>
                        {labelOf(FLOW_TYPE_LABELS, row.flow_type)}
                      </span>
                      {redemption ? <div className="muted tiny">погашение ≠ доход</div> : null}
                    </Td>
                    <Td>{instrumentName(row.instrument_id)}</Td>
                    <Td numeric>{formatMoney(moneyAmount(row.gross_amount))}</Td>
                    <Td numeric>
                      {row.expected_tax_amount
                        ? formatMoney(moneyAmount(row.expected_tax_amount))
                        : "—"}
                    </Td>
                    <Td numeric>{formatMoney(moneyAmount(row.expected_net_amount))}</Td>
                    <Td>
                      <div className="muted tiny">
                        {row.is_confirmed ? "подтверждено" : "план"}
                        {row.is_approximate ? " · примерно" : ""}
                      </div>
                      <div className="muted tiny">{row.forecast_version}</div>
                    </Td>
                    <Td>
                      <Button
                        disabled={busy || readOnly}
                        onClick={() => setPendingDeleteExpected(row)}
                        size="sm"
                        type="button"
                        variant="danger"
                      >
                        Удал.
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}

        <div className="totals-bar">
          <span>
            Прогноз пассивного дохода (нетто): <strong>{formatMoney(expectedPassiveTotal)}</strong>
          </span>
        </div>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateExpected}>
            <p className="panel__label section-form-label">Новая ожидаемая выплата</p>
            <div className="editor-grid">
              <Field htmlFor="exp-type" label="Тип выплаты">
                <Select
                  id="exp-type"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, flow_type: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  value={expectedDraft.flow_type}
                >
                  <option value="coupon">Купон</option>
                  <option value="dividend">Дивиденды</option>
                  <option value="interest">Проценты</option>
                  <option value="redemption">Погашение</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="exp-date" label="Дата выплаты">
                <Input
                  id="exp-date"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, expected_date: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  required
                  type="date"
                  value={expectedDraft.expected_date}
                />
              </Field>
              <Field htmlFor="exp-account" label="Счёт выплаты">
                <Select
                  id="exp-account"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, account_id: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  required
                  value={expectedDraft.account_id}
                >
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="exp-instr" label="Инструмент выплаты">
                <Select
                  id="exp-instr"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, instrument_id: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  required
                  value={expectedDraft.instrument_id}
                >
                  <option value="">—</option>
                  {instruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.ticker ? ` (${i.ticker})` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="exp-gross" label="Прогноз брутто">
                <Input
                  className="input--money"
                  id="exp-gross"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, gross: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  required
                  value={expectedDraft.gross}
                />
              </Field>
              <Field htmlFor="exp-tax" label="Прогноз налога (необязательно)">
                <Input
                  className="input--money"
                  id="exp-tax"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, tax: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  value={expectedDraft.tax}
                />
              </Field>
              <Field htmlFor="exp-net" label="Прогноз нетто (необязательно)">
                <Input
                  className="input--money"
                  id="exp-net"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, net: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  value={expectedDraft.net}
                />
              </Field>
              <Field htmlFor="exp-ver" label="Версия">
                <Input
                  id="exp-ver"
                  onChange={(e) => {
                    setExpectedDraft({ ...expectedDraft, forecast_version: e.target.value });
                    setExpectedDraftTouched(true);
                  }}
                  value={expectedDraft.forecast_version}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить ожидаемую выплату
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel action={<Badge>12 месяцев вперёд</Badge>} label="Прогноз" title="Календарь выплат">
        <ExpectedPaymentsCalendar months={calendar} />
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDeleteActual
            ? `Удалить выплату «${labelOf(FLOW_TYPE_LABELS, pendingDeleteActual.flow_type)}» от ${pendingDeleteActual.event_date}?`
            : ""
        }
        onCancel={() => setPendingDeleteActual(null)}
        onConfirm={() => void confirmDeleteActual()}
        open={pendingDeleteActual !== null}
        title="Удалить выплату?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDeleteExpected
            ? `Удалить ожидаемую выплату «${labelOf(FLOW_TYPE_LABELS, pendingDeleteExpected.flow_type)}» на ${pendingDeleteExpected.expected_date}?`
            : ""
        }
        onCancel={() => setPendingDeleteExpected(null)}
        onConfirm={() => void confirmDeleteExpected()}
        open={pendingDeleteExpected !== null}
        title="Удалить ожидаемую выплату?"
      />
    </div>
  );
}
