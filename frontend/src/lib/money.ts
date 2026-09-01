import type { MoneyValue } from "../api/types";

/** Normalize user money input to API decimal string (no float math). */
export function normalizeMoneyInput(value: string): string | null {
  const cleaned = value
    .trim()
    .replace(/\u00a0/g, "")
    .replace(/\s/g, "")
    .replace(",", ".");
  if (cleaned === "") {
    return null;
  }
  if (!/^-?\d+(\.\d{1,2})?$/.test(cleaned)) {
    return null;
  }
  const negative = cleaned.startsWith("-");
  const unsigned = negative ? cleaned.slice(1) : cleaned;
  const [intPart, frac = ""] = unsigned.split(".");
  const cents = `${frac}00`.slice(0, 2);
  const body = `${intPart}.${cents}`;
  return negative ? `-${body}` : body;
}

/** Format a valid money string for editing without using locale-dependent parsing. */
export function formatMoneyInput(value: string): string {
  const normalized = normalizeMoneyInput(value);
  if (normalized == null) return value;

  const negative = normalized.startsWith("-");
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [intPart, fraction = "00"] = unsigned.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
  return `${negative ? "-" : ""}${grouped},${fraction}`;
}

export function rub(amount: string): MoneyValue {
  const normalized = normalizeMoneyInput(amount);
  if (normalized == null) {
    throw new Error(`invalid money amount: ${amount}`);
  }
  return { amount: normalized, currency: "RUB" };
}

export function moneyAmount(value: MoneyValue | null | undefined): string {
  return value?.amount ?? "";
}

/** Empty / zero-ish for optional lines. */
export function isBlankMoney(value: string): boolean {
  const n = normalizeMoneyInput(value);
  return n == null || n === "0.00" || n === "-0.00";
}

function normalizedToKopecks(normalized: string): bigint {
  const negative = normalized.startsWith("-");
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [intPart, frac = "00"] = unsigned.split(".");
  const kopecks = BigInt(intPart) * 100n + BigInt(frac.padEnd(2, "0").slice(0, 2));
  return negative ? -kopecks : kopecks;
}

/** Parse a money amount into exact integer kopecks. Invalid values are rejected. */
export function toKopecks(amount: string): bigint {
  const normalized = normalizeMoneyInput(amount);
  if (normalized == null) {
    throw new Error(`invalid money amount: ${amount}`);
  }
  return normalizedToKopecks(normalized);
}

/** Convert exact integer kopecks back to the canonical decimal-string amount. */
export function fromKopecks(kopecks: bigint): string {
  const negative = kopecks < 0n;
  const abs = negative ? -kopecks : kopecks;
  const major = abs / 100n;
  const cents = String(abs % 100n).padStart(2, "0");
  return `${negative ? "-" : ""}${major}.${cents}`;
}

/** Sum money amount strings via exact integer kopecks. Invalid/blank optional lines are ignored. */
export function sumMoneyAmounts(amounts: Array<string | null | undefined>): string {
  let totalKopecks = 0n;
  for (const raw of amounts) {
    if (raw == null || raw === "") {
      continue;
    }
    const normalized = normalizeMoneyInput(raw);
    if (normalized == null) {
      continue;
    }
    totalKopecks += normalizedToKopecks(normalized);
  }
  return fromKopecks(totalKopecks);
}

/**
 * Exact percentage of one money amount within another, rounded HALF_UP for display.
 * The result is a decimal string in percentage points (e.g. "33.3").
 */
export function moneySharePercent(
  partAmount: string,
  totalAmount: string,
  digits: 1 | 2 = 1,
): string {
  const part = toKopecks(partAmount);
  const total = toKopecks(totalAmount);
  if (part < 0n || total <= 0n) {
    throw new Error("money share requires a non-negative part and positive total");
  }

  const scale = 10n ** BigInt(digits);
  const numerator = part * 100n * scale;
  const quotient = numerator / total;
  const remainder = numerator % total;
  const rounded = remainder * 2n >= total ? quotient + 1n : quotient;
  const major = rounded / scale;
  const fraction = String(rounded % scale).padStart(digits, "0");
  return `${major}.${fraction}`;
}

/**
 * Deliberate lossy boundary for chart libraries that require JavaScript numbers.
 * Never use the returned value for financial aggregation, comparison, or percentages.
 */
export function moneyToChartNumber(amount: string): number {
  return Number(toKopecks(amount)) / 100;
}
