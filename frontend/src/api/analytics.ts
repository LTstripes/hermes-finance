import { apiRequest } from "./client";
import type {
  CapitalCompositionHistory,
  ClosedReportComparison,
  PassiveIncomeHistory,
} from "./types";

export function getCapitalComposition(signal?: AbortSignal): Promise<CapitalCompositionHistory> {
  return apiRequest<CapitalCompositionHistory>("/api/analytics/capital-composition", {
    method: "GET",
    signal,
  });
}

export function getClosedReportComparison(signal?: AbortSignal): Promise<ClosedReportComparison> {
  return apiRequest<ClosedReportComparison>("/api/analytics/closed-report-comparison", {
    method: "GET",
    signal,
  });
}

export function getPassiveIncomeHistory(
  reportingMonthId: number,
  signal?: AbortSignal,
): Promise<PassiveIncomeHistory> {
  const params = new URLSearchParams({ reporting_month_id: String(reportingMonthId) });
  return apiRequest<PassiveIncomeHistory>(`/api/analytics/passive-income?${params.toString()}`, {
    method: "GET",
    signal,
  });
}
