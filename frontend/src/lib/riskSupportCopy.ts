import { ASSET_CLASS_NAMES } from "./labels";
import { reasonCopy } from "./reasonCopy";
/**
 * Owner-facing copy for the R07-06A allocation/concentration support model.
 *
 * Shared so a second surface cannot invent a different wording for the same
 * backend reason code and support status.
 */

export const ASSET_CLASS_LABELS: Record<string, string> = {
  cash: ASSET_CLASS_NAMES.cash,
  deposits: ASSET_CLASS_NAMES.deposits,
  stock: ASSET_CLASS_NAMES.stocks,
  bond: ASSET_CLASS_NAMES.bonds,
  fund: "Фонды",
  currency: "Валюта",
  gold: ASSET_CLASS_NAMES.gold_other,
  other: "Прочее",
  unknown_asset_class: "Неизвестный класс активов",
  unassigned_cash: "Наличные без привязки к счёту",
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
  return reasonCopy(reason, { surface: "risk" }).message;
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
