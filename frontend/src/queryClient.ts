import { QueryClient } from "@tanstack/react-query";

export const queryKeys = {
  months: ["months"] as const,
  accounts: ["accounts"] as const,
  instruments: ["instruments"] as const,
  dashboard: (monthId: number | null) => ["dashboard", monthId] as const,
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
