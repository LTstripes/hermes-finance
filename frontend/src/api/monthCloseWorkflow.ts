import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../queryClient";
import { apiRequest } from "./client";

export type GuidedCloseStepId =
  | "month_setup"
  | "alfa_baseline"
  | "market_quotes"
  | "actual_payouts"
  | "future_payouts"
  | "broker_reconciliation"
  | "readiness"
  | "final_review_close"
  | "next_month_outlook";

export type GuidedCloseActionId =
  | "open_month"
  | "set_snapshot_date"
  | "open_alfa_preview"
  | "open_quote_preview"
  | "choose_statement_file"
  | "open_payout_batch_preview"
  | "open_reconciliation_preview"
  | "open_freshness"
  | "open_final_review"
  | "confirm_close"
  | "open_cash_flow_ladder"
  | "clone_next_month";

export type WorkflowAction = {
  id: GuidedCloseActionId;
  label: string;
  target: "open_panel" | "internal_route" | "confirm_close";
};

export type GuidedCloseStep = {
  id: GuidedCloseStepId;
  order: number;
  title: string;
  state: "not_started" | "ready" | "completed" | "skipped" | "warning" | "blocked";
  applicability: "mandatory" | "conditional" | "not_applicable";
  gate: "must_resolve" | "owner_decision" | "advisory" | "none";
  affects_close: boolean;
  why: string;
  reason_codes: string[];
  primary_action: WorkflowAction | null;
  secondary_actions: WorkflowAction[];
  completion_basis: string | null;
  evidence_scope: string;
  evidence_version: string | null;
  evidence_summary: Record<string, unknown>;
  stale: { is_stale: boolean; reason_codes: string[] };
  diagnostics: Record<string, unknown>;
};

export type MonthCloseWorkflow = {
  contract_version: "monthly_close_workflow_v1";
  generated_at: string;
  month: {
    id: number;
    year: number;
    month: number;
    status: "draft" | "closed";
    snapshot_date: string | null;
    source: string;
  };
  recommended_step_id: GuidedCloseStepId | null;
  progress: { completed_or_skipped: number; total_applicable: number };
  steps: GuidedCloseStep[];
  readiness: {
    can_close: boolean;
    hard_blocker_count: number;
    warning_count: number;
    reason_codes: string[];
  };
  freshness: {
    available: boolean;
    evaluated_on: string | null;
    quote_valuation_target_date: string | null;
    families: Array<Record<string, unknown>>;
    reason_codes: string[];
  };
  final_review: { available: boolean; reason_code: string | null };
  outlook: { available: boolean; reason_code: string | null } | null;
  links: { month: string; close_readiness: string; freshness: string };
};

export function getMonthCloseWorkflow(
  monthId: number,
  signal?: AbortSignal,
): Promise<MonthCloseWorkflow> {
  return apiRequest<MonthCloseWorkflow>(`/api/months/${monthId}/close-workflow`, {
    method: "GET",
    signal,
  });
}

export function useMonthCloseWorkflow(monthId: number | null) {
  return useQuery({
    enabled: monthId !== null,
    queryKey: queryKeys.monthCloseWorkflow(monthId),
    queryFn: ({ signal }) => getMonthCloseWorkflow(monthId as number, signal),
    refetchOnWindowFocus: true,
  });
}
