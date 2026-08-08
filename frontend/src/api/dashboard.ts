import { apiRequest } from "./client";
import type { DashboardSlice } from "./types";

export function getDashboard(monthId: number, signal?: AbortSignal): Promise<DashboardSlice> {
  return apiRequest<DashboardSlice>(`/api/months/${monthId}/dashboard`, {
    method: "GET",
    signal,
  });
}
