import { apiMultipart, apiRequest } from "./client";

export type MoneyOccurrence = { import_id: number; section: "money"; ordinal: number };
export type MoneyDecision = {
  role: "coupon" | "account_funding";
  seed: MoneyOccurrence;
  operation?: "accept" | "corroborate" | "reaffirm";
  instrument_id?: number;
  investment_cash_flow_id?: number;
  coupon_claims?: {
    reference: string;
    review_context_digest: string;
    actual_coupon_payment: boolean;
    exact_row_instrument_link: boolean;
    complete_occurrence_set_is_one_event: boolean;
    existing_target_is_same_payment: boolean;
  };
  owner_flow_intent?: Record<string, unknown>;
};
export type MoneyIntent = {
  contract_version: "broker_money_v1";
  base_request_id: string;
  reporting_month_id: number;
  account_id: number;
  money_decisions: MoneyDecision[];
};
export type MoneyPreview = {
  contract_version: "broker_money_v1";
  confirmation_digest: string;
  account_id: number;
  reporting_month_id: number;
  base_request_id: string;
  can_apply: boolean;
  expected_effects?: {
    new_coupon_facts: number;
    new_account_flow_facts: number;
    selected_coupon_net_minor: string | null;
  };
  blockers: string[];
  exceptions: string[];
  sources: { import_id: number; original_required?: boolean; source: Record<string, string> }[];
  inventory: {
    occurrence: MoneyOccurrence;
    candidate_kind: string;
    description: string;
    date: string;
    signed_amount: string;
    currency: string;
    reasons: string[];
  }[];
  decisions: {
    decision: MoneyDecision;
    occurrences: MoneyOccurrence[];
    target_id: string | number | null;
    action: string;
    blockers: string[];
    review_context_digest?: string;
    owner_flow_intent?: Record<string, unknown>;
    h2_plan?: { source_set_fingerprint: string; review_context_digest: string } | null;
    competing_payouts?: Record<string, string | null>[];
  }[];
};
export type MoneyTarget = {
  role: "coupon" | "account_funding";
  target_id: string | number;
  facts: Record<string, string | null> | null;
  effective: boolean;
  exceptions: string[];
  h2?: { account_scope: { status: string }; portfolio_scope: { status: string } };
};
export type MoneyReadback = {
  contract_version: "broker_money_v1";
  request_id: string;
  confirmation_digest: string;
  base_request_id: string;
  account_id: number;
  reporting_month_id: number;
  targets: MoneyTarget[];
  accepted: unknown;
  exceptions: string[];
  bookkeeping_ready: boolean;
};

function form(files: File[], intent: unknown, field: "intent" | "confirmation") {
  const data = new FormData();
  files.forEach((file, index) => {
    data.append(index === 0 ? "file" : "originals", file);
  });
  data.append(field, JSON.stringify(intent));
  return data;
}
export function previewBrokerMoney(files: File[], intent: MoneyIntent) {
  return apiMultipart<MoneyPreview>("/api/broker-months/preview", form(files, intent, "intent"));
}
export function applyBrokerMoney(
  files: File[],
  intent: MoneyIntent,
  digest: string,
  requestId: string,
) {
  return apiMultipart<MoneyReadback>(
    "/api/broker-months/apply",
    form(
      files,
      {
        ...intent,
        confirmation_digest: digest,
        request_id: requestId,
      },
      "confirmation",
    ),
  );
}
export function readBrokerMoney(requestId: string) {
  return apiRequest<MoneyReadback>(`/api/broker-months/${encodeURIComponent(requestId)}`);
}
