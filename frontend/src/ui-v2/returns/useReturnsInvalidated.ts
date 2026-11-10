import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

/** Invalidation can happen without a refetch; retire saved figures immediately. */
export function useReturnsInvalidated(queryKey: QueryKey) {
  const client = useQueryClient();
  return useSyncExternalStore(
    (changed) => client.getQueryCache().subscribe(changed),
    () => client.getQueryState(queryKey)?.isInvalidated ?? false,
  );
}
