import type { MoneyValue } from "../api/types";
import { formatMoney, formatMoneyDelta } from "../lib/format";

/**
 * Shared UI v2 money presentation.
 *
 * These helpers only format canonical backend money strings; they never
 * convert, aggregate or recompute a financial value.
 */
export function moneyText(value: MoneyValue | null | undefined, empty = "Недоступно"): string {
  return formatMoney(value?.amount, {
    currency: value?.currency === "RUB" ? "₽" : value?.currency,
    empty,
  });
}

export function moneyDeltaText(value: MoneyValue | null | undefined, empty = "Недоступно"): string {
  return formatMoneyDelta(value?.amount, {
    currency: value?.currency === "RUB" ? "₽" : value?.currency,
    empty,
  });
}

export function moneyTone(
  value: MoneyValue | null | undefined,
): "positive" | "negative" | "neutral" {
  const amount = value?.amount.trim() ?? "";
  if (/^-/.test(amount) && !/^-0(?:\.0+)?$/.test(amount)) return "negative";
  if (/^\+?[0-9]/.test(amount) && !/^\+?0(?:\.0+)?$/.test(amount)) return "positive";
  return "neutral";
}

/** A liability increase is worse for net capital, so its tone is inverted. */
export function liabilityTone(
  value: MoneyValue | null | undefined,
): "positive" | "negative" | "neutral" {
  const ordinary = moneyTone(value);
  if (ordinary === "positive") return "negative";
  if (ordinary === "negative") return "positive";
  return "neutral";
}
