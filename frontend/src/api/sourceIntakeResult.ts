import { apiRequest } from "./client";
import type { KnownPayouts } from "./instrumentCashIncome";
import type { KnownTrades } from "./instrumentTrades";

export const assumptionKeys = [
  "no_unobserved_movements",
  "no_unobserved_payouts",
  "no_other_costs_or_taxes",
] as const;
export type Assumptions = Record<(typeof assumptionKeys)[number], boolean>;

export type SourceIntakeResultRequest = {
  intakeId: number;
  isin: string;
  t0: string;
  t1: string;
  chosen: Assumptions;
  nonce: string;
};

export type SourceIntakeResult = {
  method: "source-intake-fixed-holding-result";
  version: 1;
  authority: "hypothetical";
  request_nonce: string;
  intake: {
    id: number;
    head_seq: number;
    manifest_digest: string;
    document_sha256: string;
    covered_from: string;
    covered_to: string;
    finance_link: "present" | "absent";
    exceptions: string[];
  };
  account: { id: number; name: string } | null;
  instrument: {
    isin: string;
    instrument_type: "stock" | "bond" | null;
    hermes_id: number | null;
    name: string | null;
  };
  currency_assessment: {
    observed_denomination: string | null;
    effective_currency: string | null;
    basis: string | null;
    provisional: boolean | null;
  };
  t0: string;
  t1: string;
  interval: "(t0,t1]";
  currency: "RUB";
  observed: {
    availability: "available" | "unavailable";
    quantity: string | null;
    beginning_quantity: string | null;
    forward_quantity: string | null;
    beginning_value: string | null;
    ending_value: string | null;
    beginning_basis: "previous_day_eod";
    ending_basis: "covered_to_eod";
    value_change: string | null;
    value_change_fraction: string | null;
    value_change_percent: string | null;
    bond_nkd_basis: "unknown" | "not_applicable";
    source_row: { ordinal: number; locator: string; row_fingerprint: string } | null;
    reason_codes: string[];
  };
  known: {
    payouts: KnownPayouts | null;
    trades: KnownTrades | null;
    net_distributions: string | null;
    confirmed_cost_legs: {
      trade_id: number;
      role: "commission" | "paid_nkd";
      signed_rub: string;
      effective_date: string | null;
      in_interval: boolean | null;
      receipt_id: string | null;
    }[];
    cost_coverage: "unknown";
    reason_codes: string[];
  };
  chosen_assumptions: Assumptions;
  missing_assumptions: string[];
  hard_blockers: string[];
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

export function readSourceIntakeResult(
  request: SourceIntakeResultRequest,
  signal?: AbortSignal,
): Promise<SourceIntakeResult> {
  const query = new URLSearchParams({
    isin: request.isin,
    request_nonce: request.nonce,
    ...Object.fromEntries(assumptionKeys.map((key) => [key, String(request.chosen[key])])),
  });
  return apiRequest<SourceIntakeResult>(
    `/api/broker-months/intakes/${request.intakeId}/instrument-result?${query}`,
    { method: "GET", signal, cache: "no-store" },
  );
}

// Bind the response to this evaluation and the selected original. A digest is
// never freshness authority; a journal head change must be re-evaluated.
export function matchesSourceIntakeResult(
  data: SourceIntakeResult,
  request: SourceIntakeResultRequest,
): boolean {
  try {
    const values = [
      data.hypothetical_result.conditional_result,
      data.hypothetical_result.conditional_period_fraction,
      data.hypothetical_result.conditional_period_percent,
    ];
    const numeric = values.every(
      (value) => typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value),
    );
    const empty = values.every((value) => value === null);
    if (
      !(
        data.method === "source-intake-fixed-holding-result" &&
        data.version === 1 &&
        data.authority === "hypothetical" &&
        data.request_nonce === request.nonce &&
        data.interval === "(t0,t1]" &&
        data.currency === "RUB" &&
        data.intake.id === request.intakeId &&
        data.instrument.isin === request.isin &&
        data.t0 === request.t0 &&
        data.t1 === request.t1 &&
        data.actual_instrument_return === null &&
        data.whole_period_completeness === "unknown" &&
        data.dependency_fingerprint === null &&
        data.hypothetical_result.annualized === false &&
        data.hypothetical_result.formula === "V1-V0+P" &&
        data.hypothetical_result.percent_unit === "percentage_points" &&
        data.hypothetical_result.decimal_precision === 100 &&
        (numeric || empty) &&
        assumptionKeys.every((key) => data.chosen_assumptions[key] === request.chosen[key]) &&
        Array.isArray(data.hard_blockers) &&
        Array.isArray(data.missing_assumptions)
      )
    )
      return false;
    if (numeric) {
      return !!(
        data.hard_blockers.length === 0 &&
        data.missing_assumptions.length === 0 &&
        assumptionKeys.every((key) => request.chosen[key]) &&
        data.observed.availability === "available" &&
        data.instrument.instrument_type === "stock" &&
        data.known.net_distributions !== null
      );
    }
    return true;
  } catch {
    return false;
  }
}
