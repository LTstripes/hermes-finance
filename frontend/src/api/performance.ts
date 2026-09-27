import { apiRequest } from "./client";
import type {
  PerformanceAttribution,
  PerformanceReadiness,
  PerformanceReadinessScope,
  PortfolioTwrr,
  PortfolioXirr,
} from "./types";

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

/**
 * Coherent read-only readiness projection (accepted #530).
 * Composes canonical availability with the final XIRR/TWRR results.
 * No client-side financial calculation; values/units come from the backend.
 */
export function getPerformanceReadiness(
  startDate: string,
  endDate: string,
  scope: PerformanceReadinessScope = "portfolio",
  accountId?: number | null,
  signal?: AbortSignal,
): Promise<PerformanceReadiness> {
  const query = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    scope,
  });
  if (scope === "account" && accountId !== undefined && accountId !== null) {
    query.set("account_id", String(accountId));
  }
  return apiRequest<PerformanceReadiness>(`/api/performance/readiness?${query.toString()}`, {
    method: "GET",
    signal,
  });
}
