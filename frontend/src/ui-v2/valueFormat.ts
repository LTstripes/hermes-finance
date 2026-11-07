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

/**
 * Overview money in whole rubles (P 12.2): kopecks are rounded HALF_UP away from
 * zero for display only. Exact amounts stay in tables and tooltips.
 */
export function moneyWholeText(value: MoneyValue | null | undefined, empty = "Недоступно"): string {
  const whole = wholeRubles(value?.amount);
  if (whole === null) return moneyText(value, empty);
  return formatMoney(whole, {
    currency: value?.currency === "RUB" ? "₽" : value?.currency,
    empty,
  });
}

/** Signed whole-ruble delta: "+28 900 ₽" / "−203 478 ₽". */
export function moneyWholeDeltaText(
  value: MoneyValue | null | undefined,
  empty = "Недоступно",
): string {
  const whole = wholeRubles(value?.amount);
  if (whole === null) return moneyDeltaText(value, empty);
  return formatMoneyDelta(whole, {
    currency: value?.currency === "RUB" ? "₽" : value?.currency,
    empty,
  });
}

function wholeRubles(amount: string | undefined): string | null {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount?.trim() ?? "");
  if (!match) return null;
  const [, sign, integer, fraction = ""] = match;
  const roundUp = (fraction[0] ?? "0") >= "5";
  const rubles = BigInt(integer) + (roundUp ? 1n : 0n);
  return `${sign && rubles > 0n ? "-" : ""}${rubles}`;
}

/**
 * Display rounding of a backend percentage string, HALF_UP away from zero,
 * without binary floats: ("-3.13", 1) → "−3,1%", ("92.5", 0) → "93%".
 */
export function percentText(
  value: string | null | undefined,
  digits: 0 | 1 | 2 = 1,
  options: { signed?: boolean; empty?: string } = {},
): string {
  const { signed = false, empty = "—" } = options;
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value?.trim() ?? "");
  if (!match) return empty;
  const [, sign, integer, fraction = ""] = match;
  const kept = fraction.padEnd(digits, "0").slice(0, digits);
  const roundUp = (fraction[digits] ?? "0") >= "5";
  const scaled = BigInt(`${integer}${kept}`) + (roundUp ? 1n : 0n);
  const text = scaled.toString().padStart(digits + 1, "0");
  const body = digits === 0 ? text : `${text.slice(0, -digits)},${text.slice(-digits)}`;
  const isZero = scaled === 0n;
  const prefix = isZero ? "" : sign ? "−" : signed ? "+" : "";
  return `${prefix}${body}%`;
}
