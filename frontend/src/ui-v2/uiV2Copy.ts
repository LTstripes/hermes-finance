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
