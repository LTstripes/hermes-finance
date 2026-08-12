import { useMemo } from "react";
import type { TooltipContentProps } from "recharts";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CapitalCompositionPoint } from "../../api/types";
import { formatMoney, formatPercent } from "../../lib/format";
import {
  buildCapitalCompositionSeries,
  type CapitalCompositionDatum,
} from "../../lib/capitalComposition";
import { EmptyState } from "../ui";

export type CapitalCompositionMode = "amount" | "share";

const CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Наличные", color: "#b9c4b9" },
  deposits: { label: "Депозиты", color: "#6f786f" },
  stocks: { label: "Акции", color: "#27734c" },
  bonds: { label: "Облигации", color: "#9a6a1d" },
  gold_other: { label: "Золото и прочее", color: "#172019" },
};

const FALLBACK_COLORS = ["#496f5a", "#8a9c8d", "#b27d35", "#4f5a52", "#a7b8a9"];

function metaFor(assetClass: string, index: number) {
  return (
    CLASS_META[assetClass] ?? {
      label: assetClass,
      color: FALLBACK_COLORS[index % FALLBACK_COLORS.length],
    }
  );
}

function axisPercent(value: number) {
  return formatPercent(String(Math.round(value)), { digits: 1 });
}

export function CapitalCompositionTooltip({
  active,
  payload,
  assetClasses,
  mode,
}: TooltipContentProps & { assetClasses: string[]; mode: CapitalCompositionMode }) {
  const datum = (payload?.[0]?.payload ?? undefined) as CapitalCompositionDatum | undefined;
  if (!active || !datum || datum.isGap) return null;

  const valueFor = (amount: string | null, share: string | null) =>
    mode === "amount" ? (amount == null ? "—" : formatMoney(amount)) : formatPercent(share);

  return (
    <div className="chart-tooltip composition-tooltip">
      <strong>{datum.label}</strong>
      <div className="composition-tooltip__breakdown">
        {assetClasses.map((assetClass, index) => {
          const meta = metaFor(assetClass, index);
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
  mode,
  points,
}: {
  assetClasses: string[];
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
  const labelByKey = new Map(series.map((datum) => [datum.key, datum.shortLabel]));

  return (
    <section
      aria-label="Состав ликвидных активов по закрытым месяцам"
      className="capital-composition-chart"
    >
      <ResponsiveContainer height={360} width="100%">
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
            tickFormatter={
              mode === "amount"
                ? (value: number) => `${Math.round(value).toLocaleString("ru-RU")} ₽`
                : axisPercent
            }
            tickLine={false}
            width={92}
          />
          <Tooltip
            content={(props) => (
              <CapitalCompositionTooltip {...props} assetClasses={assetClasses} mode={mode} />
            )}
            cursor={{ stroke: "#b9c4b9" }}
          />
          <Legend
            formatter={(value) =>
              value === "total"
                ? "Всего активов"
                : value === "net"
                  ? "Капитал нетто"
                  : metaFor(value, assetClasses.indexOf(value)).label
            }
          />
          {assetClasses.map((assetClass, index) => (
            <Area
              dataKey={assetClass}
              fill={metaFor(assetClass, index).color}
              fillOpacity={0.82}
              isAnimationActive={false}
              key={assetClass}
              name={assetClass}
              stackId="assets"
              stroke={metaFor(assetClass, index).color}
              type="linear"
            />
          ))}
          <Line
            connectNulls={false}
            dataKey="total"
            dot={false}
            isAnimationActive={false}
            name="Всего активов"
            stroke="#172019"
            strokeDasharray="5 4"
            strokeWidth={2}
            type="linear"
          />
          <Line
            connectNulls={false}
            dataKey="net"
            dot={{ fill: "#fff", r: 3, stroke: "#172019", strokeWidth: 2 }}
            isAnimationActive={false}
            name="Капитал нетто"
            stroke="#172019"
            strokeWidth={2}
            type="linear"
          />
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
