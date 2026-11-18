import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  spendingApi,
  type Coverage,
  type ExpenseType,
  type SpendingHistoryItem,
  type SpendingSource,
} from "../../api/spending";
import type { MoneyValue } from "../../api/types";
import { Button } from "../../components/ui";
import { triggerDownload } from "../../lib/download";
import { formatMonthKey, formatPercent } from "../../lib/format";
import { moneyText } from "../valueFormat";
import { wholeMoneyText } from "../wholeMoney";
import sheet from "../ReportSheet.module.css";
import styles from "./Spending.module.css";

export const spendingPath = "/v2/spending";
export const typeLabels = {
  mandatory: "Обязательные",
  comfortable: "Комфорт",
  other: "Прочие",
} satisfies Record<ExpenseType, string>;
export const typeColors = {
  mandatory: "var(--c-mandatory)",
  comfortable: "var(--c-comfort)",
  other: "var(--c-other)",
};
export const types = ["mandatory", "comfortable", "other"] as const;
export const sourceLabels = {
  alfa: "Альфа",
  cash: "Наличные",
  sber: "Сбер",
  manual_other: "Ручной файл, оплата не указана",
  month_entries: "Записи месяца",
} satisfies Record<SpendingSource, string>;
export const sources = ["alfa", "cash", "sber", "manual_other", "month_entries"] as const;

export function currentMonth(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
export function shiftMonth(month: string, offset: number) {
  const [year, number] = month.split("-").map(Number);
  const index = year * 12 + number - 1 + offset;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}
export function validMonth(month: string) {
  return /^[1-9]\d{3}-(0[1-9]|1[0-2])$/.test(month) && month <= currentMonth();
}
export function monthPath(month: string) {
  return `${spendingPath}?month=${month}`;
}
export function importPath(month: string, review = false) {
  return `${spendingPath}/import?month=${month}${review ? "&review=1" : ""}`;
}
export function shortDate(date?: string | null, year = false) {
  if (!date) return "без даты";
  const [y, m, d] = date.slice(0, 10).split("-");
  return `${d}.${m}${year ? `.${y}` : ""}`;
}
export function rangeText(coverage: Pick<Coverage, "from" | "to">) {
  return coverage.from && coverage.to
    ? `${shortDate(coverage.from)}–${shortDate(coverage.to)}`
    : "";
}
export function coverageLabel(data: SpendingHistoryItem) {
  if (!data.loaded) return "Нет данных";
  if (data.partial)
    return rangeText(data.coverage) ? `Частично: ${rangeText(data.coverage)}` : "Частично";
  if (data.has_manual) return data.has_statement ? "Выписка + ручной файл" : "Только ручной файл";
  return "Только выписка";
}
export function isNonzero(value?: MoneyValue | null) {
  return value != null && /[1-9]/.test(value.amount);
}
export function Money({ value, empty = "—" }: { value?: MoneyValue | null; empty?: string }) {
  return (
    <span
      className={value?.amount.startsWith("-") ? styles.negative : undefined}
      title={value ? moneyText(value) : undefined}
    >
      {wholeMoneyText(value, empty)}
    </span>
  );
}
export function signedPercent(value: string | null, category = false) {
  if (value == null) return "—";
  if (category && /^-?0(?:\.|$)/.test(value)) return "= к среднему";
  return `${value.startsWith("-") ? "▼" : "▲"} ${formatPercent(category ? value.replace(/^-/, "") : value, { signed: !category })}`;
}
export function MonthSelect({
  month,
  onChange,
  disabled,
}: {
  month: string;
  onChange: (month: string) => void;
  disabled?: boolean;
}) {
  const now = currentMonth();
  const months = Array.from({ length: 25 }, (_, offset) => shiftMonth(now, -offset));
  if (!months.includes(month)) months.push(month);
  return (
    <label className={sheet.select}>
      Месяц{" "}
      <select
        aria-label="Месяц"
        value={month}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        {months.map((value) => (
          <option key={value} value={value}>
            {formatMonthKey(value)}
          </option>
        ))}
      </select>
    </label>
  );
}
export function Section({
  title,
  eyebrow,
  actions,
  children,
  id,
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section className={sheet.section} id={id}>
      <div className={sheet.sectionHead}>
        <div>
          {eyebrow && <p className={sheet.eyebrow}>{eyebrow}</p>}
          <h2>{title}</h2>
        </div>
        {actions && <div className={sheet.sectionActions}>{actions}</div>}
      </div>
      {children}
    </section>
  );
}
export function TemplateButton({ month }: { month: string }) {
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    setFailed(false);
    try {
      const file = await spendingApi.template(month);
      triggerDownload(file.blob, file.filename);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="ghost" disabled={busy} onClick={() => void download()}>
        Скачать шаблон ручного файла
      </Button>
      {failed && <span role="alert">Не удалось скачать шаблон</span>}
    </>
  );
}
export function UploadLink({ month }: { month: string }) {
  return (
    <Link className="btn btn--primary" to={importPath(month)}>
      Загрузить траты
    </Link>
  );
}
export function TypeSelect({
  value,
  onChange,
  label = "Тип",
  disabled,
}: {
  value: ExpenseType;
  onChange: (type: ExpenseType) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <select
      aria-label={label}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(event.target.value as ExpenseType)}
    >
      {types.map((type) => (
        <option value={type} key={type}>
          {typeLabels[type]}
        </option>
      ))}
    </select>
  );
}
