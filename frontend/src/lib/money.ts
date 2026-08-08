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
