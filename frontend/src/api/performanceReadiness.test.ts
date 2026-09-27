import { afterEach, describe, expect, it, vi } from "vitest";

import { getPerformanceReadiness } from "./performance";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubFetch() {
  const calls: Array<{ url: string; signal?: AbortSignal }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      calls.push({ url: String(input), signal: options?.signal ?? undefined });
      return new Response(JSON.stringify({ schema_version: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

describe("getPerformanceReadiness", () => {
  it("requests the portfolio projection with scope and dates", async () => {
    const calls = stubFetch();
    await getPerformanceReadiness("2031-05-31", "2031-07-31", "portfolio", null);
    expect(calls).toHaveLength(1);
    const url = new URL(calls[0].url, "http://localhost");
    expect(url.pathname).toBe("/api/performance/readiness");
    expect(url.searchParams.get("start_date")).toBe("2031-05-31");
    expect(url.searchParams.get("end_date")).toBe("2031-07-31");
    expect(url.searchParams.get("scope")).toBe("portfolio");
    expect(url.searchParams.get("account_id")).toBeNull();
  });

  it("requests an explicit account scope with cancellation support", async () => {
    const calls = stubFetch();
    const controller = new AbortController();
    await getPerformanceReadiness("2031-05-31", "2031-07-31", "account", 3, controller.signal);
    const url = new URL(calls[0].url, "http://localhost");
    expect(url.searchParams.get("scope")).toBe("account");
    expect(url.searchParams.get("account_id")).toBe("3");
    expect(calls[0].signal).toBe(controller.signal);
  });
});
