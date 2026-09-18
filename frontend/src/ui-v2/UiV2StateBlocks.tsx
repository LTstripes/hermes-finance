import type { ReactNode } from "react";
import { Link } from "react-router";

import type { ReportingMonth } from "../api/types";
import { formatDate, formatMonth } from "../lib/format";
import styles from "./UiV2Page.module.css";

/** A read model counts as confirmed only when it is settled and not paused. */
export function isQueryReady(query: {
  isPending: boolean;
  isFetching: boolean;
  isError: boolean;
  fetchStatus: string;
}): boolean {
  return !query.isPending && !query.isFetching && !query.isError && query.fetchStatus !== "paused";
}

export function UiV2Notice({
  title,
  children,
  retry,
}: {
  title: string;
  children: ReactNode;
  retry?: () => void;
}) {
  return (
    <section className={styles.notice} role={retry ? "alert" : undefined}>
      <h2>{title}</h2>
      <p>{children}</p>
      {retry ? (
        <button className={styles.secondaryButton} onClick={retry} type="button">
          Повторить
        </button>
      ) : null}
    </section>
  );
}

export function UiV2WidgetState({
  title = "Данные временно недоступны",
  retry,
}: {
  title?: string;
  retry?: () => void;
}) {
  return (
    <div className={styles.widgetState} role={retry ? "alert" : "status"}>
      <p>{title}</p>
      {retry ? (
        <button onClick={retry} type="button">
          Повторить
        </button>
      ) : null}
    </div>
  );
}

export function UiV2Loading({ label }: { label: string }) {
  return (
    <p className={styles.loading} role="status">
      {label}
    </p>
  );
}

export function UiV2ReportContext({
  children,
  kind = "current",
  month,
  source,
  status,
}: {
  children?: ReactNode;
  /** `historical` is used only by the historical report route; never for current state. */
  kind?: "current" | "historical";
  month: ReportingMonth;
  source?: string;
  status?: string;
}) {
  return (
    <div className={styles.reportContext} data-context={kind} data-testid="v2-report-context">
      <span className={styles.closedBadge}>
        {kind === "historical" ? "Исторический отчёт" : "Закрытый отчёт"}
      </span>
      {status ? <span className={styles.reportStatus}>{status}</span> : null}
      <span>{formatMonth(month.year, month.month)}</span>
      <span className={styles.contextDivider} aria-hidden="true">
        ·
      </span>
      <span>Снимок {formatDate(month.snapshot_date)}</span>
      {source ? (
        <>
          <span className={styles.contextDivider} aria-hidden="true">
            ·
          </span>
          <span>Источник: {source}</span>
        </>
      ) : null}
      {children}
    </div>
  );
}

export function UiV2BackLink({ to, label }: { to: string; label: string }) {
  return (
    <Link className={styles.contextLink} to={to}>
      {label}
    </Link>
  );
}
