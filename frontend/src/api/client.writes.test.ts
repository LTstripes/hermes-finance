import { afterEach, describe, expect, it, vi } from "vitest";
import { apiMultipart, apiRequest, subscribeApiWrites } from "./client";

afterEach(() => vi.unstubAllGlobals());
describe("saved-data write notifications", () => {
  it.each([
    "/api/incomes",
    "/api/months/1/close",
    "/api/months/1/reopen",
    "/api/broker-months/intakes/1/decisions",
    "/api/instruments/1",
  ])("retires reads after %s", async (path) => {
    const listener = vi.fn();
    const stop = subscribeApiWrites(listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await apiRequest(path, { method: "POST" });
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
  });
  it("retires reads after multipart Apply and a lost write ACK, without replay", async () => {
    const listener = vi.fn();
    const stop = subscribeApiWrites(listener);
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}"))
      .mockRejectedValueOnce(new TypeError("lost ACK"));
    vi.stubGlobal("fetch", fetch);
    await apiMultipart("/api/statement-import/apply", new FormData());
    await expect(apiRequest("/api/positions/1", { method: "PATCH" })).rejects.toThrow("lost ACK");
    expect(listener).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenCalledTimes(2);
    stop();
  });
  it("keeps current reads after rejected validation but invalidates an uncertain server failure", async () => {
    const listener = vi.fn();
    const stop = subscribeApiWrites(listener);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("{}", { status: 422 }))
        .mockResolvedValueOnce(new Response("{}", { status: 500 })),
    );
    await expect(apiRequest("/api/positions/1", { method: "PATCH" })).rejects.toThrow();
    expect(listener).not.toHaveBeenCalled();
    await expect(apiRequest("/api/positions/1", { method: "PATCH" })).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
  });
  it.each([
    "/api/quote-preview",
    "/api/broker-months/preview",
    "/api/broker-months/money-prepare",
    "/api/broker-months/public-identity-lookup",
    "/api/broker-months/intakes/1/review-preview",
    "/api/statement-import/prepare",
    "/api/months/1/scenario-lab",
    "/api/broker-statement-what-if/context",
    "/api/months/1/ai-analysis-bundle",
  ])("keeps evidence during read-only POST %s", async (path) => {
    const listener = vi.fn();
    const stop = subscribeApiWrites(listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    await apiRequest(path, { method: "POST" });
    expect(listener).not.toHaveBeenCalled();
    stop();
  });
});
