import type { ReactNode } from "react";

import type { ReportingMonth } from "../api/types";
import { formatDate, formatMonth } from "../lib/format";
import styles from "./ReportSheet.module.css";

/**
 * Page title with the closed report it reads, in one line (#1079 stage 4).
 * Replaces the separate "Закрытый отчёт · Месяц · Снимок" row on Income and Capital.
 */
export function ClosedReportTitle({
  title,
  month,
  links,
}: {
  title: string;
  month: ReportingMonth | null;
  links?: ReactNode;
}) {
  return (
    <div className={styles.titleRow}>
      <h1>{title}</h1>
      {month ? (
        <span className={styles.chip} data-context="current" data-testid="v2-report-context">
          <span className={styles.visuallyHidden}>Закрытый отчёт: </span>
          {formatMonth(month.year, month.month)} закрыт · снимок {formatDate(month.snapshot_date)}
        </span>
      ) : null}
      {links ? <span className={styles.titleLinks}>{links}</span> : null}
    </div>
  );
}
