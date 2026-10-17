import { apiRequest } from "./client";
import type { PayoutScope } from "./instrumentCashIncome";

export type TradeOccurrence = {
  import_id: number;
  section: string;
  ordinal: number;
  row_fingerprint: string;
};
export type TradeLeg = {
  role: "settlement" | "paid_nkd" | "commission";
  proof_class: "effective_cash_leg_authority" | "unavailable";
  signed_rub: string | null;
  signed_kopecks: string | null;
  effective_date: string | null;
  in_interval: boolean | null;
  basis: string | null;
  receipt_id: string | null;
  occurrences: TradeOccurrence[];
  reason_codes: string[];
};
export type KnownTrade = {
  trade_id: number;
  account_id: number;
  instrument_id: number;
  source_identity: string;
  native_ids: string[];
  proof_class: "observed_native_execution";
  revision: number | null;
  currentness: "current" | "unavailable";
  historical_identity: {
    isin: string;
    instrument_type: "stock" | "bond";
    denomination: "RUB";
  } | null;
  side: "BUY" | "SELL" | null;
  signed_quantity: string | null;
  execution_date: string | null;
  execution_in_interval: boolean | null;
  settlement_date: string | null;
  settlement_in_interval: boolean | null;
  depository_date: string | null;
  depository_in_interval: boolean | null;
  planned_settlement_date: string | null;
  lifecycle: "settled" | "pending" | null;
  source_occurrences: TradeOccurrence[];
  cash_legs: TradeLeg[];
  reason_codes: string[];
};
export type KnownTrades = {
  method: "known-instrument-trades";
  version: 1;
  account: { id: number; name: string };
  instrument: { id: number; name: string };
  t0: string;
  t1: string;
  currency: "RUB";
  trade_history_completeness: "unknown";
  financial_coverage: "unknown";
  status: "available" | "capacity_exceeded";
  capacity: number;
  known_count: number | null;
  events: KnownTrade[];
  dependency_digest: string;
  dependency_fingerprint: string | null;
  currentness: "unavailable";
  reason_codes: string[];
};

export function getKnownTrades(scope: PayoutScope, signal?: AbortSignal): Promise<KnownTrades> {
  const query = new URLSearchParams({
    account_id: String(scope.accountId),
    t0: scope.t0,
    t1: scope.t1,
  });
  return apiRequest<KnownTrades>(`/api/instruments/${scope.instrumentId}/known-trades?${query}`, {
    method: "GET",
    signal,
  });
}
