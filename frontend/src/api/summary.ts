import { apiRequest } from "./client";
import type { MonthSummary } from "./types";

export function getMonthSummary(monthId: number, signal?: AbortSignal): Promise<MonthSummary> {
  return apiRequest<MonthSummary>(`/api/months/${monthId}/summary`, {
    method: "GET",
    signal,
  });
}
