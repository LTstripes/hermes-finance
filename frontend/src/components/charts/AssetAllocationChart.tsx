import { useMemo } from "react";
import type { TooltipContentProps } from "recharts";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { AssetAllocationPoint } from "../../api/types";
import { formatMoney, formatPercent } from "../../lib/format";
import {
  moneyAmount,
  moneySharePercent,
  moneyToChartNumber,
  sumMoneyAmounts,
  toKopecks,
} from "../../lib/money";
import { EmptyState, Td, Th } from "../ui";

const ASSET_CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Наличные", color: "#b9c4b9" },
  deposits: { label: "Депозиты", color: "#6f786f" },
  stocks: { label: "Акции", color: "#27734c" },
  bonds: { label: "Облигации", color: "#9a6a1d" },
  gold_other: { label: "Золото и прочее", color: "#172019" },
};

type Slice = {
  key: string;
  label: string;
  color: string;
  value: number;
  amount: string;
};

function buildSlices(allocation: AssetAllocationPoint[]): Slice[] {
  return allocation.flatMap((point) => {
    const meta = ASSET_CLASS_META[point.asset_class] ?? {
      label: point.asset_class,
      color: "#6f786f",
    };
    const amount = moneyAmount(point.amount);
    if (toKopecks(amount) <= 0n) {
      return [];
    }
    return [
      {
        key: point.asset_class,
        label: meta.label,
        color: meta.color,
        // Recharts arc coordinate only; all totals/shares stay exact.
        value: moneyToChartNumber(amount),
        amount,
      },
    ];
  });
}

function AllocationTooltip({ active, payload }: TooltipContentProps) {
  const datum = (payload?.[0]?.payload ?? undefined) as Slice | undefined;
  if (!active || !datum) {
    return null;
  }
  return (
    <div className="chart-tooltip">
      <strong>{datum.label}</strong>
      <span className="chart-tooltip__amount">{formatMoney(datum.amount)}</span>
    </div>
  );
}

export function AssetAllocationChart({ allocation }: { allocation: AssetAllocationPoint[] }) {
  const slices = useMemo(() => buildSlices(allocation), [allocation]);

  if (slices.length === 0) {
    return (
      <EmptyState
        description="Добавь активы в закрытые месяцы — диаграмма появится здесь."
        title="Нет активов"
      />
    );
  }

  const totalAmount = sumMoneyAmounts(slices.map((s) => s.amount));

  return (
    <section aria-label="Распределение ликвидных активов по классам" className="asset-allocation">
      <div className="asset-allocation__chart">
        <ResponsiveContainer height={240} width="100%">
          <PieChart accessibilityLayer>
            <Pie
              data={slices}
              dataKey="value"
              innerRadius="55%"
              isAnimationActive={false}
              nameKey="label"
              outerRadius="85%"
              paddingAngle={2}
              strokeWidth={0}
            >
              {slices.map((slice) => (
                <Cell fill={slice.color} key={slice.key} />
              ))}
            </Pie>
            <Tooltip content={(props) => <AllocationTooltip {...props} />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <table className="asset-allocation__table">
        <caption className="visually-hidden">Распределение активов по классам</caption>
        <thead>
          <tr>
            <Th>Класс</Th>
            <Th numeric>Сумма</Th>
            <Th numeric>Доля</Th>
          </tr>
        </thead>
        <tbody>
          {slices.map((slice) => (
            <tr key={slice.key}>
              <Td>
                <span
                  aria-hidden="true"
                  className="asset-allocation__dot"
                  style={{ background: slice.color }}
                />
                {slice.label}
              </Td>
              <Td numeric>{formatMoney(slice.amount)}</Td>
              <Td numeric>{formatPercent(moneySharePercent(slice.amount, totalAmount, 1))}</Td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <Td>Итого</Td>
            <Td numeric>{formatMoney(totalAmount)}</Td>
            <Td numeric>100%</Td>
          </tr>
        </tfoot>
      </table>
    </section>
  );
}
