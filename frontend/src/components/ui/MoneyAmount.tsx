import { formatMoney } from "../../lib/format";
import type { MoneyValue } from "../../api/types";

type MoneyAmountProps = {
  amount?: string | MoneyValue | null | undefined;
  currency?: string;
  empty?: string;
  className?: string;
};

/**
 * #650: one readable typographic unit for money + sign/currency.
 * Keeps amount, sign and currency on one line with stable tabular alignment.
 * Zero renders as "0 ₽", null/empty renders the explicit empty label, never blank.
 */
export function MoneyAmount({ amount, currency, empty = "—", className = "" }: MoneyAmountProps) {
  const raw = typeof amount === "string" ? amount : (amount?.amount ?? null);
  const resolvedCurrency =
    currency ??
    (typeof amount === "object" && amount !== null && amount.currency !== "RUB"
      ? amount.currency
      : "₽");
  const text = formatMoney(raw, { currency: resolvedCurrency, empty });
  const isEmpty = text === empty;
  const classes = ["money", isEmpty ? "money--empty" : "", className].filter(Boolean).join(" ");
  return <span className={classes}>{text}</span>;
}
