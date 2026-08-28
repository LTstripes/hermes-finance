import type { BrokerMapping, BrokerSnapshotDiagnostics } from "./brokerSnapshot";
import { apiRequest } from "./client";

export type ReconciliationRowState =
  | "matched"
  | "differs"
  | "missing_local"
  | "missing_provider"
  | "unresolved"
  | string;

export type ReconciliationRow = {
  state: ReconciliationRowState;
  account_id: number | null;
  instrument_id: number | null;
  account_name: string | null;
  instrument_name: string | null;
  instrument_isin: string | null;
  instrument_ticker: string | null;
  provider_account_id: string | null;
  provider_instrument_id: string | null;
  hermes_quantity: string | null;
  provider_quantity: string | null;
  quantity_difference: string | null;
  quantity_equal: boolean | null;
  hermes_market_price_per_unit_kopecks: number | null;
  provider_broker_unit_price: string | null;
  provider_accounting_price: string | null;
  provider_market_value: string | null;
  price_comparable: string;
  hermes_accrued_interest_kopecks: number | null;
  provider_accrued_interest_nkd: string | null;
  nkd_comparable: string;
  hermes_unrealized_result_kopecks: number | null;
  provider_unrealized_result: string | null;
  unrealized_comparable: string;
  reason: string | null;
  warnings: string[];
  comparison_only_fields: string[];
  fingerprint: string | null;
};

export type ReconciliationAccount = {
  provider_account_id: string;
  hermes_account_id: number | null;
  status: string;
  reason: string | null;
};

export type ReconciliationInstrument = {
  provider_instrument_id: string | null;
  isin: string | null;
  ticker: string | null;
  display_name: string | null;
  hermes_instrument_id: number | null;
  status: string;
  reason: string | null;
};

export type ReconciliationCashRow = {
  provider_account_id: string;
  hermes_account_id: number | null;
  currency: string | null;
  provider_amount: string | null;
  status: string;
  reason: string | null;
};

export type BrokerReconciliationResponse = {
  reporting_month_id: number;
  provider: string;
  status: string;
  read_only: true;
  eligible_for_apply: false;
  stale: boolean;
  snapshot_status: string;
  compatibility_state: string;
  compatibility_fingerprint: string | null;
  snapshot_fingerprint: string | null;
  source_as_of: string | null;
  captured_at: string;
  month_status: string;
  month_closed: boolean;
  accounts: ReconciliationAccount[];
  instruments: ReconciliationInstrument[];
  rows: ReconciliationRow[];
  cash: ReconciliationCashRow[];
  warnings: string[];
  diagnostics: BrokerSnapshotDiagnostics;
  diagnostic_report: string;
  error_code: string | null;
  message: string | null;
};

/** Explicit owner action over the accepted normalized read-only backend. */
export function previewBrokerReconciliation(
  monthId: number,
  mapping: BrokerMapping,
  signal?: AbortSignal,
): Promise<BrokerReconciliationResponse> {
  return apiRequest<BrokerReconciliationResponse>(
    `/api/months/${monthId}/broker-reconciliation-preview`,
    {
      method: "POST",
      body: mapping,
      signal,
    },
  );
}
