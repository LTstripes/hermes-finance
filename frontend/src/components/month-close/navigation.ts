import type { GuidedCloseActionId, GuidedCloseStepId } from "../../api/monthCloseWorkflow";

const STEP_IDS = new Set<GuidedCloseStepId>([
  "month_setup",
  "alfa_baseline",
  "market_quotes",
  "actual_payouts",
  "future_payouts",
  "broker_reconciliation",
  "readiness",
  "final_review_close",
  "next_month_outlook",
]);

export type MonthlyCloseReturnContext = { monthId: number; step: GuidedCloseStepId };

export function parseMonthlyCloseReturnContext(
  params: URLSearchParams,
): MonthlyCloseReturnContext | null {
  const monthId = Number(params.get("monthId"));
  const step = params.get("step") as GuidedCloseStepId | null;
  if (
    params.get("from") !== "monthly-close" ||
    !Number.isInteger(monthId) ||
    monthId < 1 ||
    !step ||
    !STEP_IDS.has(step)
  ) {
    return null;
  }
  return { monthId, step };
}

export function withMonthlyCloseReturn(
  path: string,
  monthId: number,
  step: GuidedCloseStepId,
): string {
  const [pathAndQuery, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = pathAndQuery.split("?", 2);
  const params = new URLSearchParams(query);
  params.set("from", "monthly-close");
  params.set("step", step);
  params.set("monthId", String(monthId));
  return `${pathname}?${params.toString()}${hash ? `#${hash}` : ""}`;
}

const ACTION_PATHS: Record<GuidedCloseActionId, (monthId: number) => string> = {
  open_month: (monthId) => `/months/${monthId}`,
  set_snapshot_date: (monthId) => `/months/${monthId}?section=general`,
  open_alfa_preview: () => "/accounts",
  open_quote_preview: (monthId) => `/months/${monthId}?section=positions`,
  choose_statement_file: () => "/payouts",
  open_payout_batch_preview: () => "/payouts",
  open_reconciliation_preview: () => "/reconciliation",
  open_freshness: () => "/freshness",
  open_final_review: (monthId) => `/months/${monthId}/close#final_review_close`,
  confirm_close: (monthId) => `/months/${monthId}/close#final_review_close`,
  open_cash_flow_ladder: () => "/payouts",
  clone_next_month: () => "/months",
};

export function routeForGuidedAction(
  actionId: GuidedCloseActionId,
  monthId: number,
  step: GuidedCloseStepId,
): string {
  return withMonthlyCloseReturn(ACTION_PATHS[actionId](monthId), monthId, step);
}
