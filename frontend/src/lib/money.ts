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

/** Sum money amount strings via integer kopecks (no binary float). */
export function sumMoneyAmounts(amounts: Array<string | null | undefined>): string {
  let totalKopecks = 0;
  for (const raw of amounts) {
    if (raw == null || raw === "") {
      continue;
    }
    const n = normalizeMoneyInput(raw);
    if (n == null) {
      continue;
    }
    const negative = n.startsWith("-");
    const unsigned = negative ? n.slice(1) : n;
    const [intPart, frac = "00"] = unsigned.split(".");
    const kopecks = Number(intPart) * 100 + Number(frac.padEnd(2, "0").slice(0, 2));
    totalKopecks += negative ? -kopecks : kopecks;
  }
  const neg = totalKopecks < 0;
  const abs = Math.abs(totalKopecks);
  const major = Math.floor(abs / 100);
  const cents = String(abs % 100).padStart(2, "0");
  return `${neg ? "-" : ""}${major}.${cents}`;
}
