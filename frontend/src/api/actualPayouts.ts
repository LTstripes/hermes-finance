import { apiRequest } from "./client";

export type ForecastProof = {
  kind: "app" | "ecf";
  facts: Record<string, string | null>;
  revision: Record<string, string | null> | null;
  provider_event_key: string | null;
  state?: "paid" | "future" | "unresolved";
  reason_code?: string | null;
};
export type PayoutObligation = {
  account_id: number;
  reporting_month_id: number;
  base_request_id: string;
  investment_cash_flow_id: number;
  actual: Record<string, string | null>;
  money_proof_request_id: string;
  candidates: ForecastProof[];
  forecast_choices: ForecastProof[];
  legacy_relations: Record<string, string | null>[];
  terminal_relation: (Record<string, string | null> & { state: string }) | null;
  coverage_state: "complete" | "unknown";
};
export type PayoutIntent = {
  contract_version: "broker_payout_reconciliation_v1";
  operation: "link" | "reaffirm" | "retire" | "distinct";
  base_request_id: string;
  reporting_month_id: number;
  account_id: number;
  investment_cash_flow_id: number;
  applied_payout_id: number | null;
  expected_cash_flow_id: number | null;
  predecessor_id: number | null;
  claims?: {
    reference: string;
    independent_event_reference: string;
    settlement_basis_reference: string;
    review_context_digest: string;
    actual_is_exact_event: boolean;
    full_event_settled_not_partial: boolean;
    provider_identity_key: string | null;
    exact_manual_row_is_same_event: boolean;
    actual_and_forecast_are_distinct: boolean;
    actual_independent_event_key: string | null;
    forecast_independent_event_key: string | null;
  };
};
export type PayoutPlan = {
  contract_version: "broker_payout_reconciliation_v1";
  operation: PayoutIntent["operation"];
  scope: { account_id: number; reporting_month_id: number };
  targets: Record<string, unknown>[];
  review_context_digest: string;
  confirmation_digest: string;
  can_apply: boolean;
  blockers: string[];
};
export type PayoutReceipt = {
  contract_version: "broker_payout_reconciliation_v1";
  request_id: string;
  account_id: number;
  reporting_month_id: number;
  confirmation_digest: string;
  accepted: unknown;
  relations: { id: number; state: string; retired_request_id: string | null }[];
  status: string;
};
export function listPayoutObligations(month: number, account: number, signal?: AbortSignal) {
  return apiRequest<PayoutObligation[]>(
    `/api/broker-months/payout-obligations?reporting_month_id=${month}&account_id=${account}`,
    { signal },
  );
}
export function previewActualPayout(intent: PayoutIntent) {
  return apiRequest<PayoutPlan>("/api/broker-months/payout-preview", {
    method: "POST",
    body: intent,
  });
}
export function confirmActualPayout(intent: PayoutIntent, digest: string, request: string) {
  return apiRequest<PayoutReceipt>("/api/broker-months/payout-apply", {
    method: "POST",
    body: { ...intent, confirmation_digest: digest, request_id: request },
  });
}
export function readActualPayout(request: string) {
  return apiRequest<PayoutReceipt>(`/api/broker-months/${encodeURIComponent(request)}`);
}
