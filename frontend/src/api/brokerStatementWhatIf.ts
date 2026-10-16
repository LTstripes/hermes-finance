import type { BrokerStatementReturn } from "./brokerStatementReturn";
import { apiMultipart } from "./client";

export type WhatIfFlow = {
  source_reference: string;
  event_date: string;
  signed_amount_kopecks: string;
  provenance: "accepted_h2" | "assumed_native_incoming";
};
export type WhatIfChoice =
  | "native_totals_continuously"
  | "use_displayed_schedule"
  | "include_as_account_inflow"
  | "exclude_from_external_schedule"
  | "no_other_account_crossings"
  | "no_additional_flow_or_adjustment"
  | "no_additional_channel_effect";
export type WhatIfRequirement = {
  requirement_id: string;
  subject: string;
  slot: "native_basis" | "schedule" | "remaining_crossings" | "money_basis" | "residual";
  source_references: string[];
  choices: WhatIfChoice[];
};
export type WhatIfAssumptions = {
  version: "account_native_what_if_v1";
  schedule_mode: "explicit_empty" | "dated" | null;
  selections: {
    requirement_id: string;
    source_references: string[];
    choice: WhatIfChoice;
  }[];
};
export type WhatIfContext = {
  kind: "broker_statement_what_if_context_v1";
  method: "broker_statement_what_if_mwr_period_v1";
  scope: "account";
  account_id: number;
  request_id: string;
  t0: string;
  t1: string;
  observed: {
    opening: BrokerStatementReturn["opening"] | null;
    closing: BrokerStatementReturn["closing"] | null;
    capital_delta_kopecks: string | null;
  };
  actual_result: BrokerStatementReturn;
  diagnostic_inventory: Record<string, unknown>;
  fixed_schedule: WhatIfFlow[];
  optional_candidate: WhatIfFlow | null;
  required_assumptions: WhatIfRequirement[];
  hard_blockers: string[];
  limitations: string[];
  context_fingerprint: string;
};
export type WhatIfResult = {
  kind: "broker_statement_what_if_result_v1";
  method: "broker_statement_what_if_mwr_period_v1";
  scope: "account";
  authority: "hypothetical";
  currency: "RUB";
  annualized: false;
  status: "hypothetical" | "needs_assumptions" | "blocked";
  account_id: number;
  request_id: string;
  t0: string;
  t1: string;
  scenario_result_kopecks: string | null;
  scenario_rate_fraction: string | null;
  assumed_schedule: WhatIfFlow[];
  assumptions: WhatIfAssumptions;
  actual_result: BrokerStatementReturn;
  context: WhatIfContext;
  limitations: string[];
  reason_codes: string[];
  context_fingerprint: string;
  assumption_fingerprint: string;
  result_fingerprint: string;
};

export function whatIfRequest<T extends WhatIfContext | WhatIfResult>(
  operation: "context" | "evaluate" | "export",
  actual: BrokerStatementReturn,
  file: File,
  signal: AbortSignal,
  context?: WhatIfContext,
  assumptions?: WhatIfAssumptions,
  result?: WhatIfResult,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("account_id", String(actual.account_id));
  form.append("request_id", actual.sources[0].request_id);
  form.append("expected_actual_fingerprint", actual.material_fingerprint);
  if (context) form.append("expected_context_fingerprint", context.context_fingerprint);
  if (assumptions) form.append("assumptions", JSON.stringify(assumptions));
  if (result) form.append("expected_result_fingerprint", result.result_fingerprint);
  return apiMultipart<T>(`/api/broker-statement-what-if/${operation}`, form, signal);
}

export function contextMatches(context: WhatIfContext, actual: BrokerStatementReturn) {
  return (
    context.kind === "broker_statement_what_if_context_v1" &&
    context.method === "broker_statement_what_if_mwr_period_v1" &&
    context.scope === "account" &&
    context.account_id === actual.account_id &&
    context.request_id === actual.sources[0].request_id &&
    context.t0 === actual.t0 &&
    context.t1 === actual.t1 &&
    context.actual_result.material_fingerprint === actual.material_fingerprint &&
    context.actual_result.account_id === actual.account_id &&
    context.actual_result.t0 === actual.t0 &&
    context.actual_result.t1 === actual.t1 &&
    /^[0-9a-f]{64}$/.test(context.context_fingerprint)
  );
}

export function resultMatches(
  result: WhatIfResult,
  context: WhatIfContext,
  actual: BrokerStatementReturn,
  assumptions: WhatIfAssumptions,
) {
  return (
    result.kind === "broker_statement_what_if_result_v1" &&
    result.method === context.method &&
    result.scope === "account" &&
    result.authority === "hypothetical" &&
    result.currency === "RUB" &&
    result.annualized === false &&
    result.account_id === context.account_id &&
    result.request_id === context.request_id &&
    result.t0 === context.t0 &&
    result.t1 === context.t1 &&
    result.actual_result.material_fingerprint === actual.material_fingerprint &&
    JSON.stringify(result.actual_result) === JSON.stringify(actual) &&
    result.context_fingerprint === context.context_fingerprint &&
    result.context.context_fingerprint === context.context_fingerprint &&
    contextMatches(result.context, actual) &&
    JSON.stringify(result.assumptions) === JSON.stringify(assumptions) &&
    /^[0-9a-f]{64}$/.test(result.result_fingerprint) &&
    ["hypothetical", "needs_assumptions", "blocked"].includes(result.status) &&
    (result.status === "hypothetical"
      ? typeof result.scenario_result_kopecks === "string" &&
        /^-?\d+$/.test(result.scenario_result_kopecks) &&
        typeof result.scenario_rate_fraction === "string" &&
        /^-?\d+(\.\d+)?$/.test(result.scenario_rate_fraction)
      : result.scenario_result_kopecks === null && result.scenario_rate_fraction === null)
  );
}
