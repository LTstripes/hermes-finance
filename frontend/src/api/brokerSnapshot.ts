import { apiRequest } from "./client";

export type BrokerMapping = {
  accounts: { hermes_account_id: number; provider_account_id: string }[];
  instruments: { hermes_instrument_id: number; provider_instrument_id: string }[];
};

export type BrokerPositionRow = {
  account_id: number;
  instrument_id: number;
  account_name: string | null;
  instrument_name: string | null;
  instrument_isin: string | null;
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
  is_money?: boolean | null;
  provider_account_id?: string | null;
  provider_instrument_id?: string | null;
  [key: string]: unknown;
};

export type BrokerSnapshotDiagnostics = {
  schema_version: string;
  provider: string;
  snapshot_status: string;
  eligible_for_apply: boolean;
  compatibility_state: "compatible" | "unknown" | "unsupported" | string;
  compatibility_fingerprint: string | null;
  api_doc_version: string;
  observed_alfa_pro_version: string | null;
  observed_api_version: string | null;
  observed_protocol_version: string | null;
  protocol_family: string;
  layout_family: string;
  capabilities: string[];
  failure_class:
    | "none"
    | "connection"
    | "auth"
    | "routing"
    | "protocol"
    | "layout"
    | "mapping"
    | string;
  failure_codes: string[];
  entity_status: string[];
  entity_counts: string[];
  observed_fields: string[];
  safe_artifact: boolean;
  raw_payload_saved: boolean;
  private_values_included: boolean;
  credentials_included: boolean;
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
    classification?: string;
  }[];
  instruments: {
    provider_instrument_id: string | null;
    isin: string | null;
    ticker: string | null;
    display_name: string | null;
    hermes_instrument_id: number | null;
    status: string;
    reason: string | null;
    classification?: string;
  }[];
  month_closed?: boolean;
  month_status?: string;
  cash: unknown[];
  warnings: string[];
  diagnostics: BrokerSnapshotDiagnostics;
  diagnostic_report: string;
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

export type BrokerApplyResult = {
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
  baseline_date?: string | null;
  provenance_id?: number | null;
};

export function applyBrokerSnapshot(
  monthId: number,
  mapping: BrokerMapping,
  selections: BrokerApplySelection[],
  signal?: AbortSignal,
) {
  return apiRequest<BrokerApplyResult>(`/api/months/${monthId}/broker-snapshot-apply`, {
    method: "POST",
    body: { mapping, selections },
    signal,
  });
}

export function applyBrokerBaseline(
  monthId: number,
  payload: {
    baseline_date: string;
    mapping: BrokerMapping;
    selections: BrokerApplySelection[];
  },
  signal?: AbortSignal,
) {
  return apiRequest<BrokerApplyResult>(`/api/months/${monthId}/broker-baseline-apply`, {
    method: "POST",
    body: payload,
    signal,
  });
}
