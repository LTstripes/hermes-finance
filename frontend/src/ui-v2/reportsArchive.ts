import type { CapitalCompositionPoint, ReportingMonth } from "../api/types";
import { MONTH_STATUS_LABELS } from "../lib/labels";
import { latestClosedMonth, newerDraftMonth, sortReportingMonths } from "./monthSelection";

/**
 * Read-only model of the contextual report archive.
 *
 * Pure presentation mapping over two already-cached read models:
 * `/api/months` (status, calendar positions) and
 * `/api/analytics/capital-composition` (canonical closed-report money).
 * No money is computed, interpolated or substituted here.
 */

export const REPORTS_PATH = "/v2/reports";

export function reportPath(monthId: number): string {
  return `${REPORTS_PATH}/${monthId}`;
}

/** Archive row vocabulary (frozen). */
export const GAP_ROW_LABEL = "отчёта нет";
export const CURRENT_ROW_STATUS = "Текущий отчёт";
export const CURRENT_ROW_ACTION = "Открыть в «Мои финансы»";
export const OLDER_ROW_ACTION = "Открыть отчёт";
export const SINGLE_REPORT_NOTE = "История появится после второго закрытого отчёта.";

/** No arbitrary historical pair has a canonical change read model (#423 §8.3). */
export const NO_HISTORICAL_CHANGE_TEXT =
  "Изменение между отчётами показывается только для двух последних закрытых отчётов.";

/** Always-visible methodology note; historical values are not frozen as of the original close. */
export const CURRENT_METHODOLOGY_CAVEAT =
  "Значения рассчитаны по данным этого отчёта текущей подтверждённой методикой. Поздние цены, остатки и позиции никогда не подставляются в прошлый отчёт.";

export const CURRENT_METHODOLOGY_ARCHIVE_NOTE =
  "Значения показаны по данным каждого отчёта текущей подтверждённой методикой; поздние цены и остатки в прошлые отчёты не подставляются.";

export type ArchiveGapRow = {
  kind: "gap";
  key: string;
  year: number;
  month: number;
};

export type ArchiveReportRow = {
  kind: "report";
  key: string;
  month: ReportingMonth;
  /** Canonical composition point of that month; null while money is not confirmed. */
  point: CapitalCompositionPoint | null;
  isCurrent: boolean;
  statusLabel: string;
  actionLabel: string;
  actionPath: string;
};

export type ArchiveRow = ArchiveGapRow | ArchiveReportRow;

export type ArchiveGroup = {
  year: number;
  rows: ArchiveRow[];
};

export type ArchiveModel = {
  closedCount: number;
  groups: ArchiveGroup[];
  latestClosed: ReportingMonth | null;
  newerDraft: ReportingMonth | null;
  singleReportNote: string | null;
};

function reportRow(
  month: ReportingMonth,
  latestClosedId: number | null,
  point: CapitalCompositionPoint | null,
): ArchiveReportRow {
  const isCurrent = latestClosedId !== null && month.id === latestClosedId;
  return {
    kind: "report",
    key: `report-${month.id}`,
    month,
    point,
    isCurrent,
    statusLabel: isCurrent
      ? CURRENT_ROW_STATUS
      : (MONTH_STATUS_LABELS[month.status] ?? month.status),
    actionLabel: isCurrent ? CURRENT_ROW_ACTION : OLDER_ROW_ACTION,
    actionPath: isCurrent ? "/v2" : reportPath(month.id),
  };
}

/**
 * Build the archive: CLOSED reports grouped by year, newest first.
 *
 * `отчёта нет` markers are strictly between the earliest and the latest CLOSED
 * report of the same year group: never before the first, never after the latest,
 * never a zero, never a draft. Drafts are never rows.
 */
export function buildArchive({
  months,
  points,
  moneyConfirmed,
}: {
  months: ReportingMonth[];
  points: CapitalCompositionPoint[];
  /** Identity guard result: the composition series is confirmed for this month set. */
  moneyConfirmed: boolean;
}): ArchiveModel {
  const sorted = sortReportingMonths(months);
  const closed = sorted.filter((month) => month.status === "closed");
  const latestClosed = latestClosedMonth(months);
  const latestClosedId = latestClosed?.id ?? null;
  const pointById = new Map(points.map((point) => [point.reporting_month_id, point]));
  const years = [...new Set(closed.map((month) => month.year))].sort((a, b) => b - a);

  const groups: ArchiveGroup[] = years.map((year) => {
    const yearMonths = closed.filter((month) => month.year === year);
    const earliest = Math.min(...yearMonths.map((month) => month.month));
    const newest = Math.max(...yearMonths.map((month) => month.month));
    const rows: ArchiveRow[] = [];
    for (let month = newest; month >= earliest; month -= 1) {
      const closedMonth = yearMonths.find((candidate) => candidate.month === month);
      if (closedMonth) {
        rows.push(
          reportRow(
            closedMonth,
            latestClosedId,
            moneyConfirmed ? (pointById.get(closedMonth.id) ?? null) : null,
          ),
        );
        continue;
      }
      rows.push({ kind: "gap", key: `gap-${year}-${month}`, year, month });
    }
    return { year, rows };
  });

  return {
    closedCount: closed.length,
    groups,
    latestClosed,
    newerDraft: newerDraftMonth(months, latestClosed),
    singleReportNote: closed.length === 1 ? SINGLE_REPORT_NOTE : null,
  };
}

export type ReportTargetKind = "malformed" | "missing" | "draft" | "current" | "older";

export type ReportTarget =
  | { kind: "malformed"; month: null }
  | { kind: "missing"; month: null }
  | { kind: "draft"; month: ReportingMonth }
  | { kind: "current"; month: ReportingMonth }
  | { kind: "older"; month: ReportingMonth };

/**
 * Classify the `/v2/reports/{monthId}` route parameter against the month list.
 *
 * The id regex is the accepted `resolveMonthSelection` one; the month status
 * decides the state: only an older CLOSED report is a historical report.
 */
export function resolveReportTarget(
  idValue: string | undefined,
  months: ReportingMonth[],
): ReportTarget {
  if (idValue === undefined || !/^[1-9]\d*$/.test(idValue)) {
    return { kind: "malformed", month: null };
  }
  const id = Number(idValue);
  if (!Number.isSafeInteger(id)) return { kind: "malformed", month: null };
  const month = months.find((item) => item.id === id);
  if (!month) return { kind: "missing", month: null };
  if (month.status !== "closed") return { kind: "draft", month };
  const latestClosed = latestClosedMonth(months);
  if (latestClosed !== null && latestClosed.id === month.id) return { kind: "current", month };
  return { kind: "older", month };
}

export type SeriesPosition = {
  point: CapitalCompositionPoint;
  previous: CapitalCompositionPoint | null;
  next: CapitalCompositionPoint | null;
};

/** Previous/next CLOSED neighbour of a point in the canonical series order. */
export function seriesPosition(
  points: CapitalCompositionPoint[],
  monthId: number,
): SeriesPosition | null {
  const index = points.findIndex((point) => point.reporting_month_id === monthId);
  if (index < 0) return null;
  return {
    point: points[index],
    previous: points[index - 1] ?? null,
    next: points[index + 1] ?? null,
  };
}
