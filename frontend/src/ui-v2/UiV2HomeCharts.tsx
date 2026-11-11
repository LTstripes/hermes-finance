import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { toKopecks } from "../lib/money";
import { formatMoney } from "../lib/format";
import { rubleAxisTick } from "./rubleAxis";
import styles from "./UiV2Home.module.css";

/*
 * Chart geometry for Home (#1079, direction A). SVG presentation attributes
 * need literal colours, so these mirror tokens.css. Numbers here are lossy
 * chart coordinates only; every displayed amount comes from a backend string.
 */
const C = {
  accent: "#1f4e8c",
  accentSoft: "#b9c8dc",
  ink: "#152131",
  ink2: "#3b4757",
  muted: "#5f6a78",
  faint: "#a3abb5",
  line2: "#efede7",
  pos: "#1f7a50",
  neg: "#b23b32",
  base: "#c3cedb",
  surface: "#ffffff",
};

const TICK = { fontSize: 11, fill: C.muted };

/** Short chart label: "5,2 млн", "128 тыс", "634". */
export function shortRub(value: number): string {
  return rubleAxisTick(value).replace(/\s?₽$/, "").replace("тыс.", "тыс");
}

/** Whole-ruble bar labels; round the source string HALF_UP before compact display. */
export function shortWholeRub(amount: string, signed = false): string {
  const kopecks = toKopecks(amount);
  const rubles = ((kopecks < 0n ? -kopecks : kopecks) + 50n) / 100n;
  const sign = rubles === 0n ? "" : kopecks < 0n ? "−" : signed ? "+" : "";
  return `${sign}${shortRub(Number(rubles))}`;
}

export type CapitalChartPoint = {
  key: string;
  label: string;
  fullLabel: string;
  amount: string | null;
  value: number | null;
};

/** A step of 1, 2 or 5 × 10^k, so compact tick labels stay exact. */
function niceStep(raw: number): number {
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
}

/** Axis from the data (not from zero) unless asked, with four even steps. */
export function niceAxis(
  values: number[],
  extra: number | null,
  fromZero: boolean,
): { domain: [number, number]; ticks: number[] } {
  const all = extra === null ? values : [...values, extra];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  const span = hi - lo || Math.abs(hi) * 0.1 || 1;
  if (fromZero) {
    lo = Math.min(0, lo);
  } else {
    const bottom = lo - span * 0.35;
    lo = lo >= 0 && bottom < 0 ? 0 : bottom;
  }
  hi += span * 0.08;
  const step = niceStep((hi - lo) / 4);
  const first = Math.floor(lo / step) * step;
  const last = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let tick = first; tick <= last + step / 2; tick += step) ticks.push(Math.round(tick));
  return { domain: [first, last], ticks };
}

function CapitalTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: CapitalChartPoint }>;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point || point.amount === null) return null;
  return (
    <div className={styles.tooltip}>
      <span>{point.fullLabel}</span>
      <strong className="money">{formatMoney(point.amount)}</strong>
    </div>
  );
}

export function CapitalAreaChart({
  data,
  goal,
}: {
  data: CapitalChartPoint[];
  goal: { value: number; label: string } | null;
}) {
  const values = data.flatMap((point) => (point.value === null ? [] : [point.value]));
  const top = values.length ? Math.max(...values) : 0;
  const bottom = values.length ? Math.min(...values) : 0;
  // A distant goal would flatten the line; it stays in the facts beside the chart.
  const showGoal = goal !== null && values.length > 0 && goal.value <= top * 1.5 && goal.value > 0;
  const axis = values.length
    ? niceAxis(values, showGoal ? goal.value : null, bottom <= 0)
    : { domain: [0, 1] as [number, number], ticks: [0, 1] };
  const domain = axis.domain;
  const lastIndex = data.reduce((last, point, index) => (point.value === null ? last : index), -1);

  function renderDot(props: { cx?: number; cy?: number; index?: number }): ReactElement {
    const { cx, cy, index } = props;
    if (cx == null || cy == null || data[index ?? -1]?.value == null) {
      return <g key={`dot-${index}`} />;
    }
    const last = index === lastIndex;
    return (
      <g key={`dot-${index}`}>
        <circle
          cx={cx}
          cy={cy}
          r={last ? 5 : 3}
          fill={last ? C.accent : C.surface}
          stroke={C.accent}
          strokeWidth={2}
        />
        {last ? (
          <text
            x={cx - 8}
            y={cy - 12}
            textAnchor="end"
            fill={C.ink}
            fontSize={12}
            fontWeight={600}
            className={styles.svgNum}
          >
            {shortRub(data[lastIndex].value ?? 0)}
          </text>
        ) : null}
      </g>
    );
  }

  return (
    <ResponsiveContainer height={236} width="100%">
      <AreaChart data={data} margin={{ bottom: 0, left: 0, right: 12, top: 18 }}>
        <defs>
          <linearGradient id="home-capital-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={C.accent} stopOpacity={0.18} />
            <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={C.line2} vertical={false} />
        <XAxis
          axisLine={false}
          dataKey="label"
          interval="preserveStartEnd"
          tick={TICK}
          tickLine={false}
          tickMargin={8}
        />
        <YAxis
          allowDataOverflow={false}
          axisLine={false}
          domain={domain}
          tick={TICK}
          tickFormatter={shortRub}
          tickLine={false}
          ticks={axis.ticks}
          width={58}
        />
        <Tooltip
          content={<CapitalTooltip />}
          cursor={{ stroke: C.faint, strokeDasharray: "3 3" }}
        />
        {showGoal ? (
          <ReferenceLine
            ifOverflow="extendDomain"
            label={{
              value: goal.label,
              position: "insideTopLeft",
              fill: C.muted,
              fontSize: 11,
            }}
            stroke={C.faint}
            strokeDasharray="5 5"
            strokeWidth={1.5}
            y={goal.value}
          />
        ) : null}
        <Area
          activeDot={{ r: 5, fill: C.accent, stroke: C.surface, strokeWidth: 2 }}
          baseValue={domain[0]}
          connectNulls={false}
          dataKey="value"
          dot={renderDot}
          fill="url(#home-capital-fill)"
          isAnimationActive={false}
          stroke={C.accent}
          strokeLinejoin="round"
          strokeWidth={2.5}
          type="linear"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export type PassiveChartPoint = {
  key: string;
  label: string;
  fullLabel: string;
  amount: string;
  value: number;
};

export function PassiveBarsChart({
  data,
  average,
  goal,
}: {
  data: PassiveChartPoint[];
  average: number | null;
  goal: number | null;
}) {
  const values = data.map((point) => point.value);
  const axis = niceAxis([0, ...values, average ?? 0], goal, true);
  const lastIndex = data.length - 1;
  return (
    <ResponsiveContainer height={200} width="100%">
      <BarChart data={data} margin={{ bottom: 0, left: 0, right: 8, top: 20 }}>
        <CartesianGrid stroke={C.line2} vertical={false} />
        <XAxis
          axisLine={false}
          dataKey="label"
          interval="preserveStartEnd"
          tick={TICK}
          tickLine={false}
          tickMargin={8}
        />
        <YAxis
          axisLine={false}
          domain={axis.domain}
          tick={TICK}
          tickFormatter={(value: number) => (value === 0 ? "0" : shortRub(value))}
          tickLine={false}
          ticks={axis.ticks}
          width={58}
        />
        <Tooltip
          cursor={false}
          formatter={(_value, _name, item) => [formatMoney(item.payload.amount), "Факт"]}
          labelFormatter={(_label, payload) => payload?.[0]?.payload?.fullLabel ?? ""}
        />
        <Bar dataKey="value" isAnimationActive={false} maxBarSize={48} radius={[5, 5, 0, 0]}>
          {data.map((point, index) => (
            <Cell fill={index === lastIndex ? C.accent : C.accentSoft} key={point.key} />
          ))}
          <LabelList
            content={(props) => {
              const { x, y, width, index } = props as {
                x?: number;
                y?: number;
                width?: number;
                index?: number;
              };
              if (index !== lastIndex || x == null || y == null || width == null) return null;
              return (
                <text
                  x={Number(x) + Number(width) / 2}
                  y={Number(y) - 6}
                  textAnchor="middle"
                  fill={C.ink}
                  fontSize={11}
                  fontWeight={600}
                  className={styles.svgNum}
                >
                  {shortRub(data[lastIndex].value)}
                </text>
              );
            }}
          />
        </Bar>
        {average !== null ? <ReferenceLine stroke={C.ink2} strokeWidth={1.5} y={average} /> : null}
        {goal !== null ? (
          <ReferenceLine stroke={C.faint} strokeDasharray="5 5" strokeWidth={1.5} y={goal} />
        ) : null}
      </BarChart>
    </ResponsiveContainer>
  );
}

export type WaterfallStep = {
  key: string;
  label: string;
  kind: "start" | "end" | "step";
  /** Lossy chart coordinate of the signed step or endpoint. */
  value: number;
  text: string;
};

/** Up to two lines of a category label, each shortened to fit a narrow column. */
function WaterfallTick(props: { x?: number; y?: number; payload?: { value?: string } }) {
  const { x = 0, y = 0, payload } = props;
  const words = String(payload?.value ?? "").split(/\s+/);
  const lines: string[] = [];
  for (const word of words) {
    const last = lines.length - 1;
    if (last >= 0 && `${lines[last]} ${word}`.length <= 10) lines[last] = `${lines[last]} ${word}`;
    else lines.push(word);
  }
  const shown = lines.slice(0, 2).map((line, index, all) => {
    const clipped = line.length > 10 ? `${line.slice(0, 9)}…` : line;
    return index === all.length - 1 && lines.length > 2 && !clipped.endsWith("…")
      ? `${clipped}…`
      : clipped;
  });
  return (
    <text fill={C.muted} fontSize={11} textAnchor="middle" x={x} y={y + 4}>
      {shown.map((line, index) => (
        <tspan dy={index === 0 ? 8 : 13} key={line} x={x}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

export function CapitalWaterfallChart({ steps }: { steps: WaterfallStep[] }) {
  // Only plain fields go into chart rows: Recharts forwards row keys to SVG.
  let running = 0;
  const levels: number[] = [];
  const spans = steps.map((step) => {
    if (step.kind === "step") {
      const start = running;
      running += step.value;
      levels.push(start, running);
      return { start, end: running };
    }
    running = step.value;
    levels.push(step.value);
    return { start: null, end: step.value };
  });
  const lo = Math.min(...levels);
  const hi = Math.max(...levels);
  const span = hi - lo || Math.abs(hi) * 0.05 || 1;
  const floor = lo - span * 0.9;
  const ceiling = hi + span * 0.12;
  const data = steps.map((step, index) => ({
    key: step.key,
    label: step.label,
    kind: step.kind,
    value: step.value,
    text: step.text,
    range: [spans[index].start ?? floor, spans[index].end],
  }));
  const fill = (bar: (typeof data)[number]) =>
    bar.kind === "start" ? C.base : bar.kind === "end" ? C.accent : bar.value < 0 ? C.neg : C.pos;
  return (
    <ResponsiveContainer height={236} width="100%">
      <BarChart data={data} margin={{ bottom: 0, left: 4, right: 4, top: 22 }}>
        <XAxis
          axisLine={false}
          dataKey="label"
          interval={0}
          height={46}
          tick={<WaterfallTick />}
          tickLine={false}
          tickMargin={8}
        />
        <YAxis domain={[floor, ceiling]} hide />
        <Bar dataKey="range" isAnimationActive={false} maxBarSize={56} minPointSize={2} radius={4}>
          {data.map((bar) => (
            <Cell fill={fill(bar)} key={bar.key} />
          ))}
          <LabelList
            content={(props) => {
              const { x, y, width, height, index } = props as {
                x?: number;
                y?: number;
                width?: number;
                height?: number;
                index?: number;
              };
              const bar = data[index ?? -1];
              if (!bar || x == null || y == null || width == null) return null;
              const top = Math.min(Number(y), Number(y) + Number(height ?? 0));
              return (
                <text
                  x={Number(x) + Number(width) / 2}
                  y={top - 6}
                  textAnchor="middle"
                  fill={C.ink2}
                  fontSize={11}
                  className={styles.svgNum}
                >
                  {bar.text}
                </text>
              );
            }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
