import { Link } from "react-router";

import type { ProviderCapabilities } from "../api/providerCapabilities";
import type {
  FreshnessFamily,
  FreshnessItem,
  FreshnessProvenanceSummary,
  FreshnessStatus,
  ReportingMonth,
} from "../api/types";
import type { GuidedCloseStepId } from "../api/monthCloseWorkflow";
import { monthlyCloseReturnPath } from "../components/month-close/navigation";
import { formatDate, formatDateTime, formatMonth } from "../lib/format";
import {
  FRESHNESS_STATUS_LABELS,
  labelOf,
  MONTH_STATUS_LABELS,
  SOURCE_LABELS,
  SOURCE_TIMESTAMP_KIND_LABELS,
} from "../lib/labels";
import dataStyles from "./UiV2Data.module.css";

const FAMILY_CLOSE_STEP: Record<string, GuidedCloseStepId | null> = {
  market_quotes: "market_quotes",
  alfa_pro_positions: "alfa_baseline",
  t_invest_payouts: "actual_payouts",
  alfa_statement_payouts: "actual_payouts",
  manual_month_data: null,
  deposit_cash_snapshots: null,
};

function statusTone(status: FreshnessStatus): string {
  if (status === "current") return "ok";
  if (status === "stale" || status === "mixed") return "stale";
  if (status === "unavailable" || status === "missing") return "missing";
  if (status === "not_applicable") return "info";
  return "unknown";
}

function sourceLabel(value: string): string {
  return SOURCE_LABELS[value] ?? "внешний источник";
}

function clockValue(item: FreshnessItem): string {
  if (item.source_date) return formatDate(item.source_date);
  if (item.source_datetime) return formatDateTime(item.source_datetime);
  return "—";
}

function itemHasDetailTable(family: FreshnessFamily): boolean {
  return family.items.some((item) => item.item_kind !== "manual_group");
}

export function FreshnessBody({
  monthId,
  summary,
}: {
  monthId: number;
  summary: FreshnessProvenanceSummary;
}) {
  const warnings = summary.reasons.filter((reason) => reason.severity === "warning");
  return (
    <>
      <dl className={dataStyles.clocks} data-testid="freshness-clocks">
        <div className={dataStyles.clock}>
          <dt>Отчётный месяц</dt>
          <dd>{formatMonth(summary.reporting_month.year, summary.reporting_month.month)}</dd>
          <span className={dataStyles.meta}>срез учёта, не наблюдение</span>
        </div>
        <div className={dataStyles.clock}>
          <dt>Дата снимка месяца</dt>
          <dd>{formatDate(summary.reporting_month.snapshot_date)}</dd>
          <span className={dataStyles.meta}>дата снимка</span>
        </div>
        <div className={dataStyles.clock}>
          <dt>Дата оценки котировок</dt>
          <dd>{formatDate(summary.quote_valuation_target_date)}</dd>
          <span className={dataStyles.meta}>ближайшая дата: снимок или сегодня</span>
        </div>
        <div className={dataStyles.clock}>
          <dt>Сегодня для оценки</dt>
          <dd>{formatDate(summary.evaluated_on)}</dd>
          <span className={dataStyles.meta}>не финансовое наблюдение</span>
        </div>
      </dl>
      {warnings.length > 0 ? (
        <section className={dataStyles.resultPanel}>
          <h2>Предупреждения</h2>
          <ul className={dataStyles.reasonList}>
            {warnings.map((reason) => (
              <li key={reason.code}>{reason.message}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <div className={dataStyles.familyList}>
        {summary.families.map((family) => (
          <FamilyCard family={family} key={family.family_id} monthId={monthId} />
        ))}
      </div>
    </>
  );
}

export function MonthToolbar({
  months,
  selected,
  onSelect,
}: {
  months: ReportingMonth[];
  selected: ReportingMonth;
  onSelect: (id: number) => void;
}) {
  return (
    <div className={dataStyles.toolbar}>
      <div className={dataStyles.field}>
        <label htmlFor="data-sources-month">Отчётный месяц</label>
        <select
          id="data-sources-month"
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
      <p className={dataStyles.hint}>
        Диагностика по выбранному месяцу. Явно неверный месяц скрывает числа.
      </p>
    </div>
  );
}

export function CapabilitiesDisclosure({
  profiles,
  ready,
  failed = false,
  retry,
}: {
  profiles: ProviderCapabilities[] | undefined;
  ready: boolean;
  failed?: boolean;
  retry: () => void;
}) {
  return (
    <details className={dataStyles.disclosure} data-testid="provider-capabilities">
      <summary>Технические сведения об источнике</summary>
      {!ready ? (
        failed ? (
          <p className={dataStyles.muted}>
            Не удалось загрузить профили возможностей.{" "}
            <button className={dataStyles.secondaryButton} onClick={retry} type="button">
              Повторить
            </button>
          </p>
        ) : (
          <p className={dataStyles.muted}>Загружаем профили возможностей…</p>
        )
      ) : profiles && profiles.length > 0 ? (
        <div className={dataStyles.capabilityList}>
          {profiles.map((profile) => (
            <article className={dataStyles.capabilityCard} key={profile.provider}>
              <h4>{sourceLabel(profile.provider)}</h4>
              <p>
                Инструменты:{" "}
                {profile.supported_instrument_types.length > 0
                  ? profile.supported_instrument_types.join(", ")
                  : "—"}
              </p>
              <ul>
                {profile.capabilities.map((capability) => (
                  <li key={capability.name}>
                    {capability.name}: {capability.status}
                    {capability.limitations.length > 0
                      ? ` · ${capability.limitations.join("; ")}`
                      : ""}
                  </li>
                ))}
              </ul>
              {profile.limitations.length > 0 ? (
                <p>Ограничения: {profile.limitations.join("; ")}</p>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className={dataStyles.muted}>Профили возможностей пока не объявлены.</p>
      )}
    </details>
  );
}

function FamilyCard({ family, monthId }: { family: FreshnessFamily; monthId: number }) {
  const step = FAMILY_CLOSE_STEP[family.family_id] ?? null;
  return (
    <article className={dataStyles.family} data-testid={`freshness-family-${family.family_id}`}>
      <div className={dataStyles.familyHeader}>
        <div>
          <p className={dataStyles.familyMeta}>
            {family.providers.map(sourceLabel).join(" · ") || "Локальные данные"}
          </p>
          <h3>{family.title}</h3>
        </div>
        <span className={dataStyles.statusBadge} data-tone={statusTone(family.status)}>
          {labelOf(FRESHNESS_STATUS_LABELS, family.status)}
        </span>
      </div>
      <p className={dataStyles.familyMeta}>
        Строк: {family.coverage.row_count}
        {family.coverage.current_count ? ` · актуальных: ${family.coverage.current_count}` : ""}
        {family.coverage.stale_count ? ` · устаревших: ${family.coverage.stale_count}` : ""}
        {family.coverage.manual_count ? ` · ручных: ${family.coverage.manual_count}` : ""}
        {family.coverage.missing_count ? ` · без применения: ${family.coverage.missing_count}` : ""}
      </p>
      {family.reasons.length > 0 ? (
        <ul className={dataStyles.reasonList}>
          {family.reasons.map((reason) => (
            <li key={`${family.family_id}-${reason.code}`}>{reason.message}</li>
          ))}
        </ul>
      ) : null}
      {family.items.length > 0 && itemHasDetailTable(family) ? (
        <details className={dataStyles.disclosure}>
          <summary>Показать записи</summary>
          <div className={dataStyles.provenance}>
            <table>
              <thead>
                <tr>
                  <th>Запись</th>
                  <th>Статус</th>
                  <th>Источник</th>
                  <th>Наблюдение</th>
                  <th>Запрос</th>
                  <th>Применение</th>
                  <th>Правка</th>
                </tr>
              </thead>
              <tbody>
                {family.items.map((item) => (
                  <tr key={`${family.family_id}-${item.item_kind}-${item.label}`}>
                    <td>
                      {item.account_name ? `${item.account_name} · ${item.label}` : item.label}
                    </td>
                    <td>
                      <span
                        className={dataStyles.statusBadge}
                        data-tone={statusTone(item.freshness_status)}
                      >
                        {labelOf(FRESHNESS_STATUS_LABELS, item.freshness_status)}
                      </span>
                    </td>
                    <td>{sourceLabel(item.source_kind)}</td>
                    <td>
                      {clockValue(item)}
                      <div className={dataStyles.muted}>
                        {labelOf(SOURCE_TIMESTAMP_KIND_LABELS, item.source_timestamp_kind)}
                      </div>
                    </td>
                    <td>{formatDateTime(item.fetched_at)}</td>
                    <td>{formatDateTime(item.import_apply_time)}</td>
                    <td>{formatDateTime(item.local_edit_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      {family.items.length > 0 && !itemHasDetailTable(family) ? (
        <ul className={dataStyles.reasonList}>
          {family.items.map((item) => (
            <li key={item.label}>{item.label}</li>
          ))}
        </ul>
      ) : null}
      <div className={dataStyles.familyActions}>
        {step ? (
          <Link to={monthlyCloseReturnPath({ monthId, origin: "monthly-close", step })}>
            Открыть шаг закрытия →
          </Link>
        ) : (
          <span className={dataStyles.muted}>Обновление — вручную в редакторе месяца</span>
        )}
      </div>
    </article>
  );
}
