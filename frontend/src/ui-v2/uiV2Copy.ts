/** Shared owner-facing wording for the native UI v2 surfaces. */

export const PRINCIPAL_REPAYMENT_LABEL = "Возврат основной суммы";
export const UNKNOWN_SOURCE_LABEL = "Источник не распознан";

const SPENDING_MONTH_FORMS = {
  accusative: [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
  ],
  genitive: [
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
  ],
  prepositional: [
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
  ],
};

export function spendingMonthForm(month: string, form: keyof typeof SPENDING_MONTH_FORMS) {
  return SPENDING_MONTH_FORMS[form][Number(month.slice(5)) - 1] ?? "";
}

export function spendingComparisonNote(
  hasManual: boolean,
  months: { month: string; has_manual: boolean }[],
) {
  if (!hasManual)
    return months.some((item) => item.has_manual)
      ? "Сравнение неточное: в этом месяце нет ручного файла, наличные и Сбер не учтены."
      : null;
  const missing = months
    .filter((item) => !item.has_manual)
    .map((item) => spendingMonthForm(item.month, "prepositional"));
  if (!missing.length) return null;
  const list =
    missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(", ")} и ${missing.at(-1)}`;
  return `Сравнение неточное: в ${list} нет ручного файла, траты там могли быть выше.`;
}

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
