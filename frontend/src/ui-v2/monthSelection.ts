import type { GuidedCloseStepId } from "../api/monthCloseWorkflow";
import type { ReportingMonth } from "../api/types";

export function sortReportingMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id);
}

/** Calendar position of a reporting month; used only for ordering, never for money. */
export function reportIndex(month: Pick<ReportingMonth, "year" | "month">): number {
  return month.year * 12 + month.month;
}

/** The single CLOSED report that is the normal Home/Capital context. */
export function latestClosedMonth(months: ReportingMonth[]): ReportingMonth | null {
  return sortReportingMonths(months).find((month) => month.status === "closed") ?? null;
}

/** The newest unfinished month that sits after the latest CLOSED report. */
export function newerDraftMonth(
  months: ReportingMonth[],
  latestClosed: ReportingMonth | null,
): ReportingMonth | null {
  return (
    sortReportingMonths(months).find(
      (month) =>
        month.status === "draft" &&
        (latestClosed === null || reportIndex(month) > reportIndex(latestClosed)),
    ) ?? null
  );
}

export function selectNewestDraftAfterLatestClosed(months: ReportingMonth[]): {
  latestClosed: ReportingMonth | null;
  newestDraft: ReportingMonth | null;
} {
  const sorted = sortReportingMonths(months);
  const latestClosed = sorted.find((month) => month.status === "closed") ?? null;
  const newestDraft =
    sorted.find(
      (month) =>
        month.status === "draft" &&
        (latestClosed === null || reportIndex(month) > reportIndex(latestClosed)),
    ) ?? null;
  return { latestClosed, newestDraft };
}

type MonthSelection =
  | { kind: "automatic" }
  | { kind: "invalid" }
  | { kind: "missing" }
  | { kind: "selected"; month: ReportingMonth };

export function resolveMonthSelection(values: string[], months: ReportingMonth[]): MonthSelection {
  if (values.length === 0) return { kind: "automatic" };
  if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) return { kind: "invalid" };
  const id = Number(values[0]);
  if (!Number.isSafeInteger(id)) return { kind: "invalid" };
  const month = months.find((item) => item.id === id);
  return month ? { kind: "selected", month } : { kind: "missing" };
}

export function monthWorkspacePath(monthId: number, step?: GuidedCloseStepId): string {
  const params = new URLSearchParams({ month: String(monthId) });
  if (step) params.set("step", step);
  return `/v2/close?${params.toString()}`;
}

/**
 * Shared active-work selector for Data/App diagnostics:
 * newest DRAFT when one exists, otherwise latest CLOSED.
 */
export function selectDiagnosticMonth(months: ReportingMonth[]): ReportingMonth | null {
  const sorted = sortReportingMonths(months);
  const newestDraft = sorted.find((month) => month.status === "draft");
  if (newestDraft) return newestDraft;
  return sorted.find((month) => month.status === "closed") ?? null;
}

export type DataAppSection = "sources" | "reconciliation" | "catalogs" | "files" | "app";

export function dataAppPath(
  section: DataAppSection,
  monthId?: number,
  search = "",
  hash = "",
): string {
  const base =
    section === "sources"
      ? "/v2/data"
      : section === "reconciliation"
        ? "/v2/data/reconciliation"
        : section === "catalogs"
          ? "/v2/data/catalogs"
          : section === "files"
            ? "/v2/data/files"
            : "/v2/data/app";
  const params = new URLSearchParams(search);
  if (monthId != null && !params.has("month")) params.set("month", String(monthId));
  const query = params.toString();
  return `${base}${query ? `?${query}` : ""}${hash}`;
}
