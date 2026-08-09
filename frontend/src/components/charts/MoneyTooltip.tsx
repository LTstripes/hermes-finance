import type { TooltipContentProps } from "recharts";

import { formatMoney } from "../../lib/format";
import type { ChartDatum } from "../../lib/chartData";

/** Shared chart tooltip: month label + formatted money amount. */
export function MoneyTooltip({ active, payload }: TooltipContentProps) {
  const datum = (payload?.[0]?.payload ?? undefined) as ChartDatum | undefined;
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
