import { apiRequest } from "./client";
import type { DashboardSlice } from "./types";

export function getDashboard(
  monthId: number,
  signal?: AbortSignal,
  includeCapitalChange = true,
): Promise<DashboardSlice> {
  return apiRequest<DashboardSlice>(
    `/api/months/${monthId}/dashboard${includeCapitalChange ? "" : "?include_capital_change=false"}`,
    {
      method: "GET",
      signal,
    },
  );
}
