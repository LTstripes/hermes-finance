import { useMemo } from "react";
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
import { buildGappedSeries, axisMoney } from "../../lib/chartData";
import { moneyAmount } from "../../lib/money";
import { EmptyState } from "../ui";
import { MoneyTooltip } from "./MoneyTooltip";

export function CapitalChart({ points }: { points: CapitalHistoryPoint[] }) {
  const data = useMemo(
    () =>
      buildGappedSeries(
        points.map((p) => ({
          year: p.year,
          month: p.month,
          amount: moneyAmount(p.liquid_capital_net),
        })),
      ),
    [points],
  );

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
          <Tooltip
            content={(props) => <MoneyTooltip {...props} />}
            cursor={{ stroke: "#b9c4b9" }}
          />
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
