import { useMemo } from "react";
import type { TooltipContentProps } from "recharts";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CssResponsiveContainer as ResponsiveContainer } from "./CssResponsiveContainer";
import type { CapitalCompositionPoint } from "../../api/types";
import { PortfolioCoverageNote } from "../PortfolioCoverageNote";
import { axisMoney } from "../../lib/chartData";
import { formatMoney, formatPercent } from "../../lib/format";
import {
  buildCapitalCompositionSeries,
  type CapitalCompositionDatum,
} from "../../lib/capitalComposition";
import { classMeta } from "../../ui-v2/assetClasses";
import { EmptyState } from "../ui";

export type CapitalCompositionMode = "amount" | "share";

const CLASS_META: Record<string, { color: string }> = {
  cash: { color: "#b9c4b9" },
  deposits: { color: "#6f786f" },
  stocks: { color: "#27734c" },
  bonds: { color: "#9a6a1d" },
  gold_other: { color: "#172019" },
};

/** --ink of styles/tokens.css; SVG attributes need a literal colour. */
const INK = "#152131";

const SHORT_MONTHS = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];

const FALLBACK_COLORS = ["#496f5a", "#8a9c8d", "#b27d35", "#4f5a52", "#a7b8a9"];

function metaFor(assetClass: string, index: number, classColors?: Record<string, string>) {
  const base =
    CLASS_META[assetClass] ??
    ({
      color: FALLBACK_COLORS[index % FALLBACK_COLORS.length],
    } as { color: string });
  const override = classColors?.[assetClass];
  return { label: classMeta(assetClass).label, color: override ?? base.color };
}

function axisPercent(value: number) {
  return formatPercent(String(Math.round(value)), { digits: 1 });
}

export function CapitalCompositionTooltip({
  active,
  payload,
  assetClasses,
  classColors,
  mode,
  points,
}: TooltipContentProps & {
  assetClasses: string[];
  classColors?: Record<string, string>;
  mode: CapitalCompositionMode;
  points?: CapitalCompositionPoint[];
}) {
  const datum = (payload?.[0]?.payload ?? undefined) as CapitalCompositionDatum | undefined;
  if (!active || !datum || datum.isGap) return null;

  const valueFor = (amount: string | null, share: string | null) =>
    mode === "amount" ? (amount == null ? "—" : formatMoney(amount)) : formatPercent(share);

  return (
    <div className="chart-tooltip composition-tooltip">
      <strong>{datum.label}</strong>
      <div className="composition-tooltip__breakdown">
        {assetClasses.map((assetClass, index) => {
          const meta = metaFor(assetClass, index, classColors);
          const amount = datum.amounts[assetClass] ?? null;
          const share = datum.shares[assetClass] ?? null;
          return (
            <div className="composition-tooltip__row" key={assetClass}>
              <span>
                <i aria-hidden="true" style={{ background: meta.color }} />
                {meta.label}
              </span>
              <strong>{valueFor(amount, share)}</strong>
            </div>
          );
        })}
      </div>
      <div className="composition-tooltip__totals">
        <div className="composition-tooltip__row">
          <span>Всего активов</span>
          <strong>{valueFor(datum.totalAmount, datum.totalShare)}</strong>
        </div>
        <div className="composition-tooltip__row">
          <span>Капитал нетто</span>
          <strong>{valueFor(datum.netAmount, datum.netShare)}</strong>
        </div>
        <PortfolioCoverageNote
          coverage={
            points?.find((point) => point.reporting_month_id === datum.reportingMonthId)
              ?.portfolio_source_coverage
          }
          month={points?.find((point) => point.reporting_month_id === datum.reportingMonthId)}
        />
        <div className="composition-tooltip__row composition-tooltip__debt">
          <span>Включённые долги</span>
          <strong>{formatMoney(datum.debtsAmount)}</strong>
        </div>
      </div>
    </div>
  );
}

export function CapitalCompositionChart({
  assetClasses,
  classColors,
  highlightMonthId,
  mode,
  points,
  height = 360,
}: {
  assetClasses: string[];
  height?: number;
  /** Optional presentation-only palette override; v1 keeps its own colours. */
  classColors?: Record<string, string>;
  /**
   * Presentation-only marker for one already-rendered closed report. It never
   * changes the series, the ordering or any value; a gap can never be marked.
   */
  highlightMonthId?: number;
  mode: CapitalCompositionMode;
  points: CapitalCompositionPoint[];
}) {
  const series = useMemo(
    () => buildCapitalCompositionSeries(points, assetClasses),
    [assetClasses, points],
  );

  if (series.length === 0) {
    return (
      <EmptyState
        description="График появится после закрытия первого месяца. Черновики не входят в историческую динамику."
        title="Нет закрытых месяцев"
      />
    );
  }

  const chartData = series.map((datum) => ({
    ...datum,
    ...Object.fromEntries(
      assetClasses.map((assetClass) => [
        assetClass,
        mode === "amount"
          ? datum.amountCoordinates[assetClass]
          : datum.shareCoordinates[assetClass],
      ]),
    ),
    total:
      mode === "amount"
        ? datum.totalCoordinate
        : datum.totalShare == null
          ? null
          : Number(datum.totalShare),
    net:
      mode === "amount"
        ? datum.netCoordinate
        : datum.netShare == null
          ? null
          : Number(datum.netShare),
  }));
  const hasGap = series.some((datum) => datum.isGap);
  // One month format with the Home chart: "апр 2031" (#1079).
  const labelByKey = new Map(
    series.map((datum) => [
      datum.key,
      datum.isGap ? "" : `${SHORT_MONTHS[datum.month - 1] ?? ""} ${datum.year}`.trim(),
    ]),
  );
  const highlightKey =
    highlightMonthId == null
      ? null
      : (series.find((datum) => datum.reportingMonthId === highlightMonthId)?.key ?? null);

  return (
    <section
      aria-label="Состав ликвидных активов по закрытым месяцам"
      className="capital-composition-chart"
      data-highlight-key={highlightKey ?? undefined}
    >
      <ResponsiveContainer height={height}>
        <AreaChart
          accessibilityLayer
          data={chartData}
          margin={{ bottom: 4, left: 8, right: 16, top: 12 }}
        >
          <CartesianGrid stroke="var(--line-soft)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            axisLine={false}
            dataKey="key"
            interval="preserveStartEnd"
            tickFormatter={(key: string) => labelByKey.get(key) ?? ""}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            domain={mode === "share" ? [0, "auto"] : ["auto", "auto"]}
            tickFormatter={mode === "amount" ? axisMoney : axisPercent}
            tickLine={false}
            width={mode === "amount" ? 64 : 52}
          />
          <Tooltip
            content={(props) => (
              <CapitalCompositionTooltip
                {...props}
                assetClasses={assetClasses}
                classColors={classColors}
                mode={mode}
                points={points}
              />
            )}
            cursor={{ stroke: "#a3abb5" }}
          />
          <Legend
            formatter={(value) => (
              <span className="capital-composition-chart__legend">
                {value === "total"
                  ? "Всего активов"
                  : value === "net"
                    ? "Капитал нетто"
                    : metaFor(value, assetClasses.indexOf(value), classColors).label}
              </span>
            )}
          />
          {assetClasses.map((assetClass, index) => (
            <Area
              dataKey={assetClass}
              fill={metaFor(assetClass, index, classColors).color}
              fillOpacity={0.82}
              isAnimationActive={false}
              key={assetClass}
              name={assetClass}
              stackId="assets"
              stroke={metaFor(assetClass, index, classColors).color}
              type="linear"
            />
          ))}
          <Line
            connectNulls={false}
            dataKey="total"
            dot={false}
            isAnimationActive={false}
            name="Всего активов"
            stroke={INK}
            strokeDasharray="5 4"
            strokeWidth={2}
            type="linear"
          />
          <Line
            connectNulls={false}
            dataKey="net"
            dot={{ fill: "#fff", r: 3, stroke: INK, strokeWidth: 2 }}
            isAnimationActive={false}
            name="Капитал нетто"
            stroke={INK}
            strokeWidth={2}
            type="linear"
          />
          {highlightKey ? (
            <ReferenceLine
              className="capital-composition-chart__highlight"
              ifOverflow="extendDomain"
              label={{
                fill: "#244f83",
                fontSize: 11,
                position: "insideTopRight",
                value: "Этот отчёт",
              }}
              stroke="#244f83"
              strokeDasharray="4 3"
              strokeWidth={2}
              x={highlightKey}
            />
          ) : null}
        </AreaChart>
      </ResponsiveContainer>
      <div className="capital-composition-chart__summary">
        <span>
          Стек показывает ликвидные активы; линия «Капитал нетто» учитывает включённые долги.
        </span>
        {hasGap ? (
          <span>
            Пропуски означают неизвестную историю — данные между месяцами не интерполируются.
          </span>
        ) : null}
      </div>
    </section>
  );
}
