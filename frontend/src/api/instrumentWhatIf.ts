import { apiRequest } from "./client";
import type { KnownPayouts, PayoutScope } from "./instrumentCashIncome";
import type { EodObservation } from "./instrumentEodObservations";
import type { KnownTrades } from "./instrumentTrades";

export const assumptionKeys = [
  "no_unobserved_movements",
  "no_unobserved_payouts",
  "no_other_costs_or_taxes",
] as const;
export type Assumptions = Record<(typeof assumptionKeys)[number], boolean>;
export type WhatIfRequest = { scope: PayoutScope; chosen: Assumptions; nonce: string };
export type InstrumentWhatIfResult = {
  method: "hypothetical-fixed-stock-hpr";
  version: 1;
  authority: "hypothetical";
  request_nonce: string;
  account: { id: number; name: string };
  instrument: { id: number; name: string };
  t0: string;
  t1: string;
  interval: "(t0,t1]";
  currency: "RUB";
  observed: { opening: EodObservation; closing: EodObservation; comparable: boolean | null } | null;
  accepted_known: { payouts: KnownPayouts | null; trades: KnownTrades | null };
  chosen_assumptions: Assumptions;
  missing_assumptions: string[];
  hard_blockers: string[];
  source_checks: { source_import_id: number; reason_codes: string[] }[];
  hypothetical_result: {
    conditional_result: string | null;
    conditional_period_fraction: string | null;
    conditional_period_percent: string | null;
    percent_unit: "percentage_points";
    annualized: false;
    formula: "V1-V0+P";
    decimal_precision: 100;
  };
  actual_instrument_return: null;
  whole_period_completeness: "unknown";
  dependency_fingerprint: null;
};

export function evaluateInstrumentWhatIf(request: WhatIfRequest, signal?: AbortSignal) {
  const query = new URLSearchParams({
    account_id: String(request.scope.accountId),
    t0: request.scope.t0,
    t1: request.scope.t1,
    request_nonce: request.nonce,
    ...Object.fromEntries(assumptionKeys.map((k) => [k, String(request.chosen[k])])),
  });
  return apiRequest<InstrumentWhatIfResult>(
    `/api/instruments/${request.scope.instrumentId}/conditional-return?${query}`,
    { method: "GET", signal, cache: "no-store" },
  );
}

// Bind the response to this evaluation, including its nested canonical readers.
// Never use a digest (especially #862's NULL fingerprint) as freshness authority.
export function matchesWhatIf(data: InstrumentWhatIfResult, request: WhatIfRequest): boolean {
  try {
    const { scope } = request;
    const sameScope = (d: {
      account: { id: number };
      instrument: { id: number };
      t0: string;
      t1: string;
      currency: string;
    }) =>
      d.account.id === scope.accountId &&
      d.instrument.id === scope.instrumentId &&
      d.t0 === scope.t0 &&
      d.t1 === scope.t1 &&
      d.currency === "RUB";
    const h = data.hypothetical_result;
    const values = [
      h.conditional_result,
      h.conditional_period_fraction,
      h.conditional_period_percent,
    ];
    const numeric = values.every((v) => typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v));
    const empty = values.every((v) => v === null);
    if (
      !(
        sameScope(data) &&
        data.method === "hypothetical-fixed-stock-hpr" &&
        data.version === 1 &&
        data.authority === "hypothetical" &&
        data.request_nonce === request.nonce &&
        data.interval === "(t0,t1]" &&
        data.actual_instrument_return === null &&
        data.whole_period_completeness === "unknown" &&
        data.dependency_fingerprint === null &&
        h.annualized === false &&
        h.formula === "V1-V0+P" &&
        h.percent_unit === "percentage_points" &&
        h.decimal_precision === 100 &&
        (numeric || empty) &&
        assumptionKeys.every((k) => data.chosen_assumptions[k] === request.chosen[k]) &&
        Array.isArray(data.hard_blockers) &&
        Array.isArray(data.missing_assumptions)
      )
    )
      return false;
    const p = data.accepted_known.payouts;
    const t = data.accepted_known.trades;
    if (p && !(sameScope(p) && p.method === "known-booked-net-payouts" && p.version === 1))
      return false;
    if (
      t &&
      !(
        sameScope(t) &&
        t.method === "known-instrument-trades" &&
        t.version === 1 &&
        t.dependency_fingerprint === null &&
        t.events.every(
          (e) => e.account_id === scope.accountId && e.instrument_id === scope.instrumentId,
        )
      )
    )
      return false;
    if (
      data.observed &&
      ![data.observed.opening, data.observed.closing].every(
        (b, i) =>
          b.account_id === scope.accountId &&
          b.instrument_id === scope.instrumentId &&
          b.date === (i === 0 ? scope.t0 : scope.t1) &&
          b.currency === "RUB",
      )
    )
      return false;
    if (numeric)
      return !!(
        data.hard_blockers.length === 0 &&
        data.missing_assumptions.length === 0 &&
        assumptionKeys.every((k) => request.chosen[k]) &&
        data.observed?.comparable === true &&
        [data.observed.opening, data.observed.closing].every(
          (b) =>
            b.availability === "available" &&
            b.currentness === "current" &&
            b.historical_identity?.instrument_type === "stock" &&
            b.historical_identity.denomination === "RUB" &&
            b.bond_nkd_basis === "not_applicable",
        ) &&
        p &&
        p.events.length > 0 &&
        p.events.every(
          (e) => e.included_in_known_net && e.kind === "dividend" && e.currentness === "current",
        ) &&
        t?.known_count === 0 &&
        t.events.length === 0 &&
        t.status === "available" &&
        data.source_checks.length > 0
      );
    return true;
  } catch {
    return false;
  }
}
