import { IncomeTabs } from "./IncomeTabs";
import type { ReactNode } from "react";
import { useLocation } from "react-router";

import type { ReportingMonth } from "../api/types";
import { formatDate, formatMonth } from "../lib/format";
import {
  type DataAppSection,
  dataAppPath,
  resolveMonthSelection,
  selectDiagnosticMonth,
} from "./monthSelection";
import styles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { UiV2Tabs } from "./UiV2Tabs";

const SETTINGS_SECTIONS: Array<{ id: DataAppSection; label: string }> = [
  { id: "overview", label: "Обзор" },
  { id: "catalogs", label: "Счета и инструменты" },
  { id: "sources", label: "Источники данных" },
  { id: "files", label: "Экспорт и копии" },
  { id: "app", label: "Приложение" },
];

export type DataMonthResolution =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "invalid" }
  | { kind: "missing" }
  | { kind: "ready"; month: ReportingMonth; automatic: boolean };

export function resolveDataMonth(
  monthParams: string[],
  months: ReportingMonth[],
  monthsReady: boolean,
): DataMonthResolution {
  if (!monthsReady) return { kind: "loading" };
  const selection = resolveMonthSelection(monthParams, months);
  if (selection.kind === "invalid") return { kind: "invalid" };
  if (selection.kind === "missing") return { kind: "missing" };
  if (selection.kind === "selected") {
    return { kind: "ready", month: selection.month, automatic: false };
  }
  const diagnostic = selectDiagnosticMonth(months);
  if (!diagnostic) return { kind: "empty" };
  return { kind: "ready", month: diagnostic, automatic: true };
}

export function UiV2DataSubnav({ active, monthId }: { active: DataAppSection; monthId?: number }) {
  const location = useLocation();
  return (
    <UiV2Tabs
      inheritMonth={false}
      label="Разделы настроек"
      tabs={SETTINGS_SECTIONS.map((section) => ({
        label: section.label,
        active: active === section.id || (active === "source-intake" && section.id === "app"),
        to: dataAppPath(section.id, monthId, location.search, location.hash),
      }))}
    />
  );
}

export function UiV2DataFrame({
  active,
  busy = false,
  children,
  monthId,
  subtitle,
  title,
}: {
  active: DataAppSection;
  busy?: boolean;
  children: ReactNode;
  monthId?: number;
  subtitle: string;
  title: string;
}) {
  return (
    <UiV2Shell
      showRefresh={active !== "app" && active !== "payouts"}
      active={active === "payouts" ? "income" : "data"}
      busy={busy}
      header={
        <>
          <p className={styles.eyebrow}>{active === "payouts" ? "Доход и планы" : "Настройки"}</p>
          <h1>{title}</h1>
          <p className={styles.subtitle}>{subtitle}</p>
        </>
      }
    >
      {active === "payouts" ? (
        <IncomeTabs active="payouts" monthId={monthId} />
      ) : (
        <UiV2DataSubnav active={active} monthId={monthId} />
      )}
      {children}
    </UiV2Shell>
  );
}

export function DataMonthContext({
  month,
  automatic,
  children,
}: {
  month: ReportingMonth;
  automatic: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={styles.reportContext} data-testid="data-month-context">
      <span className={styles.closedBadge}>
        {month.status === "draft" ? "Черновик" : "Закрытый отчёт"}
      </span>
      <span>{formatMonth(month.year, month.month)}</span>
      <span className={styles.contextDivider} aria-hidden="true">
        ·
      </span>
      <span>Снимок {formatDate(month.snapshot_date)}</span>
      {automatic ? (
        <>
          <span className={styles.contextDivider} aria-hidden="true">
            ·
          </span>
          <span>месяц выбран автоматически</span>
        </>
      ) : null}
      {children}
    </div>
  );
}
