import { apiRequest } from "./client";

export type BrokerMapping = {
  accounts: { hermes_account_id: number; provider_account_id: string }[];
  instruments: { hermes_instrument_id: number; provider_instrument_id: string }[];
};

export type BrokerPositionRow = {
  account_id: number;
  instrument_id: number;
  status: string;
  provider_quantity: string | null;
  hermes_quantity: string | null;
  quantity_difference: string | null;
  quantity_equal: boolean | null;
  fingerprint: string | null;
  reason: string | null;
  warnings: string[];
  provider_broker_unit_price: string | null;
  provider_accrued_interest_nkd: string | null;
  provider_unrealized_result: string | null;
  [key: string]: unknown;
};

export type BrokerSnapshotPreview = {
  reporting_month_id: number;
  provider: string;
  status: string;
  eligible_for_apply: boolean;
  snapshot_status: string;
  positions: BrokerPositionRow[];
  accounts: {
    provider_account_id: string;
    hermes_account_id: number | null;
    status: string;
    reason: string | null;
  }[];
  instruments: {
    provider_instrument_id: string | null;
    isin: string | null;
    ticker: string | null;
    display_name: string | null;
    hermes_instrument_id: number | null;
    status: string;
    reason: string | null;
  }[];
  cash: unknown[];
  warnings: string[];
  error_code: string | null;
  message: string | null;
  [key: string]: unknown;
};

export type BrokerApplySelection = {
  account_id: number;
  instrument_id: number;
  fingerprint: string;
  action: "update" | "create";
  average_cost?: { action: "keep_existing" | "replace"; value?: string | null };
  market_price?: {
    action: "keep_existing" | "replace";
    market_price_per_unit?: string | null;
    price_date?: string | null;
    price_source?: string | null;
  };
  accrued_interest?: { action: "keep_existing" | "replace"; value?: string | null };
};

export function previewBrokerSnapshot(
  monthId: number,
  mapping: BrokerMapping,
  signal?: AbortSignal,
) {
  return apiRequest<BrokerSnapshotPreview>(`/api/months/${monthId}/broker-snapshot-preview`, {
    method: "POST",
    body: mapping,
    signal,
  });
}

export function applyBrokerSnapshot(
  monthId: number,
  mapping: BrokerMapping,
  selections: BrokerApplySelection[],
  signal?: AbortSignal,
) {
  return apiRequest<{
    success: boolean;
    selected_count: number;
    items: {
      action: string;
      position_snapshot_id: number;
      account_id: number;
      instrument_id: number;
    }[];
    error_code: string | null;
    message: string | null;
  }>(`/api/months/${monthId}/broker-snapshot-apply`, {
    method: "POST",
    body: { mapping, selections },
    signal,
  });
}
