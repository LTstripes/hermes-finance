import { ApiClientError } from "../../api/client";
import { canonicalId } from "./navigation";
export const GOLD_VERSION = "owner_manual_gold_history_v1" as const;
export type GoldEventInput = {
  event_id: string;
  event_date: string;
  side: "BUY" | "SELL";
  grams: string;
  amount_basis: "actual" | "derived_unit_price";
  amount_rub: string | null;
  unit_price_rub: string | null;
  fee_state: "known_zero" | "known" | "unknown";
  fee_rub: string | null;
};
export type GoldIntent = {
  contract_version: typeof GOLD_VERSION;
  account_id: number;
  instrument_id: number;
  expected_revision: number;
  covered_from: string;
  covered_to: string;
  complete: boolean;
  zero_start: boolean;
  current_quantity: string;
  current_quantity_date: string;
  provenance_reference: string;
  change_reason: string | null;
  events: GoldEventInput[];
};
export type GoldEvent = Omit<GoldEventInput, "amount_rub" | "fee_rub"> & {
  amount_kopecks: string;
  separate_fee_kopecks: string | null;
};
export type GoldDeclaration = Omit<GoldIntent, "expected_revision" | "events"> & {
  events: GoldEvent[];
};
export type GoldValuation = {
  snapshot_id: number;
  date: string;
  snapshot_date: string;
  price_date: string;
  quantity: string;
  market_value_kopecks: string;
  price_source: string;
  month_status?: string;
  provisional?: boolean;
};
export type GoldResult = {
  total_result_kopecks: string | null;
  realized_result_kopecks: string | null;
  unrealized_result_kopecks: string | null;
  remaining_cost_kopecks: string | null;
  buy_amount_kopecks: string | null;
  sale_amount_kopecks: string | null;
  separate_fees_kopecks: string | null;
  net_sales_kopecks: string | null;
  calculated_quantity: string | null;
  declared_calculated_quantity: string;
  period: { covered_from: string; covered_to: string | null };
  valuation_date: string | null;
  valuation_provisional?: boolean | null;
  valuation_basis: "saved_snapshot_quote" | "owner_declared_zero_quantity" | null;
  as_of_date: string;
  valuation_kopecks: string | null;
  amount_basis: "actual" | "derived";
  tax_treatment: "not_provided";
  method: string;
  reason_codes: string[];
  decomposition_reason_codes: string[];
  total_reason_codes: string[];
  realized_reason_codes: string[];
  unrealized_reason_codes: string[];
};
export type GoldHistory = {
  contract_version: typeof GOLD_VERSION;
  source_kind: "owner_manual_gold_history";
  authority: "owner_attestation";
  history_id: number;
  revision: number;
  account_id: number;
  instrument_id: number;
  currentness: "current" | "dependency_changed";
  events_loaded: boolean;
  declaration: GoldDeclaration;
  events: GoldEvent[];
  valuation: GoldValuation | null;
  result: GoldResult;
  reason_codes: string[];
  revisions: { revision: number; declaration: GoldDeclaration; accepted_at: string }[];
};
export type GoldPreview = {
  contract_version: typeof GOLD_VERSION;
  source_kind: "owner_manual_gold_history";
  authority: "owner_attestation";
  action: "create" | "revise" | "noop";
  history_id: number | null;
  expected_revision: number;
  declaration: GoldDeclaration;
  valuation: GoldValuation | null;
  result: GoldResult;
  confirmation_digest: string;
  can_apply: boolean;
};
export type GoldReceipt = {
  contract_version: typeof GOLD_VERSION;
  request_id: string;
  accepted_revision: number;
  history: GoldHistory;
  duplicate?: boolean;
};
const base = "/api/owner-manual-gold-history";
async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal,
    });
  } catch (error) {
    throw new ApiClientError(0, {
      code: "network_error",
      message: error instanceof Error ? error.message : "Network failure",
      details: [],
    });
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : (payload?.error?.message ?? `HTTP ${response.status}`);
    throw new ApiClientError(response.status, { code: detail, message: detail, details: [] });
  }
  return payload as T;
}
export function checkGoldHistory(history: GoldHistory, accountId: number, instrumentId: number) {
  if (
    history?.contract_version !== GOLD_VERSION ||
    history.source_kind !== "owner_manual_gold_history" ||
    history.authority !== "owner_attestation" ||
    history.events_loaded !== true ||
    history.account_id !== accountId ||
    history.instrument_id !== instrumentId ||
    canonicalId(history.history_id) === null ||
    canonicalId(history.revision) === null
  )
    throw new Error("Gold history context mismatch");
  return history;
}
export async function getGoldHistories(
  accountId: number,
  instrumentId: number,
  signal?: AbortSignal,
) {
  const value = await request<{ contract_version: typeof GOLD_VERSION; histories: GoldHistory[] }>(
    `${base}?${new URLSearchParams({ account_id: String(accountId), instrument_id: String(instrumentId) })}`,
    undefined,
    signal,
  );
  if (value?.contract_version !== GOLD_VERSION || !Array.isArray(value.histories))
    throw new Error("Gold history contract mismatch");
  for (const history of value.histories) checkGoldHistory(history, accountId, instrumentId);
  return value.histories;
}
export async function getGoldHistory(id: number, accountId: number, instrumentId: number) {
  const history = checkGoldHistory(
    await request<GoldHistory>(`${base}/${id}`),
    accountId,
    instrumentId,
  );
  if (history.history_id !== id) throw new Error("Gold history identity mismatch");
  return history;
}
export async function previewGoldHistory(intent: GoldIntent) {
  const value = await request<GoldPreview>(`${base}/preview`, intent);
  if (
    value?.contract_version !== GOLD_VERSION ||
    value.declaration?.account_id !== intent.account_id ||
    value.declaration.instrument_id !== intent.instrument_id ||
    value.expected_revision !== intent.expected_revision ||
    !/^[a-f0-9]{64}$/.test(value.confirmation_digest)
  )
    throw new Error("Gold preview context mismatch");
  return value;
}
export function applyGoldHistory(
  intent: GoldIntent,
  confirmation_digest: string,
  request_id: string,
) {
  return request<GoldReceipt>(`${base}/apply`, { ...intent, confirmation_digest, request_id });
}
export function getGoldReceipt(requestId: string) {
  return request<GoldReceipt>(`${base}/receipts/${encodeURIComponent(requestId)}`);
}
export function goldPendingKey(accountId: number, instrumentId: number) {
  return `hermes:gold-history:pending:${accountId}:${instrumentId}`;
}
