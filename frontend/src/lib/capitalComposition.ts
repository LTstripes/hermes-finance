import type { CapitalCompositionPoint } from "../api/types";
import { formatMonth } from "./format";
import { moneySharePercent, moneyToChartNumber, toKopecks } from "./money";
import { isContiguousMonth } from "./chartData";

export type CapitalCompositionDatum = {
  key: string;
  year: number;
  month: number;
  label: string;
  shortLabel: string;
  isGap: boolean;
  amounts: Record<string, string | null>;
  shares: Record<string, string | null>;
  amountCoordinates: Record<string, number | null>;
  shareCoordinates: Record<string, number | null>;
  totalAmount: string | null;
  debtsAmount: string | null;
  netAmount: string | null;
  totalCoordinate: number | null;
  netCoordinate: number | null;
  totalShare: string | null;
  netShare: string | null;
};

function signedSharePercent(partAmount: string, totalAmount: string): string | null {
  const part = toKopecks(partAmount);
  const total = toKopecks(totalAmount);
  if (total <= 0n) return null;

  const negative = part < 0n;
  const absolutePart = negative ? -part : part;
  const scale = 10n;
  const numerator = absolutePart * 100n * scale;
  const quotient = numerator / total;
  const remainder = numerator % total;
  const rounded = remainder * 2n >= total ? quotient + 1n : quotient;
  const major = rounded / scale;
  const fraction = String(rounded % scale).padStart(1, "0");
  return `${negative ? "-" : ""}${major}.${fraction}`;
}

function createGap(index: number): CapitalCompositionDatum {
  return {
    key: `gap-${index}`,
    year: 0,
    month: 0,
    label: "",
    shortLabel: "",
    isGap: true,
    amounts: {},
    shares: {},
    amountCoordinates: {},
    shareCoordinates: {},
    totalAmount: null,
    debtsAmount: null,
    netAmount: null,
    totalCoordinate: null,
    netCoordinate: null,
    totalShare: null,
    netShare: null,
  };
}

/**
 * Adapt exact API money strings to chart data. Missing calendar months become
 * explicit null rows; no month or financial value is synthesized from neighbors.
 */
export function buildCapitalCompositionSeries(
  points: CapitalCompositionPoint[],
  assetClasses: string[],
): CapitalCompositionDatum[] {
  const data: CapitalCompositionDatum[] = [];
  let previous: { year: number; month: number } | null = null;

  for (const point of points) {
    if (previous != null && !isContiguousMonth(previous, point)) {
      data.push(createGap(data.length));
    }

    const allocation = new Map(
      point.allocation.map((item) => [item.asset_class, item.amount.amount]),
    );
    const totalAmount = point.liquid_assets_total.amount;
    const netAmount = point.liquid_capital_net.amount;
    const hasPositiveTotal = toKopecks(totalAmount) > 0n;
    const amounts = Object.fromEntries(
      assetClasses.map((assetClass) => [assetClass, allocation.get(assetClass) ?? "0.00"]),
    );
    const shares = Object.fromEntries(
      assetClasses.map((assetClass) => {
        const amount = amounts[assetClass] ?? "0.00";
        return [assetClass, hasPositiveTotal ? moneySharePercent(amount, totalAmount, 1) : null];
      }),
    );

    data.push({
      key: `${point.year}-${String(point.month).padStart(2, "0")}`,
      year: point.year,
      month: point.month,
      label: formatMonth(point.year, point.month),
      shortLabel: `${point.month}/${point.year}`,
      isGap: false,
      amounts,
      shares,
      amountCoordinates: Object.fromEntries(
        assetClasses.map((assetClass) => [
          assetClass,
          moneyToChartNumber(amounts[assetClass] ?? "0.00"),
        ]),
      ),
      shareCoordinates: Object.fromEntries(
        assetClasses.map((assetClass) => {
          const share = shares[assetClass];
          return [assetClass, share == null ? null : Number(share)];
        }),
      ),
      totalAmount,
      debtsAmount: point.included_debts.amount,
      netAmount,
      totalCoordinate: moneyToChartNumber(totalAmount),
      netCoordinate: moneyToChartNumber(netAmount),
      totalShare: hasPositiveTotal ? "100.0" : null,
      netShare: hasPositiveTotal ? signedSharePercent(netAmount, totalAmount) : null,
    });
    previous = { year: point.year, month: point.month };
  }

  return data;
}
