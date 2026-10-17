import { apiRequest } from "./client";

export type PayoutScope = { accountId: number; instrumentId: number; t0: string; t1: string };
export type KnownPayouts = {
  method: "known-booked-net-payouts";
  version: 1;
  account: { id: number; name: string };
  instrument: { id: number; name: string };
  t0: string;
  t1: string;
  currency: "RUB";
  coverage: "unknown";
  completeness: "unknown";
  known_booked_net: { coupon: string | null; dividend: string | null };
  event_count: number;
  known_event_count: number;
  dependency_fingerprint: string | null;
  reason_codes: string[];
  events: {
    cash_flow_id: number;
    kind: "coupon" | "dividend";
    date: string;
    booked_net: string | null;
    included_in_known_net: boolean;
    proof_state:
      | "manual_booked"
      | "source_accepted"
      | "retired_or_unmatched"
      | "incomplete_unknown";
    currentness: "current" | "unavailable";
    gross: string | null;
    tax: string | null;
    fee: string | null;
    tax_available: boolean;
    receipt_ids: string[];
    provenance: string[];
    reason_codes: string[];
  }[];
};

export function getKnownPayouts(scope: PayoutScope, signal?: AbortSignal): Promise<KnownPayouts> {
  const query = new URLSearchParams({
    account_id: String(scope.accountId),
    t0: scope.t0,
    t1: scope.t1,
  });
  return apiRequest<KnownPayouts>(`/api/instruments/${scope.instrumentId}/cash-income?${query}`, {
    method: "GET",
    signal,
  });
}
