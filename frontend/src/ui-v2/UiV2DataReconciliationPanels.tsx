import { useMemo, useState } from "react";
import { Link } from "react-router";

import type { BrokerReconciliationResponse } from "../api/brokerReconciliation";
import type { Account, Instrument, ReportingMonth } from "../api/types";
import { formatMonth, formatQuantity } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import dataStyles from "./UiV2Data.module.css";
import {
  accountMappingValue,
  instrumentMappingValue,
  type MappingValues,
  type RowFilter,
  rowKey,
  rowStateLabel,
  rowStateTone,
} from "./UiV2DataReconciliationParts";

export function MonthToolbar({
  months,
  selected,
  onSelect,
  onRun,
  running,
  hasResult,
}: {
  months: ReportingMonth[];
  selected: ReportingMonth;
  onSelect: (id: number) => void;
  onRun: () => void;
  running: boolean;
  hasResult: boolean;
}) {
  return (
    <div className={dataStyles.toolbar} data-testid="reconciliation-action">
      <div className={dataStyles.field}>
        <label htmlFor="data-reconciliation-month">Отчётный месяц</label>
        <select
          id="data-reconciliation-month"
          value={selected.id}
          onChange={(event) => onSelect(Number(event.target.value))}
        >
          {months.map((month) => (
            <option key={month.id} value={month.id}>
              {formatMonth(month.year, month.month)} · {labelOf(MONTH_STATUS_LABELS, month.status)}
            </option>
          ))}
        </select>
      </div>
      <button className={dataStyles.primaryButton} disabled={running} onClick={onRun} type="button">
        {running ? "Получаем снимок…" : hasResult ? "Обновить сверку" : "Проверить снимок"}
      </button>
      <p className={dataStyles.hint}>Только явное действие · без автозапроса при открытии</p>
    </div>
  );
}

export function ResultSummary({ result }: { result: BrokerReconciliationResponse }) {
  const counts = result.rows.reduce<Record<string, number>>((acc, row) => {
    acc[row.state] = (acc[row.state] ?? 0) + 1;
    return acc;
  }, {});
  const known = ["matched", "differs", "missing_local", "missing_provider", "unresolved"];
  return (
    <dl className={dataStyles.summaryGrid}>
      <div className={dataStyles.summaryItem}>
        <dt>Всего строк</dt>
        <dd>{result.rows.length}</dd>
      </div>
      {known.map((state) => (
        <div className={dataStyles.summaryItem} key={state}>
          <dt>{rowStateLabel(state)}</dt>
          <dd>{counts[state] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}

export function MappingPanel({
  result,
  accounts,
  instruments,
  accountValues,
  instrumentValues,
  onAccountChange,
  onInstrumentChange,
}: {
  result: BrokerReconciliationResponse;
  accounts: Account[];
  instruments: Instrument[];
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
    <section className={dataStyles.resultPanel} data-testid="reconciliation-mapping">
      <h2>Временное сопоставление</h2>
      <p className={dataStyles.muted}>
        Значения только для этого запроса. Сохранения здесь нет — постоянное сопоставление в
        справочниках.
      </p>
      <div className={dataStyles.mappingGrid}>
        {accountRows.map((row, index) => (
          <div className={dataStyles.mappingField} key={row.provider_account_id}>
            <label htmlFor={`v2-recon-account-${index}`}>Счёт · {row.provider_account_id}</label>
            <select
              id={`v2-recon-account-${index}`}
              value={accountMappingValue(row, accountValues)}
              onChange={(event) => onAccountChange(row.provider_account_id, event.target.value)}
            >
              <option value="">— выбрать локальный счёт —</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </div>
        ))}
        {instrumentRows.map((row, index) => {
          const providerId = row.provider_instrument_id as string;
          return (
            <div className={dataStyles.mappingField} key={providerId}>
              <label htmlFor={`v2-recon-instrument-${index}`}>
                Инструмент · {row.display_name ?? providerId}
              </label>
              <select
                id={`v2-recon-instrument-${index}`}
                value={instrumentMappingValue(row, instrumentValues)}
                onChange={(event) => onInstrumentChange(providerId, event.target.value)}
              >
                <option value="">— выбрать локальный инструмент —</option>
                {instruments.map((instrument) => (
                  <option key={instrument.id} value={instrument.id}>
                    {instrument.name}
                    {instrument.isin ? ` · ${instrument.isin}` : ""}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
      <p className={dataStyles.familyActions}>
        <Link to="/v2/data/catalogs">Сохранить сопоставление в справочниках →</Link>
        <Link to="/settings">В текущем интерфейсе · настройки ↗</Link>
      </p>
    </section>
  );
}

export function RowsPanel({ result }: { result: BrokerReconciliationResponse }) {
  const [filter, setFilter] = useState<RowFilter>("all");
  const rows = useMemo(() => {
    if (filter === "matched") return result.rows.filter((row) => row.state === "matched");
    if (filter === "attention") return result.rows.filter((row) => row.state !== "matched");
    return result.rows;
  }, [filter, result.rows]);

  return (
    <section className={dataStyles.resultPanel} data-testid="reconciliation-rows">
      <h2>Нормализованные строки</h2>
      <div className={dataStyles.filterRow}>
        <label htmlFor="v2-recon-filter">
          Показывать
          <select
            aria-label="Фильтр строк сверки"
            id="v2-recon-filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value as RowFilter)}
          >
            <option value="all">Все строки</option>
            <option value="attention">Требуют внимания</option>
            <option value="matched">Только совпадения</option>
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <p className={dataStyles.muted}>Нет строк для показа в выбранном фильтре.</p>
      ) : (
        <div className={dataStyles.provenance}>
          <table className={dataStyles.rowTable}>
            <thead>
              <tr>
                <th>Состояние</th>
                <th>Идентичность</th>
                <th>Локально</th>
                <th>У брокера</th>
                <th>Разница</th>
                <th>Причина</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={rowKey(row)}>
                  <td>
                    <span className={dataStyles.statusBadge} data-tone={rowStateTone(row.state)}>
                      {rowStateLabel(row.state)}
                    </span>
                  </td>
                  <td>
                    <strong>{row.account_name ?? "Счёт не сопоставлен"}</strong>
                    <div>{row.instrument_name ?? "Инструмент не сопоставлен"}</div>
                  </td>
                  <td>{formatQuantity(row.hermes_quantity)}</td>
                  <td>{formatQuantity(row.provider_quantity)}</td>
                  <td>{formatQuantity(row.quantity_difference)}</td>
                  <td>
                    {row.reason ?? "—"}
                    {row.state === "unresolved" ? (
                      <div>
                        <strong>Нельзя считать сопоставление безопасным</strong>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function DiagnosticPanel({ result }: { result: BrokerReconciliationResponse }) {
  const diagnostic = result.diagnostics;
  const safeToShow =
    diagnostic.safe_artifact &&
    !diagnostic.raw_payload_saved &&
    !diagnostic.private_values_included &&
    !diagnostic.credentials_included;
  return (
    <details className={dataStyles.disclosure} data-testid="reconciliation-diagnostics">
      <summary>Техническая диагностика</summary>
      <p className={dataStyles.muted}>
        Источник: {result.provider} · статус снимка: {result.snapshot_status} · совместимость:{" "}
        {result.compatibility_state} · устарел: {result.stale ? "да" : "нет"}
      </p>
      {safeToShow ? (
        <pre className={dataStyles.diagnosticPre}>{result.diagnostic_report}</pre>
      ) : (
        <p className={dataStyles.muted}>
          Диагностический текст скрыт: приложение не подтвердило безопасность данных.
        </p>
      )}
    </details>
  );
}
