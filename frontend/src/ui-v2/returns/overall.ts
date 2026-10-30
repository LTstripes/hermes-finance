import { apiRequest } from "../../api/client";
import type { Metric, Period, Result } from "./model";

export type OverallAccount = {
  scope: string;
  label: string;
  period: Period | null;
  result: Result | null;
  proof_status: "current" | "stale" | "absent" | "conflict";
  reason_codes: string[];
  instrument_count: number;
};
export type OverallInstrumentAccount = Pick<Result, "pnl" | "rate" | "coupons" | "dividends"> & {
  canonical_account_id?: number | null;
  details_loaded: boolean;
  period: Period | null;
  scope: string;
  label: string;
};
export type OverallInstrument = {
  isin: string;
  name: string;
  kind: string | null;
  accounts: OverallInstrumentAccount[];
  reason_codes: string[];
};
export type MixedComponent = {
  id: string;
  category: "brokerage" | "deposits" | "gold";
  label: string;
  selected: boolean;
  available: boolean;
  included: boolean;
  amount: Metric;
  interval: Period | null;
  valuation_date: string | null;
  coverage: {
    status: "supported" | "partial" | "unavailable" | "conflict";
    reason_codes: string[];
  };
  method: string;
  authority: "source_only" | "accepted_snapshot" | "owner_attestation";
  exclusion_reason: string | null;
};
export type MixedResult = {
  known_result: Metric;
  rate: Metric;
  selected_component_count: number;
  available_component_count: number;
  included_component_count: number;
  components: MixedComponent[];
  reason_codes: string[];
};
export type CouponIncome = {
  known_total: Metric;
  partial: true;
  selected_accounts: number;
  included_accounts: number;
  accounts: {
    scope: string;
    label: string;
    period: Period | null;
    amount: Metric;
    proof_status: "current" | "stale" | "absent" | "conflict";
    included: boolean;
    exclusion_reason: string | null;
    reason_codes: string[];
  }[];
  reason_codes: string[];
};
export type GoldHistorySummary = {
  account_id: number;
  instrument_id: number;
  label: string;
  revision: number;
  amount_basis: "actual" | "derived";
  tax_treatment: "not_provided";
  source_kind: "owner_manual_gold_history";
  authority: "owner_attestation";
  currentness: "current" | "dependency_changed";
  period: Period | null;
  valuation_date: string | null;
  total_result: Metric;
  valuation_status: "draft" | "closed" | null;
  realized_result: Metric;
  unrealized_result: Metric;
  buy_amount: Metric;
  sale_amount: Metric;
  separate_fees: Metric;
  reason_codes: string[];
};
export type GoldTarget = { account_id: number; instrument_id: number; label: string };
export type Overall = {
  contract_version: "returns_overall_v1";
  mixed_result: MixedResult;
  coupon_income: CouponIncome;
  dividend_income: CouponIncome;
  overall: { pnl: Metric; rate: Metric; partial: true; reason_codes: string[] };
  source_accounts: OverallAccount[];
  instruments: OverallInstrument[];
  deposits: {
    interest: Metric;
    partial: true;
    periods: { period: Period; status: string; rows: number }[];
    reason_codes: string[];
  };
  gold: {
    targets?: GoldTarget[];
    histories?: GoldHistorySummary[];
    snapshots: {
      account_id: number;
      instrument_id: number;
      label: string;
      date: string;
      quantity: string;
      market_value: Metric;
      cost_basis: Metric;
      unrealized_result: Metric;
      cost_return: Metric;
    }[];
    period_result: Metric;
    reason_codes: string[];
  };
  reason_codes: string[];
};
export async function getOverall(signal: AbortSignal): Promise<Overall> {
  const value = await apiRequest<Overall>("/api/returns/overall", { signal });
  if (value.contract_version !== "returns_overall_v1") throw new Error("Return contract mismatch");
  return value;
}
export function accountHref(scope: string, period: Period | null) {
  const params = new URLSearchParams({ scope });
  if (period) {
    params.set("start", period.start);
    params.set("end", period.end);
  } else params.set("period", "history");
  return `/v2/returns/account?${params}`;
}
