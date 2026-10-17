import { apiRequest } from "./client";
import type { KnownPayouts, PayoutScope } from "./instrumentCashIncome";

export type EodObservation = {
  date: string;
  account_id: number;
  instrument_id: number;
  availability: "available" | "unavailable";
  quantity: string | null;
  market_value: string | null;
  currency: "RUB";
  historical_identity: {
    isin: string;
    instrument_type: "stock" | "bond";
    denomination: "RUB";
  } | null;
  bond_nkd_basis: "unknown" | "included" | "excluded" | "not_applicable" | null;
  price_date: string | null;
  position_id: number | null;
  price_source: string | null;
  source_import_id: number | null;
  source_row_key: string | null;
  receipt_ids: string[];
  revision_generation: number | null;
  proof_state: "source_accepted" | "unavailable";
  currentness: "current" | "unavailable";
  dependency_fingerprint: string | null;
  reason_codes: string[];
};
export type InstrumentObservations = {
  method: "persisted-instrument-eod-pair";
  version: 1;
  account: { id: number; name: string };
  instrument: { id: number; name: string };
  t0: string;
  t1: string;
  currency: "RUB";
  opening: EodObservation;
  closing: EodObservation;
  comparable: boolean | null;
  observed_position_value_difference: string | null;
  reason_codes: string[];
  dependency_fingerprint: string | null;
  valuation_dependency_fingerprint: string | null;
  known_payouts: KnownPayouts;
};
export function getInstrumentObservations(
  scope: PayoutScope,
  signal?: AbortSignal,
): Promise<InstrumentObservations> {
  const query = new URLSearchParams({
    account_id: String(scope.accountId),
    t0: scope.t0,
    t1: scope.t1,
  });
  return apiRequest<InstrumentObservations>(
    `/api/instruments/${scope.instrumentId}/eod-observations?${query}`,
    { method: "GET", signal },
  );
}
