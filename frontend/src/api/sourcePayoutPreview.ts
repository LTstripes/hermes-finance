import { apiRequest } from "./client";
import type { InstrumentAnalysis, InstrumentEvent } from "./sourceReturns";

export type SourcePayoutRequest = {
  source_account: string;
  isin: string;
  as_of: string;
};

export type SourceQuantityBases = {
  source_account: string;
  native_source_account: string | null;
  isin: string;
  on_or_before: string;
  authority: "provisional";
  financial_authority: "none";
  bases: Array<{
    as_of: string;
    quantity: string | null;
    quantity_references: string[];
    reason_codes: string[];
  }>;
};

/** Local discovery only: no provider I/O and no financial writer. */
export function getSourceQuantityBases(
  account: string,
  isin: string,
  closing: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ source_account: account, isin, on_or_before: closing });
  return apiRequest<SourceQuantityBases>(`/api/source-returns/quantity-bases?${params}`, {
    signal,
  });
}

export type SourcePayoutActual = Pick<
  InstrumentEvent,
  | "event_key"
  | "provider"
  | "native_source_account"
  | "isin"
  | "kind"
  | "source_references"
  | "event_date"
  | "effective_isin"
  | "classification"
  | "classification_origin"
  | "classification_status"
  | "persisted_link_status"
  | "attribution_basis"
  | "current"
  | "counted"
  | "reason_codes"
  | "assumptions"
> & {
  net_payout_kopecks: string | null;
  gross_payout_kopecks: string | null;
  withheld_tax_kopecks: string | null;
};

export type SourcePayoutPreview = SourcePayoutRequest & {
  authority: "provisional";
  financial_authority: "none";
  native_source_account: string | null;
  account_id: number | null;
  instrument_id: number | null;
  quantity: string | null;
  quantity_authority: "source_observed";
  assumptions: Array<"fixed_source_quantity_not_entitlement">;
  quantity_references: string[];
  source_references: InstrumentAnalysis["source_references"];
  dependency_fingerprint: string;
  reason_codes: string[];
  provider: "t_invest";
  instrument_uid: string | null;
  actuals: SourcePayoutActual[];
  reconciliation_reasons: string[];
  rows: Array<{
    identity_key: string | null;
    event_kind: string;
    payment_date: string | null;
    provider_status: string | null;
    source_method: string | null;
    per_unit_amount: string | null;
    currency: string | null;
    announced_amount_kopecks: string | null;
    personal_tax_known: false;
    status:
      | "future"
      | "possible_paid"
      | "past_unreconciled"
      | "outside_horizon"
      | "reconciliation_required"
      | "tentative"
      | "ambiguous_identity"
      | "unsupported"
      | "unavailable"
      | "error";
    countable_future: boolean;
    actual_event_keys: string[];
    reason_codes: string[];
  }>;
  failures: string[];
};

/** Ephemeral preview; no financial Apply token or PositionSnapshot is created. */
export function previewSourcePayouts(
  payload: SourcePayoutRequest,
  signal?: AbortSignal,
): Promise<SourcePayoutPreview> {
  return apiRequest<SourcePayoutPreview>("/api/source-returns/payout-preview", {
    method: "POST",
    body: payload,
    signal,
  });
}
