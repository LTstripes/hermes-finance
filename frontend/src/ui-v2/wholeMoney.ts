import type { MoneyValue } from "../api/types";
import { formatMoney, formatMoneyDelta } from "../lib/format";
import { normalizeMoneyInput, toKopecks } from "../lib/money";

/**
 * Whole rubles for overview figures (P 12.2, #1079): exact kopecks rounded
 * HALF_UP away from zero with integers only. Details keep the exact amount.
 * A non-zero amount under half a ruble keeps its kopecks: it never reads as zero.
 */
function wholeAmount(amount: string | null | undefined): string | null {
  if (amount == null || normalizeMoneyInput(amount) == null) return null;
  const kopecks = toKopecks(amount);
  const negative = kopecks < 0n;
  const rubles = ((negative ? -kopecks : kopecks) + 50n) / 100n;
  if (rubles === 0n && kopecks !== 0n) return amount;
  return `${negative && rubles > 0n ? "-" : ""}${rubles}`;
}

function currencyMark(value: MoneyValue | null | undefined): string | undefined {
  return value?.currency === "RUB" ? "₽" : value?.currency;
}

export function wholeMoneyText(value: MoneyValue | null | undefined, empty = "Недоступно"): string {
  const amount = wholeAmount(value?.amount);
  return amount === null ? empty : formatMoney(amount, { currency: currencyMark(value), empty });
}

export function wholeMoneyDeltaText(
  value: MoneyValue | null | undefined,
  empty = "Недоступно",
): string {
  const amount = wholeAmount(value?.amount);
  return amount === null
    ? empty
    : formatMoneyDelta(amount, { currency: currencyMark(value), empty });
}
