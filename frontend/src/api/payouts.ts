import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type PayoutEventKind = "coupon" | "dividend" | "redemption";

export type PayoutPreviewStatus =
  | "new"
  | "unchanged"
  | "revised"
  | "possible_manual_duplicate"
  | "cancelled_by_provider"
  | "missing_from_provider"
  | "tentative"
  | "ambiguous_identity"
  | "unsupported"
  | "unavailable"
  | "error"
  | "position_gone";

export type PayoutCountingDecision = "keep_both" | "count_manual" | "count_provider";

export type PayoutContextRequest = {
  account_id: number;
  instrument_id: number;
  position_snapshot_id: number;
  forecast_version: string;
};

export type PayoutReconciliation = {
  reconciliation_id: number;
  expected_cash_flow_id: number;
  counting_decision: PayoutCountingDecision;
};

export type PayoutPreviewRow = {
  status: PayoutPreviewStatus;
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  position_snapshot_id: number | null;
  quantity: string | null;
  provider: string;
  instrument_uid: string;
  event_kind: PayoutEventKind | null;
  identity_key: string | null;
  payment_date: string | null;
  per_unit_amount: string | null;
  currency: string | null;
  total_amount: MoneyValue | null;
  provider_status: string | null;
  source_method: string | null;
  applied_payout_id: number | null;
  applied_lifecycle: string | null;
  manual_candidate_ids: number[];
  reconciliation: PayoutReconciliation | null;
  selectable: boolean;
  default_selected: boolean;
  fingerprint: string | null;
  message: string | null;
};

export type PayoutPreview = {
  reporting_month_id: number;
  account_id: number;
  instrument_id: number;
  position_snapshot_id: number | null;
  quantity: string | null;
  provider: string;
  instrument_uid: string;
  rows: PayoutPreviewRow[];
};

export type ManualDuplicateDecision = {
  expected_cash_flow_id: number;
  counting_decision: PayoutCountingDecision;
};

export type PayoutApplySelection = {
  provider: string;
  instrument_uid: string;
  event_kind: PayoutEventKind;
  identity_key: string;
  fingerprint: string;
  manual_duplicate_decision?: ManualDuplicateDecision | null;
};

export type PayoutApplyRequest = PayoutContextRequest & {
  rows: PayoutApplySelection[];
};

export type PayoutApplyItem = {
  payout_id: number;
  revision_id: number;
  revision_kind: string;
  provider: string;
  instrument_uid: string;
  event_kind: PayoutEventKind;
  identity_key: string;
  lifecycle: string;
  total_amount: MoneyValue;
  reconciliation_id: number | null;
  counting_decision: PayoutCountingDecision | null;
  expected_cash_flow_id: number | null;
};

export type PayoutApplyFailureCode =
  | "preview_changed"
  | "validation_error"
  | "provider_error"
  | "persistence_error"
  | "closed_month";

export type PayoutApplyResult = {
  success: boolean;
  selected_count: number;
  items: PayoutApplyItem[];
  error_code: PayoutApplyFailureCode | null;
  message: string | null;
};

export type PayoutCalendarItem = {
  source_kind: "manual" | "provider" | string;
  source_id: number;
  expected_date: string;
  flow_type: string;
  account_id: number;
  account_name: string;
  instrument_id: number;
  instrument_name: string | null;
  expected_net_amount: MoneyValue;
  is_confirmed: boolean | null;
  is_approximate: boolean;
  manual_source: string | null;
  provider: string | null;
  provider_instrument_uid: string | null;
  provider_identity_key: string | null;
  provider_lifecycle: string | null;
  reconciliation_id: number | null;
  counting_decision: PayoutCountingDecision | null;
  linked_manual_id: number | null;
  linked_provider_payout_id: number | null;
};

export type PayoutCalendarMonth = {
  year: number;
  month: number;
  coupon: MoneyValue;
  dividend: MoneyValue;
  interest: MoneyValue;
  redemption: MoneyValue;
  other: MoneyValue;
  passive_net: MoneyValue;
  total_net: MoneyValue;
  items: PayoutCalendarItem[];
};

export function previewPayouts(
  monthId: number,
  payload: PayoutContextRequest,
  signal?: AbortSignal,
): Promise<PayoutPreview> {
  return apiRequest<PayoutPreview>(`/api/months/${monthId}/payout-preview`, {
    method: "POST",
    body: payload,
    signal,
  });
}

export function applyPayouts(
  monthId: number,
  payload: PayoutApplyRequest,
  signal?: AbortSignal,
): Promise<PayoutApplyResult> {
  return apiRequest<PayoutApplyResult>(`/api/months/${monthId}/payout-apply`, {
    method: "POST",
    body: payload,
    signal,
  });
}

export function listPayoutCalendar(
  monthId: number,
  forecastVersion: string,
  signal?: AbortSignal,
): Promise<PayoutCalendarMonth[]> {
  const query = new URLSearchParams({
    month_id: String(monthId),
    forecast_version: forecastVersion,
  });
  return apiRequest<PayoutCalendarMonth[]>(`/api/payouts/calendar?${query.toString()}`, {
    method: "GET",
    signal,
  });
}
