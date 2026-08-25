import { apiRequest } from "./client";
import type { InvestmentFlow, InvestmentFlowCreate, InvestmentFlowUpdate } from "./types";

export function listInvestmentFlows(
  monthId: number,
  accountId?: number,
  signal?: AbortSignal,
): Promise<InvestmentFlow[]> {
  const query = new URLSearchParams({ month_id: String(monthId) });
  if (accountId != null) {
    query.set("account_id", String(accountId));
  }
  return apiRequest<InvestmentFlow[]>(`/api/investment-flows?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

export function createInvestmentFlow(
  payload: InvestmentFlowCreate,
  signal?: AbortSignal,
): Promise<InvestmentFlow> {
  return apiRequest<InvestmentFlow>("/api/investment-flows", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateInvestmentFlow(
  flowId: number,
  payload: InvestmentFlowUpdate,
  signal?: AbortSignal,
): Promise<InvestmentFlow> {
  return apiRequest<InvestmentFlow>(`/api/investment-flows/${flowId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteInvestmentFlow(flowId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/investment-flows/${flowId}`, { method: "DELETE", signal });
}
