import { apiRequest } from "./client";
import type { PerformanceReadiness } from "./types";

export type ValuationCaptureRelation = "pre_external_flow" | "post_external_flow";
export type ValuationCaptureSideState = "captured" | "missing" | "stale" | "ambiguous";
export type ValuationCaptureCapability =
  | "available"
  | "requires_reopen"
  | "not_implemented"
  | "unsupported";

export type ValuationCaptureSide = {
  id: number;
  relation: ValuationCaptureRelation;
  observed_date: string;
  total_value: { amount: string; currency: string };
  performance_currency: string;
  coverage: "complete" | "unavailable" | "unknown";
  quality: "exact" | "unavailable" | "unknown";
  provenance_kind: string;
  bound: boolean;
};

export type ValuationCaptureTarget = {
  boundary_group_id: number | null;
  flow_ids: number[];
  event_date: string;
  reporting_month_id: number | null;
  reporting_month_status: string | null;
  scope: "portfolio" | "account";
  account_id: number | null;
  performance_currency: string;
  material_signature: string | null;
  pre_external_flow: ValuationCaptureSide[];
  post_external_flow: ValuationCaptureSide[];
  pre_state: ValuationCaptureSideState;
  post_state: ValuationCaptureSideState;
  missing_relations: ValuationCaptureRelation[];
  reason_codes: string[];
  capture_capability: ValuationCaptureCapability | null;
  blocked_reason: string | null;
  form_token: string | null;
};

export type ValuationCaptures = {
  schema_version: 1;
  scope: "portfolio" | "account";
  account_id: number | null;
  start_date: string;
  end_date: string;
  performance_currency: string;
  targets: ValuationCaptureTarget[];
  readiness: PerformanceReadiness;
  captured: {
    id: number;
    relation: ValuationCaptureRelation;
    observed_date: string;
    material_signature: string;
  } | null;
};

export type ValuationCaptureSubmission = {
  scope: "portfolio" | "account";
  account_id: number | null;
  start_date: string;
  end_date: string;
  form_token: string;
  external_flow_id: number | null;
  boundary_group_id: number | null;
  relation: ValuationCaptureRelation;
  expected_material_signature: string;
  total_value: string;
  performance_currency: string;
  coverage: "complete" | "unavailable" | "unknown";
  quality: "exact" | "unavailable" | "unknown";
  provenance_kind: string;
  provenance_reference: string | null;
  notes: string | null;
  attested: true;
};

/**
 * Capture-target read (PUI-05): canonical availability targets plus the
 * current material signature each later save must carry. No financial math.
 */
export function getValuationCaptures(
  startDate: string,
  endDate: string,
  scope: "portfolio" | "account",
  accountId: number | null,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    scope,
  });
  if (scope === "account" && accountId !== null) {
    query.set("account_id", String(accountId));
  }
  return apiRequest<ValuationCaptures>(`/api/performance/valuation-captures?${query}`, {
    method: "GET",
    signal,
  });
}

// No automatic write retries, including ambiguous network outcomes.
export function submitValuationCapture(
  body: Omit<ValuationCaptureSubmission, "attested"> & { attested: true },
) {
  return apiRequest<ValuationCaptures>("/api/performance/valuation-captures", {
    method: "POST",
    body,
  });
}
