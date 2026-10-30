/** Fabricated overall DTOs only; no runtime account data. */
import { m, may, april, detailFixture } from "./fixtures";
import type { InstrumentCard, Income, IncomeKind } from "./cards";
import type { Overall } from "./overall";
export function overallFixture(): Overall {
  const a = {
    scope: "source:SYNTH-A",
    canonical_account_id: 3,
    details_loaded: false,
    label: "Учебный счёт А",
    period: may,
    pnl: m("1200"),
    rate: m("0.12", "fraction"),
    coupons: m("0"),
    dividends: m("300"),
  };
  const b = {
    ...a,
    scope: "source:SYNTH-B",
    canonical_account_id: 4,
    label: "Учебный счёт Б",
    period: april,
    pnl: m("-400"),
    rate: m("-0.04", "fraction"),
  };
  return {
    contract_version: "returns_overall_v1",
    dividend_income: {
      known_total: m("700", "kopecks", "known_source_history_dividends"),
      partial: true,
      selected_accounts: 2,
      included_accounts: 1,
      accounts: [
        {
          scope: a.scope,
          label: a.label,
          period: may,
          amount: m("700"),
          proof_status: "current",
          included: true,
          exclusion_reason: null,
          reason_codes: [],
        },
      ],
      reason_codes: ["known_source_history_dividends_only"],
    },
    coupon_income: {
      known_total: m("3500", "kopecks", "known_source_history_coupons"),
      partial: true,
      selected_accounts: 2,
      included_accounts: 1,
      accounts: [
        {
          scope: a.scope,
          label: a.label,
          period: may,
          amount: m("3500"),
          proof_status: "current",
          included: true,
          exclusion_reason: null,
          reason_codes: [],
        },
        {
          scope: b.scope,
          label: b.label,
          period: april,
          amount: m(null),
          proof_status: "stale",
          included: false,
          exclusion_reason: "source_proof_stale",
          reason_codes: ["source_proof_stale"],
        },
      ],
      reason_codes: ["known_source_history_coupons_only"],
    },
    mixed_result: {
      known_result: m("800"),
      rate: m(null, "fraction"),
      selected_component_count: 3,
      available_component_count: 3,
      included_component_count: 2,
      reason_codes: ["known_components_only"],
      components: [
        {
          id: "brokerage:A",
          category: "brokerage",
          label: "Учебный счёт А: компонент",
          selected: true,
          available: true,
          included: true,
          amount: a.pnl,
          interval: may,
          valuation_date: null,
          coverage: { status: "supported", reason_codes: [] },
          method: "source_account_reconciliation",
          authority: "source_only",
          exclusion_reason: null,
        },
        {
          id: "brokerage:B",
          category: "brokerage",
          label: "Учебный счёт Б: компонент",
          selected: true,
          available: true,
          included: true,
          amount: b.pnl,
          interval: april,
          valuation_date: null,
          coverage: { status: "supported", reason_codes: [] },
          method: "source_account_reconciliation",
          authority: "source_only",
          exclusion_reason: null,
        },
        {
          id: "gold:synthetic",
          category: "gold",
          label: "Золото с неподтверждённым пересечением",
          selected: true,
          available: true,
          included: false,
          amount: m("-20000"),
          interval: null,
          valuation_date: may.end,
          coverage: { status: "partial", reason_codes: ["synthetic_overlap_unproven"] },
          method: "saved_unrealized",
          authority: "accepted_snapshot",
          exclusion_reason: "synthetic_overlap_unproven",
        },
      ],
    },
    overall: {
      pnl: m(null),
      rate: m(null, "fraction"),
      partial: true,
      reason_codes: ["overall_aggregation_pending_review"],
    },
    source_accounts: [a, b].map((account) => ({
      scope: account.scope,
      label: account.label,
      period: account.period,
      result: {
        period: account.period,
        pnl: account.pnl,
        rate: account.rate,
        coupons: account.coupons,
        dividends: account.dividends,
      },
      proof_status: "current",
      reason_codes: [],
      instrument_count: 2,
    })),
    instruments: [
      {
        isin: "RU000A000002",
        name: "Учебная акция",
        kind: "stock",
        accounts: [a, b],
        reason_codes: [],
      },
      {
        isin: "RU000A000003",
        name: "Проданная облигация",
        kind: "bond",
        accounts: [a],
        reason_codes: [],
      },
    ],
    deposits: {
      interest: m("0"),
      partial: true,
      periods: [
        { period: may, status: "closed", rows: 1 },
        { period: april, status: "draft", rows: 0 },
      ],
      reason_codes: ["deposit_snapshot_missing"],
    },
    gold: {
      snapshots: [
        {
          account_id: 10,
          instrument_id: 20,
          label: "Учебное золото",
          date: may.end,
          quantity: "2.500",
          market_value: m("120000"),
          cost_basis: m("100000"),
          unrealized_result: m("20000"),
          cost_return: m("0.20", "fraction"),
        },
      ],
      period_result: m(null),
      reason_codes: ["physical_gold_period_evidence_unavailable"],
    },
    reason_codes: ["unsupported_synthetic_category"],
  };
}

export function instrumentCardFixture(isin = "RU000A000002"): InstrumentCard {
  const detailA = detailFixture("source:SYNTH-A", may, isin);
  const detailB = detailFixture("source:SYNTH-B", april, isin);
  detailA.pnl = m("1200");
  detailA.rate = m("0.12", "fraction", "modified_dietz");
  detailB.pnl = m("-400");
  detailB.rate = m("-0.04", "fraction", "modified_dietz");
  detailB.closing_quantity = detailB.analysis.closing.quantity = "2";
  detailB.analysis.closing.reported_value_kopecks = "1000";
  for (const event of detailB.analysis.events) {
    event.event_date = "2030-04-12";
    event.trade_time = "2030-04-12 10:30:00";
    event.cash_settlement_date = event.depository_settlement_date = "2030-04-14";
  }
  return {
    contract_version: "returns_instrument_card_v1",
    isin,
    name: isin === "RU000A000003" ? "Проданная облигация" : "Учебная акция",
    kind: "stock",
    summary: {
      quantity: { value: "2", partial: true, reason_codes: [] },
      reported_value: m("1000"),
      valuation_dates: [may.end, april.end],
      pnl: m("800"),
      coupons: m("3500"),
      dividends: m("700"),
      valuation_and_trades: m("-3400"),
      redemption: m("0"),
      costs: m("0"),
      taxes: m("0"),
      rate: { ...m(null, "fraction"), reason_codes: ["combined_rate_not_calculated"] },
      partial: true,
      reason_codes: ["account_periods_differ"],
    },
    accounts: [
      {
        scope: "source:SYNTH-A",
        label: "Учебный счёт А",
        canonical_account_id: 3,
        period: may,
        proof_status: "current",
        included: true,
        exclusion_reason: null,
        reason_codes: [],
        detail: detailA,
      },
      {
        scope: "source:SYNTH-B",
        label: "Учебный счёт Б",
        canonical_account_id: 4,
        period: april,
        proof_status: "current",
        included: true,
        exclusion_reason: null,
        reason_codes: [],
        detail: detailB,
      },
    ],
    reason_codes: [],
  };
}
export function incomeFixture(kind: IncomeKind = "coupon"): Income {
  const summary =
    kind === "coupon" ? overallFixture().coupon_income : overallFixture().dividend_income;
  const amount = m(kind === "coupon" ? "3500" : "700");
  return {
    contract_version: "returns_income_v1",
    kind,
    summary,
    instruments: [
      {
        isin: "RU000A000002",
        name: "Учебная акция",
        amount,
        accounts: [{ scope: "source:SYNTH-A", label: "Учебный счёт А", period: may, amount }],
      },
    ],
    events: [
      {
        scope: "source:SYNTH-A",
        label: "Учебный счёт А",
        isin: "RU000A000002",
        name: "Учебная акция",
        date: "2030-05-15",
        amount,
      },
    ],
    reason_codes: [],
  };
}
