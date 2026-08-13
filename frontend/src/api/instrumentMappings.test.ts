import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteInstrumentMapping,
  deleteInstrumentMappingExclusion,
  getInstrumentMapping,
  putInstrumentMapping,
  putInstrumentMappingExclusion,
} from "./instrumentMappings";

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
  };
}

const mapping = {
  instrument_id: 10,
  state: "mapped",
  identity: {
    provider: "moex_iss",
    engine: "stock",
    market: "shares",
    boardid: "TQBR",
    secid: "SBER",
  },
  instrument_isin: "RU0009029540",
  legacy_moex_secid: "SBER",
};

describe("instrument mapping API helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("gets the mapping for one instrument", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonOk({ ...mapping, state: "unmapped", identity: null }));
    vi.stubGlobal("fetch", fetchMock);
    await getInstrumentMapping(10);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("puts an explicit identity without verify=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk(mapping));
    vi.stubGlobal("fetch", fetchMock);
    await putInstrumentMapping(10, {
      provider: "moex_iss",
      engine: "stock",
      market: "shares",
      boardid: "TQBR",
      secid: "SBER",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          provider: "moex_iss",
          engine: "stock",
          market: "shares",
          boardid: "TQBR",
          secid: "SBER",
        }),
      }),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain("verify=");
  });

  it("clears mapping and exclusion through the existing endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonOk({ ...mapping, state: "unmapped", identity: null }));
    vi.stubGlobal("fetch", fetchMock);
    await deleteInstrumentMapping(10);
    await putInstrumentMappingExclusion(10);
    await deleteInstrumentMappingExclusion(10);
    expect(fetchMock.mock.calls.map(([url, init]) => `${init?.method} ${url}`)).toEqual([
      "DELETE /api/instruments/10/market-mapping",
      "PUT /api/instruments/10/market-mapping/exclusion",
      "DELETE /api/instruments/10/market-mapping/exclusion",
    ]);
  });
});
