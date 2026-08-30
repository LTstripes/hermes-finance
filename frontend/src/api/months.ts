import { apiRequest } from "./client";
import type {
  CloseReadiness,
  HealthResponse,
  ReportingMonth,
  ReportingMonthClone,
  ReportingMonthCreate,
  ReportingMonthUpdate,
} from "./types";

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/health", { method: "GET", signal });
}

export function listMonths(signal?: AbortSignal): Promise<ReportingMonth[]> {
  return apiRequest<ReportingMonth[]>("/api/months", { method: "GET", signal });
}

export function getMonth(monthId: number, signal?: AbortSignal): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}`, { method: "GET", signal });
}

export function getCloseReadiness(monthId: number, signal?: AbortSignal): Promise<CloseReadiness> {
  return apiRequest<CloseReadiness>(`/api/months/${monthId}/close-readiness`, {
    method: "GET",
    signal,
  });
}

export function closeMonth(monthId: number, signal?: AbortSignal): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}/close`, { method: "POST", signal });
}

export function reopenMonth(monthId: number, signal?: AbortSignal): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}/reopen`, { method: "POST", signal });
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

export function updateMonth(
  monthId: number,
  payload: ReportingMonthUpdate,
  signal?: AbortSignal,
): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteMonth(monthId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/months/${monthId}`, { method: "DELETE", signal });
}

export function cloneMonth(
  monthId: number,
  payload: ReportingMonthClone,
  signal?: AbortSignal,
): Promise<ReportingMonth> {
  return apiRequest<ReportingMonth>(`/api/months/${monthId}/clone`, {
    method: "POST",
    body: payload,
    signal,
  });
}
