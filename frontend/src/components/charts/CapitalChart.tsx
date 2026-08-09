import { useMemo } from "react";
import type { TooltipContentProps } from "recharts";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CapitalHistoryPoint } from "../../api/types";
import { formatMoney, formatMonth } from "../../lib/format";
import { moneyAmount } from "../../lib/money";
import { EmptyState } from "../ui";

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
export type CapitalChartDatum = {
  key: string;
  year: number;
  month: number;
  label: string;
  shortLabel: string;
  rubles: number | null;
  amount: string;
};

function isContiguousMonth(
  prev: { year: number; month: number },
  next: { year: number; month: number },
): boolean {
  if (prev.month === 12) {
    return next.year === prev.year + 1 && next.month === 1;
  }
  return next.year === prev.year && next.month === prev.month + 1;
}

/**
 * Build chart data from the closed-month history. When two consecutive
 * closed months are not calendar-contiguous (a month has no closed data),
 * a `null` gap point is inserted so Recharts breaks the line instead of
 * interpolating across missing months (E12 acceptance).
 */
export function buildCapitalChartData(points: CapitalHistoryPoint[]): CapitalChartDatum[] {
  const data: CapitalChartDatum[] = [];
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
    const amount = moneyAmount(point.liquid_capital_net);
    data.push({
      key: `${point.year}-${String(point.month).padStart(2, "0")}`,
      year: point.year,
      month: point.month,
      label: formatMonth(point.year, point.month),
      shortLabel: `${SHORT_MONTHS_RU[point.month - 1] ?? ""} ${point.year}`.trim(),
      // Axis position only — display always goes through formatMoney on the string.
      rubles: Number(amount),
      amount,
    });
    previous = { year: point.year, month: point.month };
  }

  return data;
}

function axisMoney(value: number): string {
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

function CapitalTooltip({ active, payload }: TooltipContentProps) {
  const datum = (payload?.[0]?.payload ?? undefined) as CapitalChartDatum | undefined;
  if (!active || !datum || datum.rubles == null) {
    return null;
  }
  return (
    <div className="chart-tooltip">
      <strong>{datum.label}</strong>
      <span className="chart-tooltip__amount">{formatMoney(datum.amount)}</span>
    </div>
  );
}

export function CapitalChart({ points }: { points: CapitalHistoryPoint[] }) {
  const data = useMemo(() => buildCapitalChartData(points), [points]);

  if (data.length === 0) {
    return (
      <EmptyState
        description="График динамики капитала появится после закрытия первого месяца."
        title="Нет закрытых месяцев"
      />
    );
  }

  const hasGap = data.some((d) => d.rubles == null);
  const labelByKey = new Map(data.map((d) => [d.key, d.shortLabel]));

  return (
    <section
      aria-label="Динамика ликвидного капитала по закрытым месяцам"
      className="capital-chart"
    >
      <ResponsiveContainer height={280} width="100%">
        <LineChart
          accessibilityLayer
          data={data}
          margin={{ bottom: 4, left: 8, right: 16, top: 8 }}
        >
          <CartesianGrid stroke="#dfe3dc" strokeDasharray="3 3" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="key"
            interval="preserveStartEnd"
            tickFormatter={(key: string) => labelByKey.get(key) ?? ""}
            tickLine={false}
          />
          <YAxis axisLine={false} tickFormatter={axisMoney} tickLine={false} width={72} />
          <Tooltip content={(props) => <CapitalTooltip {...props} />} cursor={{ stroke: "#b9c4b9" }} />
          <Line
            activeDot={{ r: 5 }}
            connectNulls={false}
            dataKey="rubles"
            dot={{ fill: "#27734c", r: 3, strokeWidth: 0 }}
            isAnimationActive={false}
            name="Капитал"
            stroke="#27734c"
            strokeWidth={2}
            type="linear"
          />
        </LineChart>
      </ResponsiveContainer>
      {hasGap ? (
        <p className="capital-chart__note">
          Линия разрывается в месяцах без закрытых данных — без интерполяции.
        </p>
      ) : null}
    </section>
  );
}
