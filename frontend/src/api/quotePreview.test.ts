import { afterEach, describe, expect, it, vi } from "vitest";

import { previewMonthQuotes } from "./quotePreview";

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
});
