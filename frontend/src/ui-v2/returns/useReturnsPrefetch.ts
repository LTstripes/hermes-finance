import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { getContext, getOverview } from "./model";
import { getOverall } from "./overall";

/** Warm the neighbouring tab only after the current screen has useful data. */
export function useReturnsPrefetch(current: "overall" | "account", ready: boolean) {
  const client = useQueryClient();
  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    const warm = async () => {
      if (stopped || client.isFetching() || client.isMutating()) return;
      if (current === "account") {
        await client.prefetchQuery({
          queryKey: ["returns", "overall", "summaries"],
          queryFn: ({ signal }) => getOverall(signal, true),
          staleTime: 5 * 60 * 1000,
        });
        return;
      }
      const context = await client.fetchQuery({
        queryKey: ["returns", "context"],
        queryFn: ({ signal }) => getContext(signal),
        staleTime: 5 * 60 * 1000,
      });
      // A write cancels inactive reads and invalidates context. Never continue
      // a pre-write prefetch chain or select a different default than the page.
      if (
        stopped ||
        client.isMutating() ||
        client.getQueryState(["returns", "context"])?.isInvalidated
      )
        return;
      const account =
        context.accounts.find(
          (a) => a.id !== "portfolio" && (context.source_periods[a.id]?.length ?? 0) > 0,
        ) ?? context.accounts.find((a) => a.id === "portfolio");
      if (!account) return;
      const period = context.default_period ?? context.source_periods[account.id]?.at(-1);
      if (!period) return;
      await client.prefetchQuery({
        queryKey: ["returns", "overview", account.id, period.start, period.end],
        queryFn: ({ signal }) => getOverview(account.id, period, signal),
        staleTime: 5 * 60 * 1000,
      });
    };
    // Leave the initial render and its secondary requests ahead of prefetch.
    const timer = setTimeout(() => void warm().catch(() => undefined), 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [client, current, ready]);
}
