/**
 * Owner-facing copy for the R07-06A allocation/concentration support model.
 *
 * Shared so a second surface cannot invent a different wording for the same
 * backend reason code and support status.
 */

export const ASSET_CLASS_LABELS: Record<string, string> = {
  cash: "Наличные",
  deposits: "Депозиты",
  stock: "Акции",
  bond: "Облигации",
  fund: "Фонды",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
  unknown_asset_class: "Неизвестный класс активов",
  unassigned_cash: "Наличные без привязки к счёту",
};

export const REASON_LABELS: Record<string, string> = {
  bank_identity_not_persisted: "банк не указан для этих данных",
  broker_identity_not_persisted: "брокер не указан для этих данных",
  cash_not_account_linked: "наличные не связаны со счётом",
  currency_conversion_not_supported: "не удалось привести валюту к единому виду",
  currency_not_persisted: "валюта не указана",
  deposit_forecast_not_concentratable: "по оценке депозита нет датированного события",
  instrument_not_persisted: "инструмент не указан для события",
  instrument_type_not_authoritative: "класс инструмента не подтверждён сохранёнными данными",
  issuer_not_persisted: "эмитент не указан",
  maturity_not_persisted: "срок погашения не указан",
  no_dated_payouts: "датированных событий в окне нет",
  unsupported_position_valuation: "оценка позиции непригодна для расчёта",
};

export const SOURCE_KIND_LABELS: Record<string, string> = {
  cash_balance: "Денежный остаток",
  deposit: "Депозит",
  expected_flow: "Ожидаемая выплата",
  payout: "Выплата",
  position: "Позиция",
  property: "Недвижимость",
};

export type SupportStatus = "supported" | "unavailable" | "unknown";

const STATUS_LABELS: Record<SupportStatus, string> = {
  supported: "Поддерживается",
  unavailable: "Недоступно",
  unknown: "Неизвестно",
};

export function supportStatusLabel(status: SupportStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function supportStatusTone(status: SupportStatus): "ok" | "missing" | "unknown" {
  if (status === "supported") return "ok";
  return status === "unavailable" ? "missing" : "unknown";
}

export function supportReasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? "дополнительное ограничение данных";
}

export function sourceKindLabel(value: string): string {
  return SOURCE_KIND_LABELS[value] ?? "Исключённая строка";
}

/**
 * One owner-facing sentence for a metric that the saved data cannot support.
 * Returns null when the metric is supported and only its rows matter.
 */
export function unsupportedMetricReason(
  status: SupportStatus,
  reasonCodes: string[],
): string | null {
  if (status === "supported") return null;
  const reason = reasonCodes[0];
  if (!reason) return "Этот срез нельзя построить из доступных данных.";
  return `Этот срез нельзя построить: ${supportReasonLabel(reason)}.`;
}
