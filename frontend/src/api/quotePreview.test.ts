import { afterEach, describe, expect, it, vi } from "vitest";

import { applyMonthQuotes, previewMonthQuotes } from "./quotePreview";

describe("quote preview API helper", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to the month quote-preview endpoint without a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          reporting_month_id: 7,
          month_status: "draft",
          target_date: "2026-08-13",
          month_editable: true,
          batch_error: null,
          rows: [],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewMonthQuotes(7);
    expect(preview.rows).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/7/quote-preview",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  });

  it("posts selected preview fingerprints to quote-apply", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          reporting_month_id: 7,
          applied_count: 1,
          rows: [],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await applyMonthQuotes(7, [
      {
        position_snapshot_id: 4,
        accept_stale: false,
        expected_market_price_per_unit: { amount: "215.50", currency: "RUB" },
        expected_price_date: "2026-08-12",
        expected_identity: {
          provider: "t_invest",
          provider_instrument_id: "11111111-1111-1111-1111-111111111111",
          provider_venue_id: null,
        },
        expected_quote_kind: "last",
      },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/7/quote-apply",
      expect.objectContaining({ method: "POST" }),
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      rows: [
        {
          position_snapshot_id: 4,
          accept_stale: false,
          expected_market_price_per_unit: { amount: "215.50", currency: "RUB" },
          expected_price_date: "2026-08-12",
          expected_identity: {
            provider: "t_invest",
            provider_instrument_id: "11111111-1111-1111-1111-111111111111",
            provider_venue_id: null,
          },
          expected_quote_kind: "last",
        },
      ],
    });
  });
});
