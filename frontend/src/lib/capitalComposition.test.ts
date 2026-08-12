import { describe, expect, it } from "vitest";

import type { CapitalCompositionPoint } from "../api/types";
import { rub } from "./money";
import { buildCapitalCompositionSeries } from "./capitalComposition";

const classes = ["cash", "deposits", "stocks", "bonds", "gold_other"];

function point(year: number, month: number, total: string, net: string): CapitalCompositionPoint {
  return {
    reporting_month_id: year * 100 + month,
    year,
    month,
    snapshot_date: `${year}-${String(month).padStart(2, "0")}-28`,
    allocation: [
      { asset_class: "cash", amount: rub("100.00") },
      { asset_class: "deposits", amount: rub("300.00") },
      { asset_class: "stocks", amount: rub("0.00") },
      { asset_class: "bonds", amount: rub("100.00") },
      { asset_class: "gold_other", amount: rub("0.00") },
    ],
    liquid_assets_total: rub(total),
    included_debts: rub("50.00"),
    liquid_capital_net: rub(net),
  };
}

describe("buildCapitalCompositionSeries", () => {
  it("keeps canonical known zeroes and exact total/net DTO values", () => {
    const [datum] = buildCapitalCompositionSeries([point(2031, 1, "500.00", "450.00")], classes);

    expect(datum.amounts.stocks).toBe("0.00");
    expect(datum.amounts.gold_other).toBe("0.00");
    expect(datum.shares.deposits).toBe("60.0");
    expect(datum.totalAmount).toBe("500.00");
    expect(datum.netAmount).toBe("450.00");
    expect(datum.totalShare).toBe("100.0");
    expect(datum.netShare).toBe("90.0");
  });

  it("inserts a null gap for unknown calendar history without backfilling it", () => {
    const series = buildCapitalCompositionSeries(
      [point(2031, 1, "500.00", "450.00"), point(2031, 3, "600.00", "550.00")],
      classes,
    );

    expect(series).toHaveLength(3);
    expect(series[1]).toMatchObject({ isGap: true, label: "", totalAmount: null, netAmount: null });
    expect(series[1].amountCoordinates).toEqual({});
    expect(series[2].key).toBe("2031-03");
  });

  it("does not invent percentage values for an all-zero closed month", () => {
    const zeroPoint = point(2031, 1, "0.00", "0.00");
    const [datum] = buildCapitalCompositionSeries([zeroPoint], classes);

    expect(datum.shares).toEqual({
      cash: null,
      deposits: null,
      stocks: null,
      bonds: null,
      gold_other: null,
    });
    expect(datum.totalShare).toBeNull();
    expect(datum.netShare).toBeNull();
  });
});
