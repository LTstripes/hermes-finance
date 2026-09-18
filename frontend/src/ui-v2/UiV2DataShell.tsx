import type { ReactNode } from "react";
import { Link } from "react-router";

import type { ReportingMonth } from "../api/types";
import { formatDate, formatMonth } from "../lib/format";
import {
  type DataAppSection,
  dataAppPath,
  resolveMonthSelection,
  selectDiagnosticMonth,
} from "./monthSelection";
import dataStyles from "./UiV2Data.module.css";
import styles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";

const READ_SECTIONS: Array<{ id: DataAppSection; label: string }> = [
  { id: "sources", label: "Источники и актуальность" },
  { id: "reconciliation", label: "Сверка портфеля" },
];

const MUTATE_SECTIONS: Array<{ id: DataAppSection; label: string }> = [
  { id: "catalogs", label: "Справочники и сопоставления" },
  { id: "files", label: "Файлы" },
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

function Chip({ active, label, to }: { active: boolean; label: string; to: string }) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`${dataStyles.chip} ${active ? dataStyles.chipActive : ""}`}
      to={to}
    >
      {label}
    </Link>
  );
}

export function UiV2DataSubnav({ active, monthId }: { active: DataAppSection; monthId?: number }) {
  return (
    <nav aria-label="Разделы данных и приложения" className={dataStyles.subnav}>
      <div className={dataStyles.modeGroup}>
        <p className={dataStyles.modeLabel}>
          Проверить · только чтение <span className={dataStyles.modeBadge}>Только чтение</span>
        </p>
        <div className={dataStyles.chips}>
          {READ_SECTIONS.map((section) => (
            <Chip
              active={active === section.id}
              key={section.id}
              label={section.label}
              to={dataAppPath(section.id, monthId)}
            />
          ))}
        </div>
      </div>
      <div className={dataStyles.modeGroup}>
        <p className={dataStyles.modeLabel}>
          Изменить · изменяет данные{" "}
          <span className={`${dataStyles.modeBadge} ${dataStyles.modeBadgeMutate}`}>
            Изменяет данные
          </span>
        </p>
        <div className={dataStyles.chips}>
          {MUTATE_SECTIONS.map((section) => (
            <Chip
              active={active === section.id}
              key={section.id}
              label={section.label}
              to={dataAppPath(section.id, monthId)}
            />
          ))}
        </div>
      </div>
    </nav>
  );
}

export function UiV2DataFrame({
  active,
  busy = false,
  children,
  monthId,
  subtitle,
  title,
  v1ReturnPath,
}: {
  active: DataAppSection;
  busy?: boolean;
  children: ReactNode;
  monthId?: number;
  subtitle: string;
  title: string;
  v1ReturnPath: string;
}) {
  return (
    <UiV2Shell
      active="data"
      busy={busy}
      header={
        <>
          <p className={styles.eyebrow}>Данные и приложение</p>
          <h1>{title}</h1>
          <p className={styles.subtitle}>{subtitle}</p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      <UiV2DataSubnav active={active} monthId={monthId} />
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
