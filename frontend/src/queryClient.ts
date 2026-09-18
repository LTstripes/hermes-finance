import { QueryClient } from "@tanstack/react-query";

export const queryKeys = {
  months: ["months"] as const,
  accounts: ["accounts"] as const,
  instruments: ["instruments"] as const,
  dashboard: (monthId: number | null) => ["dashboard", monthId] as const,
  monthCloseWorkflow: (monthId: number | null) => ["month-close-workflow", monthId] as const,
  closedReportComparison: ["closed-report-comparison"] as const,
  capitalComposition: ["capital-composition"] as const,
  passiveIncomeHistory: (monthId: number | null) => ["passive-income-history", monthId] as const,
  incomePlanSummary: (monthId: number | null) => ["income-plan-summary", monthId] as const,
  cashFlowLadder: (monthId: number | null) => ["cash-flow-ladder", monthId] as const,
  goalSummary: (monthId: number | null) => ["goal-summary", monthId] as const,
  planVsActual: (monthId: number | null) => ["plan-vs-actual", monthId] as const,
  savings: (monthId: number | null) => ["savings", monthId] as const,
  riskAllocation: (monthId: number | null, topN = 5, forecastVersion = "v1") =>
    ["risk-allocation", monthId, topN, forecastVersion] as const,
  cashBalances: (monthId: number | null) => ["cash-balances", monthId] as const,
  deposits: (monthId: number | null) => ["deposits", monthId] as const,
  positions: (monthId: number | null) => ["positions", monthId] as const,
  debts: (monthId: number | null) => ["debts", monthId] as const,
  properties: (monthId: number | null) => ["properties", monthId] as const,
  performanceAttribution: (startDate: string | null, endDate: string | null) =>
    ["performance-attribution", startDate, endDate] as const,
  portfolioXirr: (startDate: string | null, endDate: string | null) =>
    ["portfolio-xirr", startDate, endDate] as const,
  portfolioTwrr: (startDate: string | null, endDate: string | null) =>
    ["portfolio-twrr", startDate, endDate] as const,
  freshnessProvenance: (monthId: number | null) => ["freshness-provenance", monthId] as const,
  providerCapabilities: ["provider-capabilities"] as const,
};

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      mutations: {
        retry: false,
      },
      queries: {
        gcTime: 5 * 60 * 1000,
        refetchOnReconnect: false,
        refetchOnWindowFocus: false,
        retry: false,
        // Keep financial reads fresh when returning from an un-migrated editor.
        // The cache still retains data for key-scoped placeholder transitions.
        staleTime: 0,
      },
    },
  });
}
