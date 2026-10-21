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
  coupons_kopecks: number;
  dividends_kopecks: number;
  income_assumptions_used: boolean;
};
export type SourceMonthlyReturns = {
  source_account: string;
  months: MonthlyReturn[];
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
  total_kopecks: number | null;
  capital_base_kopecks: number | null;
  return_percent: string | null;
  income_assumptions_used: boolean;
  income_complete: boolean;
  flags: string[];
  approximate: boolean;
};
export type SourceInstrumentReturns = {
  source_account: string;
  instruments: Array<{
    isin: string;
    source_name: string | null;
    instrument_type: string | null;
    months: Array<
      InstrumentTotals & {
        month: string;
        opening_quantity: string | null;
        closing_quantity: string | null;
        opening_value_kopecks: number | null;
        closing_value_kopecks: number | null;
        intake_ids: number[];
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
export const getSourceInstrumentReturns = (account: string, signal?: AbortSignal) =>
  apiRequest<SourceInstrumentReturns>(`/api/source-returns/instruments?${query(account)}`, {
    signal,
  });
