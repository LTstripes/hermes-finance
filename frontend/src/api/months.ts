import { apiRequest } from "./client";
import type { HealthResponse, ReportingMonth, ReportingMonthCreate } from "./types";

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/health", { method: "GET", signal });
}

export function listMonths(signal?: AbortSignal): Promise<ReportingMonth[]> {
  return apiRequest<ReportingMonth[]>("/api/months", { method: "GET", signal });
}

export function getMonth(monthId: number, signal?: AbortSignal): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}`, { method: "GET", signal });
}

export function createMonth(
  payload: ReportingMonthCreate,
  signal?: AbortSignal,
): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>("/api/months", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function deleteMonth(monthId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/months/${monthId}`, { method: "DELETE", signal });
}
