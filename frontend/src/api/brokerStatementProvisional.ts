import { apiMultipart } from "./client";
import type { SourceIntake } from "./sourceIntake";

export type ProvisionalChoice =
  | "native_totals_continuously"
  | "use_displayed_schedule"
  | "include_as_account_inflow"
  | "exclude_from_external_schedule"
  | "no_other_account_crossings"
  | "no_additional_flow_or_adjustment"
  | "native_totals_include_REPO_as_reported"
  | "unparsed_rows_reflected_in_native_totals";
export type ProvisionalSlot =
  | "native_basis"
  | "schedule"
  | "candidate"
  | "remaining_crossings"
  | "trades_money_basis"
  | "repo_basis"
  | "unparsed_basis";
export type ProvisionalRequirement = {
  requirement_id: string;
  subject: string;
  slot: ProvisionalSlot;
  source_references: string[];
  choices: ProvisionalChoice[];
};
export type ProvisionalFlow = {
  source_reference: string;
  event_date: string;
  signed_amount_kopecks: string;
  source_amount: string;
  provenance: "assumed_native_incoming";
};
export type ProvisionalKnownPayout = {
  source_reference: string;
  event_date: string;
  kind: "coupon_paid_candidate" | "trade_paid_nkd_candidate";
  source_amount: string;
  amount_kopecks: string | null;
};
export type ProvisionalPosition = {
  source_reference: string;
  isin: string;
  ordinal: number;
  beginning_quantity: string | null;
  ending_quantity: string | null;
  beginning_value: string | null;
  ending_value: string | null;
  beginning_value_kopecks: string | null;
  ending_value_kopecks: string | null;
};
export type ProvisionalCash = {
  source_reference: string;
  beginning_amount: string | null;
  ending_amount: string | null;
  beginning_kopecks: string | null;
  ending_kopecks: string | null;
};
export type ProvisionalObserved = {
  positions_value_opening_kopecks: string | null;
  cash_opening_kopecks: string | null;
  total_opening_kopecks: string | null;
  positions_value_closing_kopecks: string | null;
  cash_closing_kopecks: string | null;
  total_closing_kopecks: string | null;
  reported_value_change_kopecks: string | null;
  positions: ProvisionalPosition[];
  cash: ProvisionalCash | null;
};
export type ProvisionalJournal = {
  intake_id: number;
  head_seq: number;
  manifest_digest: string;
  document_sha256: string;
  parser: string;
  finance_link_present: boolean;
  exceptions: string[];
};
export type ProvisionalContext = {
  kind: "broker_source_provisional_context_v1";
  method: "broker_source_provisional_mwr_period_v1";
  scope: "account";
  authority: "provisional";
  currency: "RUB";
  annualized: false;
  intake_id: number;
  account_id: number;
  t0: string;
  t1: string;
  journal: ProvisionalJournal;
  observed: ProvisionalObserved;
  candidates: ProvisionalFlow[];
  known_payouts: ProvisionalKnownPayout[];
  required_assumptions: ProvisionalRequirement[];
  hard_blockers: string[];
  limitations: string[];
  context_fingerprint: string;
};
export type ProvisionalAssumptions = {
  version: "source_intake_provisional_v1";
  schedule_mode: "explicit_empty" | "dated" | null;
  selections: {
    requirement_id: string;
    source_references: string[];
    choice: ProvisionalChoice;
  }[];
};
export type ProvisionalAlternative = {
  label: string;
  scenario_result_kopecks: string;
  scenario_rate_fraction: string;
  included_candidate_references: string[];
};
export type ProvisionalResult = {
  kind: "broker_source_provisional_result_v1";
  method: "broker_source_provisional_mwr_period_v1";
  scope: "account";
  authority: "provisional";
  currency: "RUB";
  annualized: false;
  status: "provisional" | "needs_assumptions" | "blocked";
  intake_id: number;
  account_id: number;
  t0: string;
  t1: string;
  reported_value_change_kopecks: string | null;
  scenario_result_kopecks: string | null;
  scenario_rate_fraction: string | null;
  assumed_schedule: ProvisionalFlow[];
  assumptions: ProvisionalAssumptions;
  context: ProvisionalContext;
  alternatives: ProvisionalAlternative[];
  limitations: string[];
  reason_codes: string[];
  context_fingerprint: string;
  assumption_fingerprint: string;
  result_fingerprint: string;
};

export function provisionalRequest<T extends ProvisionalContext | ProvisionalResult>(
  operation: "context" | "evaluate" | "export",
  intake: SourceIntake,
  file: File,
  signal: AbortSignal,
  context?: ProvisionalContext,
  assumptions?: ProvisionalAssumptions,
  result?: ProvisionalResult,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("intake_id", String(intake.id));
  form.append("expected_manifest_digest", intake.manifest_digest);
  if (context) form.append("expected_context_fingerprint", context.context_fingerprint);
  if (assumptions) form.append("assumptions", JSON.stringify(assumptions));
  if (result) form.append("expected_result_fingerprint", result.result_fingerprint);
  return apiMultipart<T>(`/api/broker-statement-provisional/${operation}`, form, signal);
}

const fingerprint = (value: string) => /^[0-9a-f]{64}$/.test(value);

export function contextMatches(context: ProvisionalContext, intake: SourceIntake) {
  return (
    context.kind === "broker_source_provisional_context_v1" &&
    context.method === "broker_source_provisional_mwr_period_v1" &&
    context.scope === "account" &&
    context.authority === "provisional" &&
    context.currency === "RUB" &&
    context.annualized === false &&
    context.intake_id === intake.id &&
    intake.state.account_id !== null &&
    context.account_id === intake.state.account_id &&
    context.t1 === intake.covered_to &&
    context.journal.intake_id === intake.id &&
    context.journal.head_seq === intake.head_seq &&
    context.journal.manifest_digest === intake.manifest_digest &&
    context.journal.document_sha256 === intake.document_sha256 &&
    fingerprint(context.context_fingerprint)
  );
}

export function resultMatches(
  result: ProvisionalResult,
  context: ProvisionalContext,
  assumptions: ProvisionalAssumptions,
) {
  return (
    result.kind === "broker_source_provisional_result_v1" &&
    result.method === context.method &&
    result.scope === "account" &&
    result.authority === "provisional" &&
    result.currency === "RUB" &&
    result.annualized === false &&
    result.intake_id === context.intake_id &&
    result.account_id === context.account_id &&
    result.t0 === context.t0 &&
    result.t1 === context.t1 &&
    result.context_fingerprint === context.context_fingerprint &&
    result.context.context_fingerprint === context.context_fingerprint &&
    JSON.stringify(result.context) === JSON.stringify(context) &&
    JSON.stringify(result.assumptions) === JSON.stringify(assumptions) &&
    result.reported_value_change_kopecks === context.observed.reported_value_change_kopecks &&
    ["provisional", "needs_assumptions", "blocked"].includes(result.status) &&
    (result.status === "provisional"
      ? typeof result.scenario_result_kopecks === "string" &&
        /^-?\d+$/.test(result.scenario_result_kopecks) &&
        typeof result.scenario_rate_fraction === "string" &&
        /^-?\d+(\.\d+)?$/.test(result.scenario_rate_fraction)
      : result.scenario_result_kopecks === null && result.scenario_rate_fraction === null) &&
    fingerprint(result.result_fingerprint)
  );
}
