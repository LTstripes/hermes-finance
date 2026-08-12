import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CapitalHistoryPoint } from "../../api/types";
import { axisMoney, buildGappedSeries } from "../../lib/chartData";
import { formatMoney } from "../../lib/format";
import { moneyAmount, moneyToChartNumber } from "../../lib/money";
import { EmptyState, HelpTip } from "../ui";
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

type LegendKind = "fact" | "average" | "forecast" | "goal";

function legendMarker(kind: LegendKind, label: string, value?: string) {
  return (
    <span className={`chart-legend__item chart-legend__item--${kind}`}>
      <span
        aria-hidden="true"
        className={`chart-legend__marker chart-legend__marker--${kind}`}
      />
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
        points.map((point) => ({
          year: point.year,
          month: point.month,
          amount: moneyAmount(point.passive_income_actual),
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

  const hasGap = data.some((datum) => datum.rubles == null);
  const labelByKey = new Map(data.map((datum) => [datum.key, datum.shortLabel]));

  return (
    <section
      aria-label="Фактический пассивный доход по закрытым месяцам с прогнозом и целью"
      className="passive-chart passive-chart--v03"
    >
      <ResponsiveContainer height={280} width="100%">
        <BarChart
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
            cursor={{ fill: "rgb(23 32 25 / 5%)" }}
          />
          <Bar
            dataKey="rubles"
            fill="#172019"
            isAnimationActive={false}
            maxBarSize={34}
            name="Факт"
            radius={[5, 5, 0, 0]}
          />
          <ReferenceLine
            ifOverflow="extendDomain"
            stroke="#6f786f"
            strokeDasharray="2 3"
            y={moneyToChartNumber(average)}
          />
          <ReferenceLine
            ifOverflow="extendDomain"
            stroke="#9a6a1d"
            strokeDasharray="6 4"
            y={moneyToChartNumber(forecast)}
          />
          <ReferenceLine
            ifOverflow="extendDomain"
            stroke="#27734c"
            strokeWidth={2}
            y={moneyToChartNumber(goal)}
          />
        </BarChart>
      </ResponsiveContainer>

      <div className="chart-legend" aria-label="Обозначения графика">
        {legendMarker("fact", "Факт по месяцам")}
        {legendMarker("average", "Среднее факта", formatMoney(average))}
        {legendMarker("forecast", "Прогноз", formatMoney(forecast))}
        {legendMarker("goal", "Цель", formatMoney(goal))}
      </div>

      <div className="chart-meta-row">
        {!complete12m ? (
          <span className="chart-meta-item">
            Среднее: {countMonths} {pluralMonths(countMonths)} из 12
            <HelpTip label="Как считается среднее пассивного дохода" align="start">
              Среднее рассчитано только по доступным закрытым месяцам. Полное rolling-окно будет
              доступно после 12 закрытых месяцев.
            </HelpTip>
          </span>
        ) : null}
        {hasGap ? (
          <span className="chart-meta-item">
            Есть пропуски в истории
            <HelpTip label="Как отображаются пропуски в истории" align="start">
              Месяц без закрытых данных остаётся пустым. Значение между соседними месяцами не
              интерполируется.
            </HelpTip>
          </span>
        ) : null}
      </div>
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
