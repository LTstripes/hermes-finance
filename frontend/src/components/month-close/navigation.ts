import type { GuidedCloseStepId } from "../../api/monthCloseWorkflow";

const STEP_IDS = new Set<GuidedCloseStepId>([
  "month_setup",
  "market_quotes",
  "actual_payouts",
  "future_payouts",
  "readiness",
  "final_review_close",
  "next_month_outlook",
]);

export type MonthlyCloseOrigin = "monthly-close-v2";

export type MonthlyCloseReturnContext = {
  monthId: number;
  origin: MonthlyCloseOrigin;
  step: GuidedCloseStepId;
};

export function isGuidedCloseStepId(value: string | null): value is GuidedCloseStepId {
  return value !== null && STEP_IDS.has(value as GuidedCloseStepId);
}

export function monthlyCloseReturnPath(context: MonthlyCloseReturnContext): string {
  const params = new URLSearchParams({
    month: String(context.monthId),
    step: context.step,
  });
  return `/v2/close?${params.toString()}`;
}

export function parseMonthlyCloseReturnContext(
  params: URLSearchParams,
): MonthlyCloseReturnContext | null {
  const monthId = Number(params.get("monthId"));
  const step = params.get("step");
  const origin = params.get("from");
  if (
    origin !== "monthly-close-v2" ||
    params.getAll("from").length !== 1 ||
    params.getAll("monthId").length !== 1 ||
    params.getAll("step").length !== 1 ||
    !Number.isInteger(monthId) ||
    monthId < 1 ||
    !isGuidedCloseStepId(step)
  ) {
    return null;
  }
  return { monthId, origin, step };
}

export function withMonthlyCloseReturn(
  path: string,
  monthId: number,
  step: GuidedCloseStepId,
  origin: MonthlyCloseOrigin = "monthly-close-v2",
): string {
  const [pathAndQuery, hash = ""] = path.split("#", 2);
  const [pathname, query = ""] = pathAndQuery.split("?", 2);
  const params = new URLSearchParams(query);
  params.set("from", origin);
  params.set("step", step);
  params.set("monthId", String(monthId));
  return `${pathname}?${params.toString()}${hash ? `#${hash}` : ""}`;
}

export function withSelectedReturnMonth(params: URLSearchParams, monthId: number): URLSearchParams {
  const next = new URLSearchParams(params);
  next.set("month", String(monthId));
  if (parseMonthlyCloseReturnContext(params)) next.set("monthId", String(monthId));
  return next;
}
