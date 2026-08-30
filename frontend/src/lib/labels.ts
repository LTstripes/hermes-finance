export const MONTH_STATUS_LABELS: Record<string, string> = {
  draft: "Черновик",
  closed: "Утверждён",
};

export const SOURCE_LABELS: Record<string, string> = {
  manual: "Вручную",
  excel_migration: "Импорт из Excel",
  alfa_pdf: "Выписка Альфа-Банка",
  alfa_depository_income_report: "Выписка Альфа-Банка",
  t_invest: "T-Invest",
  moex: "MOEX",
  alfa_pro: "Alfa PRO",
};

export const FRESHNESS_STATUS_LABELS: Record<string, string> = {
  current: "Актуально",
  stale: "Устарело",
  mixed: "Смешанно",
  unavailable: "Вне окна",
  unknown: "Неизвестно",
  not_applicable: "Вручную / не оценивается",
  missing: "Нет данных",
};

export const SOURCE_TIMESTAMP_KIND_LABELS: Record<string, string> = {
  price_date: "Дата котировки",
  payment_date: "Дата выплаты",
  event_date: "Дата события",
  record_date: "Дата фиксации",
  fetched_at: "Время запроса к провайдеру",
  source_as_of: "Время наблюдения провайдера",
  unavailable: "Нет времени наблюдения",
  not_applicable: "Не применяется",
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
  t_invest: "T-Invest",
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
