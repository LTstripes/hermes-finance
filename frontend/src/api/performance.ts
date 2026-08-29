import { apiRequest } from "./client";
import type { PortfolioXirr } from "./types";

export function getPortfolioXirr(
  startDate: string,
  endDate: string,
  signal?: AbortSignal,
): Promise<PortfolioXirr> {
  const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
  return apiRequest<PortfolioXirr>(`/api/performance/xirr?${query.toString()}`, {
    method: "GET",
    signal,
  });
}
