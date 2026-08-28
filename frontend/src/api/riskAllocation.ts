import { apiRequest } from "./client";

export type RiskSupportStatus = "supported" | "unavailable" | "unknown";

export type RiskMetricSupport = {
  status: RiskSupportStatus;
  reason_codes: string[];
};

export type RiskSupportIssue = {
  source_kind: string;
  source_id: number | null;
  status: RiskSupportStatus;
  reason_codes: string[];
};

export type RiskMoneyValue = {
  amount: string;
  currency: string;
};

export type RiskAllocationSlice = {
  key: string;
  label: string;
  amount: RiskMoneyValue;
  share_pct: string | null;
  account_id: number | null;
  instrument_id: number | null;
  instrument_type: string | null;
};

export type RiskAllocationMetric = {
  support: RiskMetricSupport;
  denominator: RiskMoneyValue;
  covered_amount: RiskMoneyValue;
  unallocated_amount: RiskMoneyValue;
  coverage_pct: string | null;
  items: RiskAllocationSlice[];
  excluded: RiskSupportIssue[];
};

export type RiskConcentrationItem = {
  key: string;
  label: string;
  amount: RiskMoneyValue;
  share_pct: string | null;
  account_id: number | null;
  account_name: string | null;
  instrument_id: number | null;
  instrument_name: string | null;
  instrument_type: string | null;
  position_id: number | null;
  event_count: number | null;
  is_approximate: boolean;
};

export type RiskConcentrationMetric = {
  support: RiskMetricSupport;
  denominator: RiskMoneyValue;
  top_n: number;
  top_amount: RiskMoneyValue;
  top_share_pct: string | null;
  items: RiskConcentrationItem[];
  excluded: RiskSupportIssue[];
  is_approximate: boolean;
};

export type RiskAllocationResponse = {
  reporting_month_id: number;
  as_of_date: string;
  base_currency: string;
  liquid_assets_total: RiskMoneyValue;
  allocation_by_asset_class: RiskAllocationMetric;
  allocation_by_account: RiskAllocationMetric;
  top_positions: RiskConcentrationMetric;
  payout_concentration: RiskConcentrationMetric;
  redemption_concentration: RiskConcentrationMetric;
  support: Record<string, RiskMetricSupport>;
};

export function getRiskAllocation(
  monthId: number,
  topN = 5,
  forecastVersion = "v1",
  signal?: AbortSignal,
): Promise<RiskAllocationResponse> {
  const params = new URLSearchParams({
    month_id: String(monthId),
    top_n: String(topN),
    forecast_version: forecastVersion,
  });
  return apiRequest<RiskAllocationResponse>(`/api/analytics/risk-allocation?${params.toString()}`, {
    method: "GET",
    signal,
  });
}
