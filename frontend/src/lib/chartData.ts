import { formatMonth } from "./format";
import { moneyToChartNumber } from "./money";

const SHORT_MONTHS_RU = [
  "Янв",
  "Фев",
  "Мар",
  "Апр",
  "Май",
  "Июн",
  "Июл",
  "Авг",
  "Сен",
  "Окт",
  "Ноя",
  "Дек",
] as const;

/** One chart datum. `rubles: null` marks a gap — the line must not cross it. */
export type ChartDatum = {
  key: string;
  year: number;
  month: number;
  label: string;
  shortLabel: string;
  rubles: number | null;
  amount: string;
};

/** Input point: a closed month with its decimal-string amount. */
export type SeriesPoint = {
  year: number;
  month: number;
  amount: string;
};

export function isContiguousMonth(
  prev: { year: number; month: number },
  next: { year: number; month: number },
): boolean {
  if (prev.month === 12) {
    return next.year === prev.year + 1 && next.month === 1;
  }
  return next.year === prev.year && next.month === prev.month + 1;
}

/**
 * Build chart data from a monthly series. When two consecutive points are
 * not calendar-contiguous (a month has no data), a `null` gap point is
 * inserted so Recharts breaks the line instead of interpolating across
 * missing months (E12/E13 acceptance).
 */
export function buildGappedSeries(points: SeriesPoint[]): ChartDatum[] {
  const data: ChartDatum[] = [];
  let previous: { year: number; month: number } | null = null;

  for (const point of points) {
    if (previous != null && !isContiguousMonth(previous, point)) {
      data.push({
        key: `gap-${data.length}`,
        year: 0,
        month: 0,
        label: "",
        shortLabel: "",
        rubles: null,
        amount: "",
      });
    }
    data.push({
      key: `${point.year}-${String(point.month).padStart(2, "0")}`,
      year: point.year,
      month: point.month,
      label: formatMonth(point.year, point.month),
      shortLabel: `${SHORT_MONTHS_RU[point.month - 1] ?? ""} ${point.year}`.trim(),
      // Recharts coordinate only; all financial logic stays on exact decimal strings/kopecks.
      rubles: moneyToChartNumber(point.amount),
      amount: point.amount,
    });
    previous = { year: point.year, month: point.month };
  }

  return data;
}

/** Compact Y-axis label: 1.2 млн / 45 тыс / 300. Display-only. */
export function axisMoney(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    const millions = (value / 1_000_000)
      .toFixed(1)
      .replace(".", ",")
      .replace(/0$/, "")
      .replace(/,$/, "");
    return `${millions} млн`;
  }
  if (abs >= 1_000) {
    return `${Math.round(value / 1_000)} тыс`;
  }
  return String(Math.round(value));
}
