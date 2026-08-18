import { afterEach, describe, expect, it, vi } from "vitest";

import { discoverInstrumentMapping } from "./instrumentMappings";

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
  };
}

describe("instrument mapping manual discovery query", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the explicit owner query unchanged to the existing discovery endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonOk({
        status: "unavailable",
        message: null,
        candidates: [],
        rejected: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await discoverInstrumentMapping(10, { provider: "t_invest", query: "SBER" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping/discover",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ provider: "t_invest", query: "SBER" }),
      }),
    );
  });
});
