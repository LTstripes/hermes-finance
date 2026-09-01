import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../queryClient";
import { apiRequest } from "./client";
import type {
  CashFlowLadderEvent,
  CloseReadiness,
  DashboardKpis,
  InstrumentClassResultPoint,
  MoneyValue,
  UpcomingEventsWindow,
} from "./types";

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

export type WorkflowMonth = {
  id: number;
  year: number;
  month: number;
  status: "draft" | "closed";
  snapshot_date: string | null;
  source: string;
};

export type WorkflowFreshness = {
  available: boolean;
  evaluated_on: string | null;
  quote_valuation_target_date: string | null;
  families: Array<Record<string, unknown>>;
  reason_codes: string[];
};

export type ManualReviewCard = {
  id: string;
  title: string;
  available: boolean;
  reason_code: string | null;
  summary: Record<string, unknown>;
};

export type ManualAttention = {
  card_id: string;
  severity: "hard_blocker" | "warning" | string;
  code: string;
  message: string;
  context: Record<string, unknown>;
};

export type FinalMonthReview = {
  available: true;
  reason_code: string | null;
  month_header: WorkflowMonth;
  kpis: DashboardKpis;
  assets_and_cash: {
    available: boolean;
    reason_code: string | null;
    liquid_capital: {
      total_assets: MoneyValue;
      total_debts_included: MoneyValue;
      liquid_capital_net: MoneyValue;
      breakdown: {
        cash: MoneyValue;
        deposits: MoneyValue;
        securities: MoneyValue;
        other_liquid_assets: MoneyValue;
      };
      accounts: Array<{ account_id: number; amount: MoneyValue }>;
    } | null;
    current_cash: MoneyValue | null;
    cash_row_count: number;
  };
  debts_and_property: {
    available: boolean;
    reason_code: string | null;
    debt_total: MoneyValue | null;
    property_value: MoneyValue | null;
    mortgage_balance: MoneyValue | null;
    debt_row_count: number;
    property_row_count: number;
  };
  investments: {
    available: boolean;
    reason_code: string | null;
    position_count: number;
    market_value: MoneyValue | null;
    manual_price_count: number;
    actual_flow_count: number;
    future_flow_count: number;
    by_instrument_class: InstrumentClassResultPoint[];
  };
  actual_passive_income: MoneyValue;
  important_future_events: {
    available: boolean;
    reason_code: string | null;
    upcoming_14_days: UpcomingEventsWindow | null;
    upcoming_30_days: UpcomingEventsWindow | null;
    next_month: {
      year: number;
      month: number;
      known_event_count: number;
      has_known_events: boolean;
      passive_income: MoneyValue | null;
      redemption_principal: MoneyValue | null;
      total_cash_flow: MoneyValue | null;
      deposit_interest_estimate: MoneyValue | null;
      items: CashFlowLadderEvent[];
    } | null;
    known_event_count: number;
  };
  provider_summary: Array<Record<string, unknown>>;
  reconciliation_availability: Record<string, unknown>;
  freshness_summary: WorkflowFreshness;
  close_readiness: CloseReadiness;
  manual_review_cards: ManualReviewCard[];
  manual_attention: ManualAttention[];
  evidence_version: string;
};

export type FinalMonthReviewUnavailable = {
  available: false;
  reason_code: string | null;
};

export type NextMonthBucket = {
  year: number;
  month: number;
  known_event_count: number;
  has_known_events: boolean;
  passive_income: MoneyValue | null;
  redemption_principal: MoneyValue | null;
  total_cash_flow: MoneyValue | null;
  deposit_interest_estimate: MoneyValue | null;
  items: CashFlowLadderEvent[];
};

export type NextMonthOutlook = {
  available: boolean;
  reason_code: string | null;
  source_month: WorkflowMonth;
  next_month: NextMonthBucket | null;
  upcoming_14_days: UpcomingEventsWindow | null;
  upcoming_30_days: UpcomingEventsWindow | null;
  known_event_count: number;
  evidence_version: string | null;
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
  final_review: FinalMonthReview | FinalMonthReviewUnavailable;
  outlook: NextMonthOutlook | null;
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
