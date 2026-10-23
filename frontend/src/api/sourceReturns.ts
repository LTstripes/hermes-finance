import { apiRequest } from "./client";

export type ReturnGap = {
  code: string;
  intake_id: number | null;
  month: string | null;
  source_reference: string | null;
  isin?: string | null;
};
export type PeriodTotals = {
  contributions_kopecks: number | null;
  withdrawals_kopecks: number | null;
  growth_kopecks: number | null;
  chained_return: string | null;
  xirr_annualized_return: string | null;
  xirr_period_return: string | null;
  assumptions_used: boolean;
  missing_endpoint: boolean;
  approximate: true;
  chain_reason_codes: string[];
  growth_reason_codes: string[];
  xirr_reason_codes: string[];
};
export type MonthlyReturn = {
  opening_date: string;
  closing_date: string;
  opening_kopecks: number | null;
  closing_kopecks: number | null;
  contributions_kopecks: number | null;
  withdrawals_kopecks: number | null;
  growth_kopecks: number | null;
  modified_dietz_return: string | null;
  assumptions_used: boolean;
  missing_endpoint: boolean;
  reason_codes: string[];
  approximate: true;
  intake_ids: number[];
  flags: string[];
  coupons_kopecks: number | null;
  dividends_kopecks: number | null;
  income_assumptions_used: boolean;
};
export type SourceReturnFlow = {
  event_date: string;
  amount_kopecks: number;
  status: "assumed" | "confirmed";
  included: boolean;
  source_references: string[];
  classification: string;
};
export type SourceMonthlyReturns = {
  source_account: string;
  months: MonthlyReturn[];
  defaults_applied: SourceReturnFlow[];
  period: PeriodTotals;
  gaps: ReturnGap[];
  authority: "provisional";
  financial_authority: "none";
  currency: "RUB";
  approximate: true;
};
export type InstrumentTotals = {
  buys_cost_kopecks: number | null;
  sells_proceeds_kopecks: number | null;
  price_effect_kopecks: number | null;
  coupons_kopecks: number | null;
  dividends_kopecks: number | null;
  income_kopecks: number | null;
  assumed_income_kopecks: number | null;
  confirmed_income_kopecks: number | null;
  total_kopecks: number | null;
  capital_base_kopecks: number | null;
  /** Legacy simple percentage: 100 * total / (V0 + buys). */
  return_percent: string | null;
  income_assumptions_used: boolean;
  income_complete: boolean;
  flags: string[];
  approximate: boolean;
};
export type InstrumentMetric<T> = {
  value: T | null;
  status: "supported" | "provisional" | "partial" | "unavailable";
  reason_codes: string[];
  assumptions: string[];
};
export type InstrumentDietz = InstrumentMetric<string> & {
  /** Decimal FRACTION, 0.1 = 10%; never the legacy percentage. */
  method: "modified_dietz";
  approximate: true;
  annualized: false;
  capital_days: number | null;
};
export type InstrumentCashLeg = {
  role: string;
  date: string;
  account_cash_kopecks: number;
  instrument_flow_kopecks: number;
  source_references: string[];
  ownership: string;
};
export type InstrumentEvent = {
  event_key: string;
  provider: string;
  native_source_account: string;
  isin: string | null;
  kind: "BUY" | "SELL" | "COUPON" | "DIVIDEND" | "FEE" | "TAX" | "REDEMPTION" | "UNRESOLVED";
  source_references: string[];
  event_date: string | null;
  native_identity: string | null;
  native_ids: string[];
  trade_time: string | null;
  cash_settlement_date: string | null;
  depository_settlement_date: string | null;
  quantity_delta: string | null;
  unit_price: string | null;
  price_unit: "RUB_PER_UNIT" | "PERCENT_OF_FACE" | "UNKNOWN";
  face_value: string | null;
  face_value_date: string | null;
  native_trade_amount_kopecks: number | null;
  native_total_basis: string | null;
  proof_dependency: string | null;
  accrued_interest_kopecks: number | null;
  commission_kopecks: number | null;
  gross_payout_kopecks: number | null;
  withheld_tax_kopecks: number | null;
  net_payout_kopecks: number | null;
  classification: string | null;
  classification_origin: string | null;
  classification_status: string | null;
  persisted_link_status: string | null;
  attribution_basis: string | null;
  effective_isin: string | null;
  current: boolean;
  counted: boolean;
  cash_legs: InstrumentCashLeg[];
  reason_codes: string[];
  assumptions: string[];
};
export type InstrumentEndpoint = {
  date: string;
  quantity: string | null;
  reported_value_kopecks: number | null;
  economic_value_kopecks: number | null;
  accrued_interest_kopecks: number | null;
  valuation_basis: "dirty" | "clean_plus_nkd" | "reported_unknown";
  source_references: string[];
  reason_codes: string[];
};
export type InstrumentAnalysis = {
  contract_version: "instrument_return_v2";
  opening_date: string;
  closing_date: string;
  history_start: string;
  history_end: string;
  history_complete_since_acquisition: boolean;
  events: InstrumentEvent[];
  opening: InstrumentEndpoint;
  closing: InstrumentEndpoint;
  components: Record<
    | "buys"
    | "sells"
    | "coupons"
    | "dividends"
    | "redemption"
    | "fees"
    | "taxes"
    | "valuation_and_trades",
    InstrumentMetric<number>
  >;
  pnl: InstrumentMetric<number>;
  known_subtotal: InstrumentMetric<number>;
  modified_dietz: InstrumentDietz;
  chained_monthly: InstrumentMetric<string>;
  coverage: Record<
    "events" | "quantity" | "endpoints" | "payouts" | "costs" | "valuation",
    { complete: boolean; reason_codes: string[] }
  >;
  source_references: Array<{
    intake_id: number;
    original_digest: string;
    parser_version: string;
    journal_revision: number;
    manifest_digest: string;
    classification_dependencies: string[];
    link_dependencies: string;
  }>;
  reason_codes: string[];
  assumptions: string[];
  statement_estimate: {
    pnl: InstrumentMetric<number>;
    modified_dietz: InstrumentDietz;
    assumptions: string[];
  };
};
export type SourceInstrumentReturns = {
  source_account: string;
  native_source_account: string | null;
  unresolved_events: InstrumentEvent[];
  account_reconciliation_events: InstrumentEvent[];
  reconciliation: {
    opening_date: string;
    closing_date: string;
    account_growth: InstrumentMetric<number>;
    instrument_pnl: InstrumentMetric<number>;
    account_only_result: InstrumentMetric<number>;
    residual: InstrumentMetric<number>;
    complete: boolean;
    reason_codes: string[];
  } | null;
  income: Array<{
    event_date: string;
    amount_kopecks: number;
    classification: string;
    status: string;
    source_references: string[];
    isin: string | null;
  }>;
  instruments: Array<{
    isin: string;
    source_name: string | null;
    instrument_type: string | null;
    analysis: InstrumentAnalysis;
    months: Array<
      InstrumentTotals & {
        month: string;
        opening_quantity: string | null;
        closing_quantity: string | null;
        opening_value_kopecks: number | null;
        closing_value_kopecks: number | null;
        intake_ids: number[];
        analysis: InstrumentAnalysis;
      }
    >;
    all_time: InstrumentTotals & {
      available_months: string[];
      missing_months: string[];
      partial_months: string[];
      partial: boolean;
    };
  }>;
  gaps: ReturnGap[];
  authority: "provisional";
  financial_authority: "none";
  currency: "RUB";
};

const query = (account: string) => `source_account=${encodeURIComponent(account)}`;
export const getSourceMonthlyReturns = (account: string, signal?: AbortSignal) =>
  apiRequest<SourceMonthlyReturns>(`/api/source-returns/monthly?${query(account)}`, { signal });
export type InstrumentReturnSelection = { isin?: string } & (
  | { opening_date: string; closing_date: string }
  | { opening_date?: never; closing_date?: never }
);
export const getSourceInstrumentReturns = (
  account: string,
  signal?: AbortSignal,
  selection: InstrumentReturnSelection = {},
) => {
  const params = new URLSearchParams({ source_account: account });
  if (selection.isin) params.set("isin", selection.isin);
  if (selection.opening_date && selection.closing_date) {
    params.set("opening_date", selection.opening_date);
    params.set("closing_date", selection.closing_date);
  }
  return apiRequest<SourceInstrumentReturns>(`/api/source-returns/instruments?${params}`, {
    signal,
  });
};
