import { useEffect, useMemo, useState } from "react";

import { formatApiError } from "../api/client";
import { getFreshnessProvenance } from "../api/freshnessProvenance";
import { listMonths } from "../api/months";
import type {
  FreshnessFamily,
  FreshnessItem,
  FreshnessProvenanceSummary,
  FreshnessStatus,
  ReportingMonth,
} from "../api/types";
import {
  Badge,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  HelpTip,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatDateTime, formatMonth } from "../lib/format";
import {
  FRESHNESS_STATUS_LABELS,
  labelOf,
  MONTH_STATUS_LABELS,
  SOURCE_LABELS,
  SOURCE_TIMESTAMP_KIND_LABELS,
} from "../lib/labels";

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year));
}

function statusTone(status: FreshnessStatus): "ok" | "stale" | "unknown" | "missing" | "info" {
  if (status === "current") return "ok";
  if (status === "stale" || status === "mixed") return "stale";
  if (status === "unavailable" || status === "missing") return "missing";
  if (status === "not_applicable") return "info";
  return "unknown";
}

function sourceLabel(value: string): string {
  return labelOf(SOURCE_LABELS, value);
}

function itemHasDetailTable(family: FreshnessFamily): boolean {
  return family.items.some((item) => item.item_kind !== "manual_group");
}

function clockValue(item: FreshnessItem): string {
  if (item.source_date) return formatDate(item.source_date);
  if (item.source_datetime) return formatDateTime(item.source_datetime);
  return "—";
}

export function FreshnessProvenancePage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [summary, setSummary] = useState<FreshnessProvenanceSummary | null>(null);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setMonthsLoading(true);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        const sorted = sortMonths(rows);
        setMonths(sorted);
        setSelectedMonthId((previous) =>
          previous != null && sorted.some((month) => month.id === previous)
            ? previous
            : (sorted[0]?.id ?? null),
        );
        setMonthsError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMonths([]);
          setSelectedMonthId(null);
          setMonthsError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMonthsLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (selectedMonthId == null) {
      setSummary(null);
      setSummaryError(null);
      setSummaryLoading(false);
      return;
    }
    const controller = new AbortController();
    setSummaryLoading(true);
    void getFreshnessProvenance(selectedMonthId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setSummary(data);
        setSummaryError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setSummary(null);
          setSummaryError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setSummaryLoading(false);
      });
    return () => controller.abort();
  }, [selectedMonthId]);

  const warnings = useMemo(
    () => (summary?.reasons ?? []).filter((reason) => reason.severity === "warning"),
    [summary],
  );

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Обзор</p>
        <h1>Актуальность данных</h1>
        <p className="page-header__description">
          Один экран: что сейчас актуально, что устарело, чего нет и что ведётся вручную. Это не
          общий процент свежести — семьи данных считаются по своим правилам.
        </p>
      </header>

      <Panel label="Отчётный месяц" title="Какой срез смотрим">
        {monthsLoading ? (
          <LoadingState description="Загружаем месяцы…" inline />
        ) : monthsError ? (
          <ErrorState description={monthsError} inline title="Не удалось загрузить месяцы" />
        ) : months.length === 0 ? (
          <EmptyState
            description="Сначала создай хотя бы один отчётный месяц."
            inline
            title="Нет месяцев"
          />
        ) : (
          <Field htmlFor="freshness-month" label="Месяц">
            <Select
              id="freshness-month"
              onChange={(event) => setSelectedMonthId(Number(event.target.value))}
              value={selectedMonthId ?? ""}
            >
              {months.map((month) => (
                <option key={month.id} value={month.id}>
                  {formatMonth(month.year, month.month)} ·{" "}
                  {labelOf(MONTH_STATUS_LABELS, month.status)}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </Panel>

      {summaryLoading ? (
        <LoadingState description="Собираем provenance…" />
      ) : summaryError ? (
        <ErrorState description={summaryError} title="Не удалось загрузить актуальность" />
      ) : summary ? (
        <>
          <Panel
            action={
              <HelpTip label="Четыре разных часов">
                Дата отчётного месяца не равна времени наблюдения провайдера и не равна времени
                apply. Ручное значение без timestamp провайдера не считается устаревшим.
              </HelpTip>
            }
            label="Часы"
            title="Не смешивать эти даты"
          >
            <div className="freshness-clocks">
              <DataValue
                label="Отчётный месяц"
                meta="срез учёта, не наблюдение"
                value={formatMonth(summary.reporting_month.year, summary.reporting_month.month)}
              />
              <DataValue
                label="Дата снимка месяца"
                meta="snapshot_date"
                value={formatDate(summary.reporting_month.snapshot_date)}
              />
              <DataValue
                label="Дата оценки котировок"
                meta="min(снимок, сегодня)"
                value={formatDate(summary.quote_valuation_target_date)}
              />
              <DataValue
                label="Сегодня для оценки"
                meta="не финансовое наблюдение"
                value={formatDate(summary.evaluated_on)}
              />
            </div>
          </Panel>

          {warnings.length > 0 ? (
            <Panel label="Предупреждения" title="Что стоит посмотреть">
              <ul className="freshness-reason-list">
                {warnings.map((reason) => (
                  <li key={reason.code}>{reason.message}</li>
                ))}
              </ul>
            </Panel>
          ) : null}

          {summary.families.map((family) => (
            <Panel
              key={family.family_id}
              action={
                <Badge tone={statusTone(family.status)}>
                  {labelOf(FRESHNESS_STATUS_LABELS, family.status)}
                </Badge>
              }
              label={family.providers.map(sourceLabel).join(" · ") || "Локальные данные"}
              title={family.title}
            >
              <p className="freshness-family__counts">
                Строк: {family.coverage.row_count}
                {family.coverage.current_count
                  ? ` · актуальных: ${family.coverage.current_count}`
                  : ""}
                {family.coverage.stale_count ? ` · устаревших: ${family.coverage.stale_count}` : ""}
                {family.coverage.manual_count ? ` · ручных: ${family.coverage.manual_count}` : ""}
                {family.coverage.missing_count
                  ? ` · без apply: ${family.coverage.missing_count}`
                  : ""}
              </p>
              {family.reasons.length > 0 ? (
                <ul className="freshness-reason-list">
                  {family.reasons.map((reason) => (
                    <li key={`${family.family_id}-${reason.code}`}>{reason.message}</li>
                  ))}
                </ul>
              ) : null}
              {family.items.length > 0 && itemHasDetailTable(family) ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Запись</Th>
                      <Th>Статус</Th>
                      <Th>Источник</Th>
                      <Th>Наблюдение / событие</Th>
                      <Th>Запрос к провайдеру</Th>
                      <Th>Apply</Th>
                      <Th>Локальная правка</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {family.items.map((item) => (
                      <tr key={`${family.family_id}-${item.item_kind}-${item.label}`}>
                        <Td>
                          {item.account_name ? `${item.account_name} · ${item.label}` : item.label}
                        </Td>
                        <Td>
                          <Badge tone={statusTone(item.freshness_status)}>
                            {labelOf(FRESHNESS_STATUS_LABELS, item.freshness_status)}
                          </Badge>
                        </Td>
                        <Td>{sourceLabel(item.source_kind)}</Td>
                        <Td>
                          {clockValue(item)}
                          <div className="muted">
                            {labelOf(SOURCE_TIMESTAMP_KIND_LABELS, item.source_timestamp_kind)}
                          </div>
                        </Td>
                        <Td>{formatDateTime(item.fetched_at)}</Td>
                        <Td>{formatDateTime(item.import_apply_time)}</Td>
                        <Td>{formatDateTime(item.local_edit_time)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : null}
              {family.items.length > 0 && !itemHasDetailTable(family) ? (
                <ul className="freshness-reason-list">
                  {family.items.map((item) => (
                    <li key={item.label}>{item.label}</li>
                  ))}
                </ul>
              ) : null}
            </Panel>
          ))}
        </>
      ) : null}
    </section>
  );
}
