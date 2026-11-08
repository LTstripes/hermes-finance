import type { InstrumentAnalysis, InstrumentMetric } from "../../api/sourceReturns";
import type { Metric } from "./model";

export type ReturnBreakdown = {
  payouts_kopecks: string | null;
  price_and_trades_kopecks: string | null;
  commissions_kopecks: string | null;
  paid_nkd_kopecks: string | null;
  taxes_kopecks: string | null;
  other_kopecks: string | null;
  total_kopecks: string | null;
  complete: boolean;
};
export const integerMoney = (value: string | null): value is string =>
  value !== null && /^-?\d+$/.test(value);

export function breakdownRows(value: ReturnBreakdown) {
  return [
    { label: "Выплаты (купоны + дивиденды)", value: value.payouts_kopecks, subtract: false },
    { label: "Цена и результат сделок", value: value.price_and_trades_kopecks, subtract: false },
    { label: "Комиссии", value: value.commissions_kopecks, subtract: true },
    { label: "Уплаченный НКД", value: value.paid_nkd_kopecks, subtract: true },
    { label: "Учтённые налоги", value: value.taxes_kopecks, subtract: true },
    { label: "Прочие операции по счёту", value: value.other_kopecks, subtract: false },
  ]
    .filter((row, index) => index < 4 || row.value === null || row.value !== "0")
    .map((row) => ({
      ...row,
      value: integerMoney(row.value)
        ? (BigInt(row.value) * (row.subtract ? -1n : 1n)).toString()
        : null,
    }));
}

/** Verify exact producer operands; never manufacture a remainder. */
export function breakdownMatches(value: ReturnBreakdown, total: Metric) {
  const rows = breakdownRows(value);
  return (
    value.complete &&
    integerMoney(total.value) &&
    total.value === value.total_kopecks &&
    rows.every((row) => integerMoney(row.value)) &&
    rows.reduce((sum, row) => sum + BigInt(row.value as string), 0n) === BigInt(total.value)
  );
}

export function analysisBreakdown(
  analyses: InstrumentAnalysis<string>[],
  total: Metric,
  eligible = true,
): ReturnBreakdown {
  let complete = eligible && analyses.length > 0;
  const sum = (name: string) => {
    const metrics = analyses.map(
      (analysis) =>
        (analysis.components as Record<string, InstrumentMetric<string> | undefined>)[name],
    );
    if (!metrics.length || metrics.some((metric) => !metric || !integerMoney(metric.value))) {
      complete = false;
      return null;
    }
    if (
      metrics.some((metric) => metric?.status !== "supported" && metric?.status !== "provisional")
    )
      complete = false;
    return metrics
      .reduce((value, metric) => value + BigInt(metric?.value as string), 0n)
      .toString();
  };
  const value = {
    payouts_kopecks: sum("payouts"),
    price_and_trades_kopecks: sum("price_and_trades"),
    commissions_kopecks: sum("commissions"),
    paid_nkd_kopecks: sum("paid_nkd"),
    taxes_kopecks: sum("taxes"),
    other_kopecks: "0",
    total_kopecks: total.value,
    complete: false,
  };
  value.complete = complete;
  return value;
}
