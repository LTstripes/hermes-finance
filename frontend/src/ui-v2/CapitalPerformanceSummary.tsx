import { Link } from "react-router";

import type {
  PerformanceAttribution,
  PerformanceReadiness,
  PerformanceReadinessDiagnostic,
} from "../api/types";
import { formatDate, formatPercent } from "../lib/format";
import {
  performanceAttributionUnavailableMessage,
  VALUE_BRIDGE_DISCLAIMER,
  VALUE_BRIDGE_LABEL,
} from "../lib/performanceMessages";
import {
  intervalDays,
  isZeroPercent,
  needsAnnualizationWarning,
} from "./capitalPerformanceContext";
import { capabilityCopy, diagnosticCopy, hasWorkingAction } from "./capitalPerformanceCopy";
import styles from "./UiV2CapitalPerformance.module.css";
import { UiV2WidgetState } from "./UiV2StateBlocks";
import { moneyDeltaText as moneyDelta } from "./valueFormat";

/** Presentation order only (contract priority); never gates availability. */
const DIAGNOSTIC_PRIORITY: Record<string, number> = {
  excluded_source: 0,
  opening_valuation: 10,
  closing_valuation: 10,
  reporting_month: 20,
  snapshot_date: 20,
  position_valuation: 20,
  membership_history: 30,
  membership_changed: 30,
  cash_binding: 30,
  scope_coverage: 30,
  external_flows: 40,
  no_recorded_external_flows: 40,
  cash_history: 40,
  legacy_flows: 40,
  transfer_identity: 40,
  transfer_reconciliation: 40,
  transfer_in_transit: 40,
  in_kind_history: 40,
  in_kind_valuation: 40,
  valuation_boundary: 50,
  valuation_order: 50,
  historical_fx: 50,
  xirr_no_root: 60,
  xirr_ambiguous: 60,
  xirr_convergence: 60,
  unknown_reason: 70,
};

export function sortDiagnostics(
  diagnostics: PerformanceReadinessDiagnostic[],
): PerformanceReadinessDiagnostic[] {
  return [...diagnostics].sort(
    (a, b) =>
      (DIAGNOSTIC_PRIORITY[a.key] ?? 70) - (DIAGNOSTIC_PRIORITY[b.key] ?? 70) ||
      (a.key < b.key ? -1 : 1),
  );
}

/** Percent display: exact zero without a plus sign, loss with a sign. No float math. */
export function formatPerformancePercent(value: string | null): string | null {
  if (value === null || value.trim() === "") return null;
  if (isZeroPercent(value)) return formatPercent(value, { digits: 2 });
  return formatPercent(value, { digits: 2, signed: true });
}

/** Freshness gate: a response for other scope/account/dates is never shown as current. */
export function isReadinessFresh(
  readiness: PerformanceReadiness | null,
  expected: {
    start: string;
    end: string;
    scope: "portfolio" | "account";
    accountId: number | null;
  },
): readiness is PerformanceReadiness {
  return (
    readiness !== null &&
    readiness.start_date === expected.start &&
    readiness.end_date === expected.end &&
    readiness.scope === expected.scope &&
    readiness.account_id === expected.accountId
  );
}

export type CompactMetricInput = {
  label: string;
  sublabel: string;
  value: string | null;
  ready: boolean;
  requestError: boolean;
  unavailableReason: string | null;
  retry: () => void;
  testId: string;
};

export function CompactMetric({
  label,
  requestError,
  ready,
  retry,
  sublabel,
  testId,
  unavailableReason,
  value,
}: CompactMetricInput) {
  return (
    <article className={styles.metricCard} data-testid={testId}>
      <p className={styles.periodLine}>{label}</p>
      {!ready ? (
        <UiV2WidgetState retry={requestError ? retry : undefined} />
      ) : requestError ? (
        <UiV2WidgetState
          retry={retry}
          title="Проверка не завершилась — это не доказательство неполноты данных."
        />
      ) : value !== null ? (
        <>
          <p className={styles.metricValue}>{value}</p>
          <p className={styles.metricNote}>{sublabel}</p>
        </>
      ) : (
        <p className={styles.metricNote}>
          {unavailableReason ??
            "Не удалось получить подтверждённый результат для выбранного периода."}
        </p>
      )}
    </article>
  );
}

export function DiagnosticList({
  diagnostics,
  expanded,
}: {
  diagnostics: PerformanceReadinessDiagnostic[];
  expanded: boolean;
}) {
  const ordered = sortDiagnostics(diagnostics);
  const visible = expanded ? ordered : ordered.slice(0, 2);
  return (
    <div>
      <ul className={styles.diagnosticList}>
        {visible.map((diagnostic) => {
          const copy = diagnosticCopy(diagnostic.key);
          const metrics = diagnostic.affected_metrics.join("/").toUpperCase();
          return (
            <li className={styles.diagnosticItem} key={`${diagnostic.key}-${metrics}`}>
              <strong>
                {copy.title} · {metrics}
              </strong>
              <p>{copy.detail}</p>
              <p className={styles.capabilityNote}>
                {capabilityCopy(diagnostic.action.capability)}
              </p>
              {hasWorkingAction(diagnostic.action.capability) ? (
                <p className={styles.capabilityNote}>Проверка — в деталях доходности.</p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {!expanded && ordered.length > 2 ? (
        <p className={styles.capabilityNote}>
          Показаны 2 приоритетные причины из {ordered.length}. Все причины — в деталях.
        </p>
      ) : null}
    </div>
  );
}

export type CapitalPerformanceSummaryProps = {
  attribution: PerformanceAttribution | null;
  attributionReady: boolean;
  attributionError: boolean;
  detailHref: string;
  pairStart: string;
  pairEnd: string;
  readiness: PerformanceReadiness | null;
  readinessError: boolean;
  readinessReady: boolean;
  retry: () => void;
};

/**
 * Compact portfolio summary: period TWRR, annualized XIRR, state/next action.
 * Numbers come only from the fresh coherent readiness projection. A stale,
 * failed or missing readiness read hides both metrics and retries the same
 * coherent read — legacy XIRR/TWRR endpoints are never a financial fallback.
 * Diagnostics come only from the capability-driven projection.
 */
export function CapitalPerformanceSummary({
  attribution,
  attributionError,
  attributionReady,
  detailHref,
  pairEnd,
  pairStart,
  readiness,
  readinessError,
  readinessReady,
  retry,
}: CapitalPerformanceSummaryProps) {
  const fresh = isReadinessFresh(readiness, {
    start: pairStart,
    end: pairEnd,
    scope: "portfolio",
    accountId: null,
  });
  const effective = fresh && readinessReady ? readiness : null;
  // Stale identity or a transport failure: no percentage may be shown as current.
  const failed = readinessError || (readiness !== null && readinessReady && !fresh);
  const loading = !failed && effective === null;

  const xirrMetric = effective?.xirr ?? null;
  const twrrMetric = effective?.twrr ?? null;

  const xirrValue =
    xirrMetric?.availability === "available" &&
    xirrMetric.quality === "exact" &&
    xirrMetric.value !== null
      ? formatPerformancePercent(xirrMetric.value)
      : null;
  const twrrValue =
    twrrMetric?.availability === "available" &&
    twrrMetric.quality === "exact" &&
    twrrMetric.value !== null
      ? formatPerformancePercent(twrrMetric.value)
      : null;

  const xirrDiagnostics = (effective?.diagnostics ?? []).filter((d) =>
    d.affected_metrics.includes("xirr"),
  );
  const twrrDiagnostics = (effective?.diagnostics ?? []).filter((d) =>
    d.affected_metrics.includes("twrr"),
  );
  const xirrReason =
    xirrDiagnostics.length > 0
      ? diagnosticCopy(sortDiagnostics(xirrDiagnostics)[0].key).title
      : null;
  const twrrReason =
    twrrDiagnostics.length > 0
      ? diagnosticCopy(sortDiagnostics(twrrDiagnostics)[0].key).title
      : null;

  const diagnostics = effective?.diagnostics ?? [];
  const days = intervalDays(pairStart, pairEnd);
  const showAnnualizationWarning = needsAnnualizationWarning(pairStart, pairEnd);
  const currency = effective?.performance_currency ?? null;
  const period = `${formatDate(pairStart)} — ${formatDate(pairEnd)}`;

  const bridgeValue =
    attribution &&
    attribution.availability === "available" &&
    attribution.quality === "exact" &&
    attribution.value !== null
      ? moneyDelta(attribution.value)
      : null;

  return (
    <div className={styles.summary}>
      <p className={styles.periodLine} data-testid="capital-performance-period">
        {period}
        {currency ? ` · ${currency}` : ""}
        {days !== null ? ` · ${days} дн.` : ""} · единицы: п.п.
      </p>
      <div className={styles.metricGrid}>
        <CompactMetric
          label="Доходность ваших вложений · XIRR, годовых"
          requestError={failed}
          ready={!loading}
          retry={retry}
          sublabel={period}
          testId="capital-performance-xirr"
          unavailableReason={xirrReason}
          value={xirrValue}
        />
        <CompactMetric
          label="Доходность за период · TWRR"
          requestError={failed}
          ready={!loading}
          retry={retry}
          sublabel={period}
          testId="capital-performance-twrr"
          unavailableReason={twrrReason}
          value={twrrValue}
        />
      </div>
      {showAnnualizationWarning && xirrValue !== null ? (
        <p className={styles.warning}>XIRR приведён к году по короткому периоду; это не прогноз.</p>
      ) : null}
      {failed ? (
        <p className={styles.stateLine}>
          Проверка готовности не завершилась — прошлый процент как текущий не показывается.{" "}
          <button className={styles.inlineButton} onClick={retry} type="button">
            Повторить
          </button>
        </p>
      ) : loading ? (
        <p className={styles.stateLine}>Проверяем готовность расчёта…</p>
      ) : diagnostics.length > 0 ? (
        <>
          <p className={styles.stateLine}>
            Состояние: {diagnosticCopy(sortDiagnostics(diagnostics)[0].key).title}. Следующее
            действие — проверить данные.
          </p>
          <DiagnosticList diagnostics={diagnostics} expanded={false} />
        </>
      ) : (
        <p className={styles.stateLine}>Состояние: расчёт подтверждён за выбранный период.</p>
      )}
      <div className={styles.actionRow}>
        <Link className={styles.linkButton} to={detailHref}>
          {diagnostics.length > 0 ? "Проверить данные" : "Подробнее"}
        </Link>
      </div>
      <details className={styles.bridgeBox}>
        <summary>Изменение стоимости после внешних потоков (вторично)</summary>
        <article data-testid="capital-performance-bridge">
          {!attributionReady ? (
            <UiV2WidgetState retry={attributionError ? retry : undefined} />
          ) : bridgeValue !== null ? (
            <>
              <p className={styles.metricValue}>{bridgeValue}</p>
              <p className={styles.metricNote}>
                {VALUE_BRIDGE_LABEL} · {VALUE_BRIDGE_DISCLAIMER} Не прибыль и не доходность.
              </p>
            </>
          ) : (
            <p className={styles.metricNote}>
              {attribution
                ? performanceAttributionUnavailableMessage(attribution.reason_codes)
                : "Не удалось получить подтверждённый результат для выбранного периода."}
            </p>
          )}
        </article>
      </details>
    </div>
  );
}
