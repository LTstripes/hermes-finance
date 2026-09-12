import { apiRequest } from "./client";
import type { PerformanceAttribution, PortfolioTwrr, PortfolioXirr } from "./types";

export function getPerformanceAttribution(
  startDate: string,
  endDate: string,
  signal?: AbortSignal,
): Promise<PerformanceAttribution> {
  const query = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    scope: "portfolio",
  });
  return apiRequest<PerformanceAttribution>(`/api/performance/attribution?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

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

export function getPortfolioTwrr(
  startDate: string,
  endDate: string,
  signal?: AbortSignal,
): Promise<PortfolioTwrr> {
  const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
  return apiRequest<PortfolioTwrr>(`/api/performance/twrr?${query.toString()}`, {
    method: "GET",
    signal,
  });
}
