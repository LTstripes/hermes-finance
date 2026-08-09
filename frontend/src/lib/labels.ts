export const MONTH_STATUS_LABELS: Record<string, string> = {
  draft: "Черновик",
  closed: "Утверждён",
};

export const SOURCE_LABELS: Record<string, string> = {
  manual: "Вручную",
  excel_migration: "Импорт из Excel",
  alfa_pdf: "Выписка Альфа-Банка",
};

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  brokerage: "Брокерский",
  iis: "ИИС",
  deposit: "Депозит",
  savings: "Накопительный счёт",
  cash: "Наличные",
  other: "Прочее",
};

export const INSTRUMENT_TYPE_LABELS: Record<string, string> = {
  stock: "Акции",
  bond: "Облигации",
  fund: "Фонды",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
};

export const FLOW_TYPE_LABELS: Record<string, string> = {
  coupon: "Купон",
  dividend: "Дивиденды",
  interest: "Проценты",
  redemption: "Погашение",
  commission: "Комиссия",
  tax: "Налог",
  other: "Прочее",
};

export const EXPENSE_TYPE_LABELS: Record<string, string> = {
  mandatory: "Обязательный",
  comfortable: "Комфортный",
  other: "Прочее",
};

export const BENEFIT_STATUS_LABELS: Record<string, string> = {
  planned: "Запланировано",
  submitted: "Подано",
  received: "Получено",
  rejected: "Отклонено",
};

export const PRICE_SOURCE_LABELS: Record<string, string> = {
  manual: "Вручную",
  moex: "Мосбиржа",
  alfa_pdf: "Выписка Альфа-Банка",
};

export const IIS_TYPE_LABELS: Record<string, string> = {
  type_a: "Тип А",
  type_b: "Тип Б",
  type_3: "Тип 3",
};

export const DEPOSIT_TYPE_LABELS: Record<string, string> = {
  deposit: "Депозит",
  savings: "Накопления",
};

export const DEBT_TYPE_LABELS: Record<string, string> = {
  credit_card: "Кредитная карта",
  other: "Прочее",
};

export function labelOf(labels: Record<string, string>, value: string): string {
  return labels[value] ?? value;
}
