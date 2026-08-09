import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CapitalHistoryPoint } from "../../api/types";
import { buildGappedSeries, axisMoney } from "../../lib/chartData";
import { formatMoney } from "../../lib/format";
import { moneyAmount } from "../../lib/money";
import { EmptyState } from "../ui";
import { MoneyTooltip } from "./MoneyTooltip";

type PassiveIncomeChartProps = {
  /** Closed-month history from the dashboard (passive_income_actual per month). */
  points: CapitalHistoryPoint[];
  /** Actual average over the available window (kpis.passive_income_average). */
  average: string;
  /** Monthly forecast (kpis.forecast_monthly_passive_income). */
  forecast: string;
  /** Monthly goal target (kpis.goal_target). */
  goal: string;
  /** True when the 12-month rolling window is complete. */
  complete12m: boolean;
  /** Number of months included in the average window. */
  countMonths: number;
};

function legendMarker(className: string, label: string, value?: string) {
  return (
    <span className="chart-legend__item">
      <span aria-hidden="true" className={`chart-legend__marker ${className}`} />
      {label}
      {value ? (
        <>
          {": "}
          <strong>{value}</strong>
        </>
      ) : null}
    </span>
  );
}

export function PassiveIncomeChart({
  points,
  average,
  forecast,
  goal,
  complete12m,
  countMonths,
}: PassiveIncomeChartProps) {
  const data = useMemo(
    () =>
      buildGappedSeries(
        points.map((p) => ({
          year: p.year,
          month: p.month,
          amount: moneyAmount(p.passive_income_actual),
        })),
      ),
    [points],
  );

  if (data.length === 0) {
    return (
      <EmptyState
        description="График пассивного дохода появится после закрытия первого месяца."
        title="Нет закрытых месяцев"
      />
    );
  }

  const hasGap = data.some((d) => d.rubles == null);
  const labelByKey = new Map(data.map((d) => [d.key, d.shortLabel]));

  return (
    <section
      aria-label="Фактический и прогнозный пассивный доход по закрытым месяцам"
      className="passive-chart"
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
            dot={{ fill: "#172019", r: 3, strokeWidth: 0 }}
            isAnimationActive={false}
            name="Факт"
            stroke="#172019"
            strokeWidth={2}
            type="linear"
          />
          <ReferenceLine stroke="#6f786f" strokeDasharray="4 4" y={Number(average)} />
          <ReferenceLine stroke="#9a6a1d" strokeDasharray="4 4" y={Number(forecast)} />
          <ReferenceLine stroke="#27734c" strokeDasharray="6 3" y={Number(goal)} />
        </LineChart>
      </ResponsiveContainer>

      <div className="chart-legend">
        {legendMarker("chart-legend__marker--fact", "Факт")}
        {legendMarker("chart-legend__marker--average", "Среднее", formatMoney(average))}
        {legendMarker("chart-legend__marker--forecast", "Прогноз", formatMoney(forecast))}
        {legendMarker("chart-legend__marker--goal", "Цель", formatMoney(goal))}
      </div>

      {!complete12m ? (
        <p className="chart-note chart-note--warn" role="status">
          Среднее за доступный период. Учтено {countMonths} {pluralMonths(countMonths)} из 12.
        </p>
      ) : null}
      {hasGap ? (
        <p className="chart-note">
          Линия разрывается в месяцах без закрытых данных — без интерполяции.
        </p>
      ) : null}
    </section>
  );
}

function pluralMonths(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "месяц";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "месяца";
  return "месяцев";
}
