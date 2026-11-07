/** Shared owner-facing wording for the native UI v2 surfaces. */

export const PRINCIPAL_REPAYMENT_LABEL = "Возврат основной суммы";
export const UNKNOWN_SOURCE_LABEL = "Источник не распознан";

const EVENT_LABELS: Record<string, string> = {
  coupon: "Купон",
  dividend: "Дивиденд",
  deposit_interest: "Проценты по депозиту",
  other_capital_income: "Прочий доход от капитала",
  redemption_principal: PRINCIPAL_REPAYMENT_LABEL,
};

const SOURCE_LABELS: Record<string, string> = {
  manual: "введено вручную",
  provider: "внешний источник",
  deposit_forecast: "оценка по депозиту",
};

export function eventLabel(component: string): string {
  return EVENT_LABELS[component] ?? "Тип события не распознан";
}

export function sourceLabel(sourceKind: string): string {
  return SOURCE_LABELS[sourceKind] ?? UNKNOWN_SOURCE_LABEL;
}

/** Accounting boundary used only in Home and Income copy. */
export function accountingStartLabel(value: string | null): string {
  const match = /^(\d{4})-(\d{2})$/.exec(value ?? "");
  if (!match) return "";
  const months = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
  ];
  const month = months[Number(match[2]) - 1];
  return month ? `с ${month} ${match[1]}` : "";
}

const DATIVE_MONTHS = [
  "январю",
  "февралю",
  "марту",
  "апрелю",
  "маю",
  "июню",
  "июлю",
  "августу",
  "сентябрю",
  "октябрю",
  "ноябрю",
  "декабрю",
];

/** "к сентябрю", or "к декабрю 2030" when the base is in another year. */
export function comparedToLabel(
  base: { year: number; month: number },
  current: { year: number },
): string {
  const month = DATIVE_MONTHS[base.month - 1];
  if (!month) return "";
  return base.year === current.year ? `к ${month}` : `к ${month} ${base.year}`;
}
