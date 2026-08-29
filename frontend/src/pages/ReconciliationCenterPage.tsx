import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { listAccounts } from "../api/accounts";
import {
  type BrokerReconciliationResponse,
  previewBrokerReconciliation,
  type ReconciliationAccount,
  type ReconciliationInstrument,
  type ReconciliationRow,
} from "../api/brokerReconciliation";
import { formatApiError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import type { Account, Instrument, ReportingMonth } from "../api/types";
import {
  Badge,
  Button,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDateTime, formatMoney, formatMonth, formatQuantity } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { queryKeys } from "../queryClient";

type MappingValues = Record<string, string>;
type RowFilter = "all" | "attention" | "matched";
type BadgeTone = "neutral" | "ok" | "info" | "stale" | "unknown" | "missing";

const ROW_STATE_LABELS: Record<string, string> = {
  matched: "Совпадает",
  differs: "Отличается",
  missing_local: "Нет локальной позиции",
  missing_provider: "Нет позиции у брокера",
  unresolved: "Не сопоставлено",
};

const RECONCILIATION_STATUS_LABELS: Record<string, string> = {
  applicable: "Проверка выполнена",
  conflicts: "Есть конфликты сопоставления",
  non_applicable: "Не применяется",
};

const REASON_LABELS: Record<string, string> = {
  "quantity differs": "Количество отличается",
  mapping_unresolved: "Сопоставление не завершено",
  mapping_conflict: "В сопоставлении есть конфликт",
  account_mapping_unresolved: "Сопоставление счёта не завершено",
  instrument_mapping_unresolved: "Сопоставление инструмента не завершено",
  position_mapping_conflict: "Конфликт идентичности позиции",
  compatibility_unknown: "Совместимость протокола неизвестна",
  "no explicit owner mapping for provider account":
    "Нет явного сопоставления владельца для счёта брокера",
  "no Hermes instrument with this ISIN": "Нет локального инструмента с этим ISIN",
  "no ISIN and no explicit mapping; ticker/name/provider id are not identity":
    "Нет ISIN и нет явного сопоставления; тикер, имя и ID провайдера не являются идентичностью",
  "multiple Hermes instruments share this ISIN": "Несколько локальных инструментов имеют этот ISIN",
  "conflicting explicit owner mapping: provider account id mapped to multiple Hermes accounts":
    "Конфликт: один счёт брокера сопоставлен с несколькими локальными счетами",
  "duplicate provider account identifier in snapshot":
    "В снимке повторяется идентификатор счёта брокера",
  "explicit mapping targets a Hermes account id that does not exist":
    "Явное сопоставление указывает на несуществующий локальный счёт",
  "conflicting explicit owner mapping: provider instrument id mapped to multiple Hermes instruments":
    "Конфликт: один инструмент брокера сопоставлен с несколькими локальными инструментами",
  "explicit mapping contradicts provider ISIN evidence":
    "Явное сопоставление противоречит ISIN брокера",
  "explicit mapping targets a Hermes instrument id that does not exist":
    "Явное сопоставление указывает на несуществующий локальный инструмент",
  "explicit owner mapping": "Явное сопоставление владельца",
  "exact unique ISIN match": "Точное уникальное совпадение ISIN",
  "conflicting metadata for the same provider instrument identifier":
    "Конфликт метаданных для одного идентификатора инструмента брокера",
  "provider account mapping is unresolved": "Сопоставление счёта брокера не завершено",
  "provider instrument mapping is unresolved": "Сопоставление инструмента брокера не завершено",
};

const COMPARISON_FIELD_LABELS: Record<string, string> = {
  provider_broker_unit_price: "Цена брокера",
  provider_accounting_price: "Учётная цена брокера",
  provider_market_value: "Оценка брокера",
  provider_accrued_interest_nkd: "НКД брокера",
  provider_unrealized_result: "P&L брокера",
};

function rowStateLabel(state: string): string {
  return ROW_STATE_LABELS[state] ?? state;
}

function rowStateTone(state: string): BadgeTone {
  if (state === "matched") return "ok";
  if (state === "differs") return "info";
  if (state === "unresolved") return "unknown";
  if (state === "missing_local" || state === "missing_provider") return "missing";
  return "neutral";
}

function resultStatusTone(status: string): BadgeTone {
  if (status === "applicable") return "ok";
  if (status === "conflicts") return "unknown";
  return "stale";
}

function reasonLabel(reason: string | null): string {
  if (!reason) return "—";
  return REASON_LABELS[reason] ?? "Требуется дополнительная проверка данных";
}

function valueOrDash(value: string | null | undefined): string {
  return value == null || value === "" ? "—" : value;
}

function kopecksToMajor(value: number | null): string | null {
  if (value == null || !Number.isInteger(value)) return null;
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  const whole = Math.floor(absolute / 100);
  const minor = String(absolute % 100).padStart(2, "0");
  return `${sign}${whole}.${minor}`;
}

function formatKopecks(value: number | null): string {
  return formatMoney(kopecksToMajor(value));
}

function formatProviderAmount(value: string | null): string {
  return formatMoney(value);
}

function rowKey(row: ReconciliationRow): string {
  return [
    row.state,
    row.account_id ?? "provider",
    row.instrument_id ?? "row",
    row.provider_account_id ?? "account",
    row.provider_instrument_id ?? "instrument",
    row.fingerprint ?? "no-fingerprint",
  ].join("-");
}

function isComparisonUnavailable(result: BrokerReconciliationResponse): boolean {
  return (
    result.stale ||
    result.compatibility_state !== "compatible" ||
    result.snapshot_status !== "complete"
  );
}

function nonApplicableReason(result: BrokerReconciliationResponse): string | null {
  if (result.stale) {
    return "Снимок устарел. Сверка и любые следующие действия неприменимы до явного обновления снимка.";
  }
  if (result.compatibility_state !== "compatible") {
    return "Совместимость снимка не подтверждена. Результат оставлен для диагностики и неприменим.";
  }
  if (result.snapshot_status !== "complete") {
    return "Снимок неполный или недоступен. Сверка неприменима до нового явного запроса.";
  }
  return null;
}

function mappingFromValues(accountValues: MappingValues, instrumentValues: MappingValues) {
  return {
    accounts: Object.entries(accountValues)
      .filter(([, hermesId]) => hermesId !== "")
      .map(([providerAccountId, hermesId]) => ({
        hermes_account_id: Number(hermesId),
        provider_account_id: providerAccountId,
      })),
    instruments: Object.entries(instrumentValues)
      .filter(([, hermesId]) => hermesId !== "")
      .map(([providerInstrumentId, hermesId]) => ({
        hermes_instrument_id: Number(hermesId),
        provider_instrument_id: providerInstrumentId,
      })),
  };
}

function accountMappingValue(row: ReconciliationAccount, values: MappingValues): string {
  return (
    values[row.provider_account_id] ??
    (row.status === "matched" && row.hermes_account_id != null ? String(row.hermes_account_id) : "")
  );
}

function instrumentMappingValue(row: ReconciliationInstrument, values: MappingValues): string {
  if (!row.provider_instrument_id) return "";
  return (
    values[row.provider_instrument_id] ??
    (row.status === "matched" ? String(row.hermes_instrument_id) : "")
  );
}

function joinIdentityParts(parts: Array<string | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part?.trim())).join(" · ");
}

function observedInstrumentShortLabel(item: {
  display_name: string | null;
  isin: string | null;
  ticker: string | null;
}): string {
  return item.display_name?.trim() || item.isin?.trim() || item.ticker?.trim() || "";
}

function instrumentMappingLabel(row: ReconciliationInstrument): string {
  const readable = joinIdentityParts([row.display_name, row.isin, row.ticker]);
  return readable || `Источник: ${row.provider_instrument_id ?? "—"}`;
}

const ACCOUNT_MAPPING_VISIBLE_INSTRUMENTS = 3;

function accountMappingLabel(row: ReconciliationAccount): string {
  const sections = (row.section_codes ?? []).map((code) => `Раздел ${code}`);
  const instruments = (row.observed_instruments ?? [])
    .map(observedInstrumentShortLabel)
    .filter((label) => label !== "");
  const visible = instruments.slice(0, ACCOUNT_MAPPING_VISIBLE_INSTRUMENTS);
  const hiddenCount = instruments.length - visible.length;
  const extra = hiddenCount > 0 ? [`ещё ${hiddenCount}`] : [];
  const readable = [...sections, ...visible, ...extra].join(" · ");
  return readable || `Источник: ${row.provider_account_id}`;
}

function mappingSourceLine(providerId: string, label: string): string | null {
  if (label === `Источник: ${providerId}`) return null;
  return `Источник: ${providerId}`;
}

function accountDisplay(account: Account): string {
  return account.name;
}

function instrumentDisplay(instrument: Instrument): string {
  const identity = instrument.isin ?? instrument.ticker;
  return `${instrument.name}${identity ? ` · ${identity}` : ""}`;
}

function MappingPanel({
  result,
  accounts,
  instruments,
  accountsLoading,
  instrumentsLoading,
  accountsError,
  instrumentsError,
  accountValues,
  instrumentValues,
  onAccountChange,
  onInstrumentChange,
}: {
  result: BrokerReconciliationResponse;
  accounts: Account[];
  instruments: Instrument[];
  accountsLoading: boolean;
  instrumentsLoading: boolean;
  accountsError: string | null;
  instrumentsError: string | null;
  accountValues: MappingValues;
  instrumentValues: MappingValues;
  onAccountChange: (providerId: string, hermesId: string) => void;
  onInstrumentChange: (providerId: string, hermesId: string) => void;
}) {
  const accountRows = result.accounts.filter((row) => row.status !== "matched");
  const instrumentRows = result.instruments.filter(
    (row) => row.provider_instrument_id && row.status !== "matched",
  );
  if (accountRows.length === 0 && instrumentRows.length === 0) return null;

  return (
    <Panel label="Сопоставление" title="Требуется явное решение владельца">
      <p className="reconciliation-center__mapping-copy">
        Выбери существующий локальный счёт или инструмент только для строк, которые приложение
        отметило как нерешённые. Эти значения временные: сохранения и автосопоставления здесь нет.
      </p>
      <div className="reconciliation-center__mapping-grid">
        {accountRows.length > 0 ? (
          <div className="reconciliation-center__mapping-group">
            <h3>Счета</h3>
            {accountsLoading ? (
              <LoadingState description="Загружаем локальные счета…" inline />
            ) : null}
            {accountsError ? (
              <ErrorState description={accountsError} inline title="Не удалось загрузить счета" />
            ) : null}
            {!accountsLoading && !accountsError
              ? accountRows.map((row, index) => {
                  const label = accountMappingLabel(row);
                  const sourceLine = mappingSourceLine(row.provider_account_id, label);
                  return (
                    <Field
                      key={row.provider_account_id}
                      htmlFor={`reconciliation-account-${index}`}
                      label={label}
                    >
                      <Select
                        id={`reconciliation-account-${index}`}
                        value={accountMappingValue(row, accountValues)}
                        onChange={(event) =>
                          onAccountChange(row.provider_account_id, event.target.value)
                        }
                      >
                        <option value="">— выбрать локальный счёт —</option>
                        {accounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {accountDisplay(account)}
                          </option>
                        ))}
                      </Select>
                      {sourceLine ? (
                        <span className="reconciliation-center__mapping-source">{sourceLine}</span>
                      ) : null}
                      <span className="reconciliation-center__mapping-reason">
                        Причина: {reasonLabel(row.reason)}
                      </span>
                    </Field>
                  );
                })
              : null}
          </div>
        ) : null}

        {instrumentRows.length > 0 ? (
          <div className="reconciliation-center__mapping-group">
            <h3>Инструменты</h3>
            {instrumentsLoading ? (
              <LoadingState description="Загружаем локальные инструменты…" inline />
            ) : null}
            {instrumentsError ? (
              <ErrorState
                description={instrumentsError}
                inline
                title="Не удалось загрузить инструменты"
              />
            ) : null}
            {!instrumentsLoading && !instrumentsError
              ? instrumentRows.map((row, index) => {
                  const providerId = row.provider_instrument_id as string;
                  const label = instrumentMappingLabel(row);
                  const sourceLine = mappingSourceLine(providerId, label);
                  return (
                    <Field
                      key={providerId}
                      htmlFor={`reconciliation-instrument-${index}`}
                      label={label}
                    >
                      <Select
                        id={`reconciliation-instrument-${index}`}
                        value={instrumentMappingValue(row, instrumentValues)}
                        onChange={(event) => onInstrumentChange(providerId, event.target.value)}
                      >
                        <option value="">— выбрать локальный инструмент —</option>
                        {instruments.map((instrument) => (
                          <option key={instrument.id} value={instrument.id}>
                            {instrumentDisplay(instrument)}
                          </option>
                        ))}
                      </Select>
                      {sourceLine ? (
                        <span className="reconciliation-center__mapping-source">{sourceLine}</span>
                      ) : null}
                      <span className="reconciliation-center__mapping-reason">
                        Причина: {reasonLabel(row.reason)}
                      </span>
                    </Field>
                  );
                })
              : null}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

function IdentityCell({ row }: { row: ReconciliationRow }) {
  const instrumentIdentity = [row.instrument_ticker, row.instrument_isin]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="reconciliation-center__identity">
      <strong>{row.account_name ?? "Счёт не сопоставлен"}</strong>
      <span>{row.instrument_name ?? "Инструмент не сопоставлен"}</span>
      {instrumentIdentity ? <span className="muted">{instrumentIdentity}</span> : null}
      <span className="reconciliation-center__identity-provider">
        Идентификаторы источника: {valueOrDash(row.provider_account_id)} /{" "}
        {valueOrDash(row.provider_instrument_id)}
      </span>
      <details className="reconciliation-center__fingerprint">
        <summary>Технический ключ строки</summary>
        <code>{valueOrDash(row.fingerprint)}</code>
      </details>
    </div>
  );
}

function ValueComparisonCell({ row }: { row: ReconciliationRow }) {
  return (
    <div className="reconciliation-center__values">
      <span>
        Локальная цена/ед.:{" "}
        <strong>{formatKopecks(row.hermes_market_price_per_unit_kopecks)}</strong>
      </span>
      <span>
        Цена брокера: <strong>{formatProviderAmount(row.provider_broker_unit_price)}</strong>
        <small>только сравнение</small>
      </span>
      <span>
        Учётная цена брокера: <strong>{formatProviderAmount(row.provider_accounting_price)}</strong>
        <small>только сравнение</small>
      </span>
      <span>
        Оценка брокера: <strong>{formatProviderAmount(row.provider_market_value)}</strong>
        <small>только сравнение</small>
      </span>
      <span>
        Локальный НКД: <strong>{formatKopecks(row.hermes_accrued_interest_kopecks)}</strong>
      </span>
      <span>
        НКД брокера: <strong>{formatProviderAmount(row.provider_accrued_interest_nkd)}</strong>
        <small>только сравнение</small>
      </span>
      <span>
        Локальный P&amp;L: <strong>{formatKopecks(row.hermes_unrealized_result_kopecks)}</strong>
      </span>
      <span>
        P&amp;L брокера: <strong>{formatProviderAmount(row.provider_unrealized_result)}</strong>
        <small>только сравнение</small>
      </span>
      <details>
        <summary>Ограничения сравнения</summary>
        <span>
          Цена: {row.price_comparable}; НКД: {row.nkd_comparable}; P&amp;L:{" "}
          {row.unrealized_comparable}
          {row.comparison_only_fields.length > 0
            ? ` · поля: ${row.comparison_only_fields
                .map((field) => COMPARISON_FIELD_LABELS[field] ?? field)
                .join(", ")}`
            : ""}
        </span>
      </details>
    </div>
  );
}

function ReconciliationTable({
  result,
  filter,
  onFilterChange,
}: {
  result: BrokerReconciliationResponse;
  filter: RowFilter;
  onFilterChange: (filter: RowFilter) => void;
}) {
  const rows = useMemo(() => {
    if (filter === "matched") return result.rows.filter((row) => row.state === "matched");
    if (filter === "attention") return result.rows.filter((row) => row.state !== "matched");
    return result.rows;
  }, [filter, result.rows]);

  return (
    <Panel
      action={
        <label className="reconciliation-center__filter" htmlFor="reconciliation-row-filter">
          <span>Показывать</span>
          <Select
            aria-label="Фильтр строк сверки"
            id="reconciliation-row-filter"
            value={filter}
            onChange={(event) => onFilterChange(event.target.value as RowFilter)}
          >
            <option value="all">Все строки</option>
            <option value="attention">Требуют внимания</option>
            <option value="matched">Только совпадения</option>
          </Select>
        </label>
      }
      label="Нормализованные строки"
      title="Счёт и инструмент"
    >
      {rows.length === 0 ? (
        <EmptyState
          description={
            result.rows.length === 0
              ? "Приложение не получило сравнимых строк. Проверь причины и при необходимости открой диагностику ниже."
              : "В выбранном фильтре строк нет."
          }
          inline
          title="Нет строк для показа"
        />
      ) : (
        <Table className="reconciliation-center__table">
          <thead>
            <tr>
              <Th>Состояние</Th>
              <Th>Идентичность</Th>
              <Th numeric>Локальное количество</Th>
              <Th numeric>Количество у брокера</Th>
              <Th numeric>Разница</Th>
              <Th>Стоимость и наблюдения</Th>
              <Th>Причина</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                <Td>
                  <div className="reconciliation-center__state">
                    <Badge tone={rowStateTone(row.state)}>{rowStateLabel(row.state)}</Badge>
                  </div>
                </Td>
                <Td>
                  <IdentityCell row={row} />
                </Td>
                <Td numeric>{formatQuantity(row.hermes_quantity)}</Td>
                <Td numeric>{formatQuantity(row.provider_quantity)}</Td>
                <Td numeric>{formatQuantity(row.quantity_difference)}</Td>
                <Td>
                  <ValueComparisonCell row={row} />
                </Td>
                <Td>
                  <div className="reconciliation-center__reason">
                    <span>{reasonLabel(row.reason)}</span>
                    {row.state === "unresolved" ? (
                      <strong>Нельзя считать сопоставление безопасным</strong>
                    ) : null}
                    {row.warnings.length > 0 ? (
                      <ul>
                        {row.warnings.map((warning) => (
                          <li key={warning}>{reasonLabel(warning)}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Panel>
  );
}

function DiagnosticPanel({ result }: { result: BrokerReconciliationResponse }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const diagnostic = result.diagnostics;
  const safeToCopy =
    diagnostic.safe_artifact &&
    !diagnostic.raw_payload_saved &&
    !diagnostic.private_values_included &&
    !diagnostic.credentials_included;

  async function copyDiagnostic() {
    if (!safeToCopy) return;
    try {
      await navigator.clipboard.writeText(result.diagnostic_report);
      setCopied(true);
      setCopyError(false);
    } catch {
      setCopied(false);
      setCopyError(true);
    }
  }

  return (
    <details className="reconciliation-center__diagnostic-disclosure">
      <summary>Техническая диагностика</summary>
      <Panel label="По запросу" title="Совместимость и технические сведения">
        <div className="reconciliation-center__diagnostic-grid">
          <DataValue label="Источник" value={valueOrDash(result.provider)} />
          <DataValue
            label="Технический статус снимка"
            value={valueOrDash(result.snapshot_status)}
          />
          <DataValue
            label="Снимок устарел"
            value={result.stale ? "Да" : "Нет"}
            className={result.stale ? "reconciliation-center__diagnostic-value--bad" : ""}
          />
          <DataValue label="Совместимость" value={valueOrDash(result.compatibility_state)} />
          <DataValue
            label="Ключ совместимости"
            value={valueOrDash(result.compatibility_fingerprint)}
          />
          <DataValue label="Ключ снимка" value={valueOrDash(result.snapshot_fingerprint)} />
          <DataValue label="Источник наблюдения" value={formatDateTime(result.source_as_of)} />
          <DataValue label="Получено" value={formatDateTime(result.captured_at)} />
          <DataValue label="Версия описания API" value={valueOrDash(diagnostic.api_doc_version)} />
          <DataValue
            label="Версия Alfa PRO"
            value={valueOrDash(diagnostic.observed_alfa_pro_version)}
          />
          <DataValue label="Версия API" value={valueOrDash(diagnostic.observed_api_version)} />
          <DataValue
            label="Версия протокола"
            value={valueOrDash(diagnostic.observed_protocol_version)}
          />
          <DataValue
            label="Семейство протокола и структуры"
            value={`${diagnostic.protocol_family} / ${diagnostic.layout_family}`}
          />
          <DataValue label="Класс сбоя" value={valueOrDash(diagnostic.failure_class)} />
          <DataValue
            label="Безопасный артефакт"
            value={diagnostic.safe_artifact ? "Да" : "Нет"}
            className={
              diagnostic.safe_artifact ? "" : "reconciliation-center__diagnostic-value--bad"
            }
          />
        </div>

        <div className="reconciliation-center__diagnostic-reasons">
          <div>
            <strong>Коды причин</strong>
            <p>
              {diagnostic.failure_codes.length > 0 ? diagnostic.failure_codes.join(" · ") : "Нет"}
            </p>
          </div>
          <div>
            <strong>Наблюдения по сущностям</strong>
            <p>
              {diagnostic.entity_status.length > 0 ? diagnostic.entity_status.join(" · ") : "Нет"}
              {diagnostic.entity_counts.length > 0
                ? ` · ${diagnostic.entity_counts.join(" · ")}`
                : ""}
            </p>
          </div>
        </div>

        <details className="reconciliation-center__diagnostic-details">
          <summary>Показать безопасный диагностический текст</summary>
          {safeToCopy ? (
            <>
              <p className="muted">
                Здесь только очищенные технические поля. Сырые ответы, учётные данные и локальные
                пути не показываются.
              </p>
              <pre>{result.diagnostic_report}</pre>
              <Button onClick={() => void copyDiagnostic()} size="sm" type="button">
                {copied ? "Скопировано" : "Скопировать диагностику"}
              </Button>
              {copyError ? (
                <span className="reconciliation-center__copy-error" role="alert">
                  Не удалось скопировать. Выдели текст вручную.
                </span>
              ) : null}
            </>
          ) : (
            <p className="muted">
              Диагностический текст скрыт: приложение не подтвердило безопасность данных.
            </p>
          )}
        </details>
      </Panel>
    </details>
  );
}

function ResultSummary({ result }: { result: BrokerReconciliationResponse }) {
  const counts = result.rows.reduce<Record<string, number>>((accumulator, row) => {
    accumulator[row.state] = (accumulator[row.state] ?? 0) + 1;
    return accumulator;
  }, {});
  const knownStates = ["matched", "differs", "missing_local", "missing_provider", "unresolved"];

  return (
    <div className="reconciliation-center__summary-grid">
      <DataValue label="Всего строк" value={result.rows.length} />
      {knownStates.map((state) => (
        <DataValue key={state} label={rowStateLabel(state)} value={counts[state] ?? 0} />
      ))}
    </div>
  );
}

function ResultView({
  result,
  accounts,
  instruments,
  accountsLoading,
  instrumentsLoading,
  accountsError,
  instrumentsError,
  accountValues,
  instrumentValues,
  onAccountChange,
  onInstrumentChange,
  mappingDirty,
}: {
  result: BrokerReconciliationResponse;
  accounts: Account[];
  instruments: Instrument[];
  accountsLoading: boolean;
  instrumentsLoading: boolean;
  accountsError: string | null;
  instrumentsError: string | null;
  accountValues: MappingValues;
  instrumentValues: MappingValues;
  onAccountChange: (providerId: string, hermesId: string) => void;
  onInstrumentChange: (providerId: string, hermesId: string) => void;
  mappingDirty: boolean;
}) {
  const [filter, setFilter] = useState<RowFilter>("all");
  const unavailable = isComparisonUnavailable(result);
  const unavailableMessage = nonApplicableReason(result);

  return (
    <>
      <Panel
        action={
          <Badge tone={resultStatusTone(result.status)}>
            {labelOf(RECONCILIATION_STATUS_LABELS, result.status)}
          </Badge>
        }
        label="Результат"
        title="Сверка без изменений данных"
      >
        <ResultSummary result={result} />
        <p className="reconciliation-center__read-only-note">
          <strong>Только чтение.</strong> Результат не сохраняется и не содержит операций
          применения. Цена брокера, учётная цена, оценка, НКД и P&amp;L показаны только как
          наблюдения только для сравнения.
        </p>
        {unavailableMessage ? (
          <div className="reconciliation-center__gate" role="status">
            <Badge tone="stale">Сверка неприменима</Badge>
            <div>
              <strong>Сверка остановлена из соображений безопасности</strong>
              <p>{unavailableMessage}</p>
            </div>
          </div>
        ) : null}
        {mappingDirty && !unavailable ? (
          <div className="inline-alert" role="status">
            Сопоставление изменилось. Повтори явную проверку, чтобы увидеть результат для нового
            сопоставления.
          </div>
        ) : null}
        {result.warnings.length > 0 ? (
          <div className="reconciliation-center__warnings">
            <strong>Предупреждения источника</strong>
            <ul>
              {result.warnings.map((warning) => (
                <li key={warning}>{reasonLabel(warning)}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Panel>

      {!unavailable ? (
        <MappingPanel
          accounts={accounts}
          accountsError={accountsError}
          accountsLoading={accountsLoading}
          accountValues={accountValues}
          instruments={instruments}
          instrumentsError={instrumentsError}
          instrumentsLoading={instrumentsLoading}
          instrumentValues={instrumentValues}
          onAccountChange={onAccountChange}
          onInstrumentChange={onInstrumentChange}
          result={result}
        />
      ) : null}
      <ReconciliationTable filter={filter} onFilterChange={setFilter} result={result} />
      <DiagnosticPanel result={result} />
    </>
  );
}

export function ReconciliationCenterPage() {
  const [selectedMonthId, setSelectedMonthId] = useState("");
  const [result, setResult] = useState<BrokerReconciliationResponse | null>(null);
  const [accountValues, setAccountValues] = useState<MappingValues>({});
  const [instrumentValues, setInstrumentValues] = useState<MappingValues>({});
  const [mappingDirty, setMappingDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    select: (months: ReportingMonth[]) =>
      [...months].sort((left, right) => right.year - left.year || right.month - left.month),
  });
  const accountsQuery = useQuery({
    enabled: result !== null && !isComparisonUnavailable(result),
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const instrumentsQuery = useQuery({
    enabled: result !== null && !isComparisonUnavailable(result),
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
  });
  const previewMutation = useMutation({
    mutationFn: ({
      monthId,
      mapping,
    }: {
      monthId: number;
      mapping: ReturnType<typeof mappingFromValues>;
    }) => previewBrokerReconciliation(monthId, mapping),
  });

  const months = monthsQuery.data ?? [];
  const monthsError = monthsQuery.error ? formatApiError(monthsQuery.error) : null;

  async function runReconciliation() {
    const monthId = Number(selectedMonthId);
    if (!Number.isInteger(monthId) || monthId < 1) {
      setActionError("Выбери отчётный месяц.");
      return;
    }
    setActionError(null);
    try {
      const next = await previewMutation.mutateAsync({
        monthId,
        mapping: mappingFromValues(accountValues, instrumentValues),
      });
      setResult(next);
      setMappingDirty(false);
      if (next.error_code && next.message) setActionError(next.message);
    } catch (error) {
      setActionError(formatApiError(error));
    }
  }

  function changeMonth(value: string) {
    setSelectedMonthId(value);
    setResult(null);
    setAccountValues({});
    setInstrumentValues({});
    setMappingDirty(false);
    setActionError(null);
  }

  function changeAccountMapping(providerId: string, hermesId: string) {
    setAccountValues((current) => ({ ...current, [providerId]: hermesId }));
    setMappingDirty(true);
  }

  function changeInstrumentMapping(providerId: string, hermesId: string) {
    setInstrumentValues((current) => ({ ...current, [providerId]: hermesId }));
    setMappingDirty(true);
  }

  return (
    <section className="stack-18 reconciliation-center">
      <header className="page-header">
        <p className="eyebrow">Контроль данных</p>
        <h1>Сверка портфеля</h1>
        <p className="page-header__description">
          Нормализованное сравнение локального среза с наблюдением брокера. Открытие страницы не
          обращается к внешнему источнику: запрос выполняется только по явной кнопке владельца.
        </p>
      </header>

      <Panel label="Явное действие" title="Запросить снимок только для чтения">
        <p className="reconciliation-center__action-copy">
          Выбери отчётный месяц и нажми кнопку. Используется проверенный сценарий сверки; база
          данных не изменяется, фонового обновления нет.
        </p>
        <div className="reconciliation-center__action-grid">
          <Field htmlFor="reconciliation-month" label="Отчётный месяц">
            <Select
              id="reconciliation-month"
              value={selectedMonthId}
              onChange={(event) => changeMonth(event.target.value)}
              disabled={monthsQuery.isPending}
            >
              <option value="">
                {monthsQuery.isPending ? "Загружаем месяцы…" : "— выбрать месяц —"}
              </option>
              {months.map((month) => (
                <option key={month.id} value={month.id}>
                  {formatMonth(month.year, month.month)} ·{" "}
                  {labelOf(MONTH_STATUS_LABELS, month.status)}
                </option>
              ))}
            </Select>
          </Field>
          <div className="reconciliation-center__action-button">
            <Button
              disabled={previewMutation.isPending || !selectedMonthId}
              onClick={() => void runReconciliation()}
              type="button"
              variant="primary"
            >
              {previewMutation.isPending
                ? "Получаем снимок…"
                : result
                  ? "Обновить сверку"
                  : "Проверить снимок"}
            </Button>
            <span className="muted">Только явное действие · без автозапроса</span>
          </div>
        </div>
        {monthsError ? (
          <div className="inline-alert inline-alert--error" role="alert">
            Не удалось загрузить месяцы: {monthsError}
          </div>
        ) : null}
        {actionError ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {actionError}
          </div>
        ) : null}
      </Panel>

      {result ? (
        <ResultView
          accountValues={accountValues}
          accounts={accountsQuery.data ?? []}
          accountsError={accountsQuery.error ? formatApiError(accountsQuery.error) : null}
          accountsLoading={accountsQuery.isPending}
          instrumentValues={instrumentValues}
          instruments={instrumentsQuery.data ?? []}
          instrumentsError={instrumentsQuery.error ? formatApiError(instrumentsQuery.error) : null}
          instrumentsLoading={instrumentsQuery.isPending}
          mappingDirty={mappingDirty}
          onAccountChange={changeAccountMapping}
          onInstrumentChange={changeInstrumentMapping}
          result={result}
        />
      ) : (
        <Panel label="Результат" title="Сверка ещё не запрашивалась">
          <EmptyState
            description="Страница готова. Выбери месяц и запусти проверку, когда понадобится. Простое открытие не обращается к внешнему источнику."
            inline
            title="Нет снимка источника"
          />
        </Panel>
      )}
    </section>
  );
}
