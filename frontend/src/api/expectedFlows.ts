import { apiRequest } from "./client";
import type { ExpectedFlow, ExpectedFlowCreate } from "./types";

export function listExpectedFlows(
  monthId: number,
  forecastVersion: string,
  signal?: AbortSignal,
): Promise<ExpectedFlow[]> {
  const query = new URLSearchParams({
    month_id: String(monthId),
    forecast_version: forecastVersion,
  });
  return apiRequest<ExpectedFlow[]>(`/api/expected-flows?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

export function createExpectedFlow(
  payload: ExpectedFlowCreate,
  signal?: AbortSignal,
): Promise<ExpectedFlow> {
  return apiRequest<ExpectedFlow>("/api/expected-flows", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function deleteExpectedFlow(flowId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/expected-flows/${flowId}`, { method: "DELETE", signal });
}
