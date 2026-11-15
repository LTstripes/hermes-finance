import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Goal, GoalPlanWithBase } from "../api/goals";
import { CssResponsiveContainer } from "../components/charts/CssResponsiveContainer";
import { formatDate, formatMoney } from "../lib/format";
import { moneyToChartNumber, rub } from "../lib/money";
import { rubleAxisTick } from "./rubleAxis";
import { moneyWholeText } from "./valueFormat";

const stamp = (date: string) => Date.parse(`${date}T00:00:00Z`);
const tick = { fill: "var(--muted)", fontSize: 11 };

/** Numbers are chart coordinates only; amount labels keep the exact API strings. */
export function GoalPlanChart({ plan, goal }: { plan: GoalPlanWithBase; goal: Goal }) {
  const fillId = useId();
  const points = [
    { date: plan.as_of_date, capital: plan.base_capital ?? "0" },
    ...(plan.trajectory ?? []),
  ];
  const data = points.map((point) => ({
    ...point,
    time: stamp(point.date),
    value: moneyToChartNumber(point.capital),
  }));
  const start = data[0];
  const end = data[data.length - 1];
  const deadline = goal.target_date ? stamp(goal.target_date) : null;
  const showDeadline = deadline !== null && deadline >= start.time;
  const domainEnd = showDeadline ? Math.max(end.time, deadline) : end.time;
  const achievement = data.find((point) => point.date === plan.achievement_date);
  const target = moneyToChartNumber(goal.target_value.amount);
  const dates = [start.time, start.time + (domainEnd - start.time) / 2, domainEnd];
  return (
    <figure className="goal-plan-chart" aria-label="Условная помесячная траектория капитала">
      <figcaption className="goal-plan-chart-values">
        <span>
          Старт · {formatDate(start.date)}
          <strong>{moneyWholeText(rub(start.capital))}</strong>
        </span>
        <span>
          Конец · {formatDate(end.date)}
          <strong>{moneyWholeText(rub(end.capital))}</strong>
        </span>
      </figcaption>
      <CssResponsiveContainer height={260}>
        <AreaChart data={data} margin={{ left: 0, right: 15, top: 35, bottom: 8 }}>
          <defs>
            <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.2} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--line-soft)" vertical={false} />
          <XAxis
            dataKey="time"
            type="number"
            scale="time"
            domain={[start.time, domainEnd]}
            ticks={dates}
            tickFormatter={(value: number) =>
              new Intl.DateTimeFormat("ru-RU", { month: "short", year: "numeric", timeZone: "UTC" })
                .format(value)
                .replace(/\s*г\.$/, "")
            }
            tick={tick}
            axisLine={false}
            tickLine={false}
            tickMargin={10}
            minTickGap={16}
          />
          <YAxis
            tick={tick}
            tickFormatter={rubleAxisTick}
            width={60}
            axisLine={false}
            tickLine={false}
            domain={["auto", "auto"]}
          />
          <Tooltip
            content={({ active, payload }) => {
              const point = payload?.[0]?.payload as (typeof data)[number] | undefined;
              return active && point ? (
                <div className="goal-plan-tooltip">
                  {formatDate(point.date)}
                  <strong>{formatMoney(point.capital)}</strong>
                </div>
              ) : null;
            }}
          />
          <ReferenceLine
            y={target}
            ifOverflow="extendDomain"
            stroke="var(--muted)"
            strokeDasharray="5 5"
            label={{
              value: `Цель ${moneyWholeText(goal.target_value)}`,
              position: "insideTopLeft",
              ...tick,
            }}
          />
          {showDeadline ? (
            <ReferenceLine
              x={deadline}
              stroke="var(--faint)"
              strokeDasharray="3 3"
              label={{ value: "Срок", position: "insideTopRight", ...tick }}
            />
          ) : null}
          <Area
            type="linear"
            dataKey="value"
            stroke="var(--accent)"
            strokeWidth={2.5}
            fill={`url(#${fillId})`}
            isAnimationActive={false}
          />
          <ReferenceDot
            x={start.time}
            y={start.value}
            r={4}
            fill="var(--surface)"
            stroke="var(--accent)"
            strokeWidth={2}
          />
          {achievement ? (
            <ReferenceDot
              x={achievement.time}
              y={achievement.value}
              r={5}
              fill="var(--pos)"
              stroke="var(--surface)"
              strokeWidth={2}
              label={{ value: "Достигнете", position: "top", fill: "var(--pos)", fontSize: 11 }}
            />
          ) : null}
        </AreaChart>
      </CssResponsiveContainer>
      {goal.target_date ? (
        <p className="goal-plan-note">Срок цели · {formatDate(goal.target_date)}</p>
      ) : null}
    </figure>
  );
}
