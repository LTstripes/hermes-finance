/** Fabricated DTOs for Returns consumer/desktop tests only. No account data. */
import type { Context, Detail, Instrument, Metric, Overview, Period, Result } from "./model";
import type { Basket } from "./ReturnsBasket";
export function basketFixture(period: Period, categories = "brokerage,iis,deposits,gold"): Basket {
  const included = categories ? categories.split(",") : [];
  const source = included.includes("brokerage") && included.includes("iis");
  const subtotal = (value: string | null, total: number, method: string) => ({
    value_kopecks: value,
    covered_cells: value === null ? 0 : 1,
    total_cells: total,
    method,
    reason_codes: [],
  });
  return {
    period,
    categories: included,
    partial: true,
    result_kopecks: null,
    known_partial_subtotal_kopecks: source ? "-2000" : null,
    reason_codes: ["basket_full_result_unproven"],
    source_subtotal: subtotal(
      source ? "-2000" : null,
      source ? 2 : 0,
      "source_no_crossing_calendar_months",
    ),
    deposit_received_interest: subtotal(
      included.includes("deposits") ? "300" : null,
      included.includes("deposits") ? 1 : 0,
      "deposit_received_interest",
    ),
    components: included.includes("gold")
      ? [
          {
            id: "gold:unknown",
            label: "Физическое золото",
            category: "gold",
            basis: "unsupported",
            method: "physical_gold_period_unavailable",
            cells: [
              {
                period,
                value_kopecks: null,
                reason_codes: ["physical_gold_period_evidence_unavailable"],
              },
            ],
          },
        ]
      : [],
  };
}
export const april = { start: "2030-03-31", end: "2030-04-30" };
export const may = { start: "2030-04-30", end: "2030-05-31" };
export const contextFixture: Context = {
  source_periods: {
    "source:SYNTH-A": [april, may, { start: april.start, end: may.end }],
    "source:SYNTH-B": [april, may, { start: april.start, end: may.end }],
  },
  accounts: [
    { id: "source:SYNTH-A", label: "Учебный счёт А", basis: "statements" },
    { id: "source:SYNTH-B", label: "Учебный счёт Б", basis: "statements" },
    { id: "portfolio", label: "Общий портфель", basis: "accepted" },
  ],
  default_period: may,
  closed_periods: [april, may],
};
export function m(
  value: string | null,
  unit: Metric["unit"] = "kopecks",
  method = "instrument_return_v2",
): Metric {
  return {
    value,
    unit,
    method,
    reason_codes: value === null ? ["missing_endpoint"] : [],
    estimate: true,
  };
}
export function row(
  isin: string,
  name: string,
  value: string | null,
  rate: string | null,
  period = may,
): Instrument {
  return {
    isin,
    name,
    kind: "stock",
    period,
    pnl: m(value),
    rate: m(rate, "fraction", "modified_dietz"),
    coupons: m("0"),
    dividends: m("100000"),
    conditional: false,
  };
}
export function overviewFixture(scope = "source:SYNTH-A", period: Period = may): Overview {
  const selected: Result = {
    period,
    pnl: m(scope === "source:SYNTH-B" ? "-175025" : "4812567", "kopecks", "source_monthly"),
    rate: m("0.01725", "fraction", "modified_dietz"),
    coupons: m("125000", "kopecks", "credited_payments"),
    dividends: m("186025", "kopecks", "credited_payments"),
  };
  return {
    scope,
    selected,
    all_history: { ...selected, period: { start: "2029-12-31", end: may.end }, pnl: m(null) },
    history: [
      { ...selected, period: { start: "2029-12-31", end: "2030-01-31" }, pnl: m("0") },
      { ...selected, period: { start: "2030-01-31", end: "2030-02-28" }, pnl: m("-2400000") },
      { ...selected, period: { start: "2030-02-28", end: "2030-03-31" }, pnl: m(null) },
      { ...selected, period: april, pnl: m("3200000") },
      { ...selected, period: may },
    ],
    periods: [april, may, { start: "2029-12-31", end: may.end }],
    instruments: [
      row("RU000A000001", "Северные технологии", "2600080", "0.10000000000000000001", period),
      row(
        "RU000A000002",
        "Горизонт — проданная бумага",
        "1800000",
        "0.10000000000000000002",
        period,
      ),
      row("RU000A000003", "Меридиан", "-200010", "-0.03", period),
      row("RU000A000004", "Равновесие", "0", "0", period),
      {
        ...row("RU000A000005", "Учебная облигация", null, null, period),
        kind: "bond",
        conditional: true,
        coupons: m("125000"),
      },
    ],
    instrument_reason_codes: [],
    proof_status: "current",
  };
}
export function detailFixture(
  scope = "source:SYNTH-A",
  period = may,
  isin = "RU000A000002",
): Detail {
  return {
    ...row(isin, "Горизонт — проданная бумага", "1800000", "0.1", period),
    scope,
    opening_quantity: "10",
    closing_quantity: "0",
    buys: m("0"),
    sells: m("11800000"),
    conditional_pnl: m(null),
    conditional_rate: m(null, "fraction"),
    reason_codes: [],
    events: [
      {
        ordinal: 0,
        kind: "SELL",
        date: "2030-05-12",
        cash_date: "2030-05-14",
        quantity_date: "2030-05-14",
        quantity: "-10",
        amount: m("11800000"),
        counted: true,
      },
    ],
  };
}

/** Two fabricated calendar years for selection/pagination regressions. */
export const longHistoryPeriods: Period[] = Array.from({ length: 24 }, (_, index) => {
  const year = 2029 + Math.floor(index / 12);
  const month = index % 12;
  const dayBefore = (value: Date) =>
    new Date(value.getTime() - 86400000).toISOString().slice(0, 10);
  return {
    start: dayBefore(new Date(Date.UTC(year, month, 1))),
    end: dayBefore(new Date(Date.UTC(year, month + 1, 1))),
  };
});
export const longHistoryContext: Context = {
  ...contextFixture,
  default_period: longHistoryPeriods[23],
  closed_periods: longHistoryPeriods,
  source_periods: Object.fromEntries(
    ["source:SYNTH-A", "source:SYNTH-B"].map((scope) => [
      scope,
      [
        ...longHistoryPeriods,
        { start: longHistoryPeriods[0].start, end: longHistoryPeriods[23].end },
      ],
    ]),
  ),
};
export function longHistoryOverview(scope: string, period: Period): Overview {
  const base = overviewFixture(scope, period);
  const selectedResult = (p: Period): Result => {
    const ordinal = longHistoryPeriods.findIndex((r) => r.start === p.start && r.end === p.end) + 1;
    return {
      ...base.selected,
      period: p,
      pnl: m(String(ordinal * 10000), "kopecks", "source_monthly"),
      coupons: m(String(ordinal * 100), "kopecks", "credited_payments"),
      dividends: m(String(ordinal * 200), "kopecks", "credited_payments"),
    };
  };
  const selected = selectedResult(period);
  return {
    ...base,
    selected,
    all_history: base.all_history && {
      ...base.all_history,
      period: { start: longHistoryPeriods[0].start, end: longHistoryPeriods[23].end },
    },
    history: longHistoryPeriods.map(selectedResult),
    periods: longHistoryPeriods,
    instruments: [
      { ...base.instruments[0], pnl: { ...base.instruments[0].pnl, value: selected.pnl.value } },
      { ...base.instruments[2], pnl: m(String(-BigInt(selected.pnl.value ?? "0") / 2n)) },
    ],
  };
}
