import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteInstrumentMapping,
  deleteInstrumentMappingExclusion,
  discoverInstrumentMapping,
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
    provider_instrument_id: "SBER",
    provider_venue_id: "stock/shares/TQBR",
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
      provider_instrument_id: "SBER",
      provider_venue_id: "stock/shares/TQBR",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          provider: "moex_iss",
          provider_instrument_id: "SBER",
          provider_venue_id: "stock/shares/TQBR",
        }),
      }),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain("verify=");
  });

  it("puts a T-Invest identity with verify=true and candidate ISIN", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonOk({
        ...mapping,
        identity: {
          provider: "t_invest",
          provider_instrument_id: "11111111-1111-1111-1111-111111111111",
          provider_venue_id: null,
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await putInstrumentMapping(10, {
      provider: "t_invest",
      provider_instrument_id: "11111111-1111-1111-1111-111111111111",
      provider_venue_id: null,
      isin: "RU0009029540",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping?verify=true",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          provider: "t_invest",
          provider_instrument_id: "11111111-1111-1111-1111-111111111111",
          provider_venue_id: null,
          isin: "RU0009029540",
        }),
      }),
    );
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

  it("posts an explicit T-Invest discovery request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonOk({
        status: "ok",
        message: null,
        candidates: [
          {
            provider: "t_invest",
            provider_instrument_id: "11111111-1111-1111-1111-111111111111",
            provider_venue_id: null,
            instrument_kind: "stock",
            isin: "RU0009029540",
          },
        ],
        rejected: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await discoverInstrumentMapping(10, { provider: "t_invest" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/10/market-mapping/discover",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ provider: "t_invest" }),
      }),
    );
  });
});
