import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiRequest, formatApiError } from "./client";
import { createMonth, deleteMonth, listMonths } from "./months";

describe("apiRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  it("returns JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ status: "ok", version: "0.1.0" }),
      }),
    );

    const data = await apiRequest<{ status: string; version: string }>("/api/health");
    expect(data).toEqual({ status: "ok", version: "0.1.0" });
  });

  it("parses D08 error body into ApiClientError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () =>
          JSON.stringify({
            error: {
              code: "conflict",
              message: "reporting month already exists",
              details: [],
            },
          }),
      }),
    );

    await expect(apiRequest("/api/months")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 409,
      code: "conflict",
      message: "reporting month already exists",
    });
  });

  it("returns undefined on 204", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        text: async () => "",
      }),
    );

    await expect(apiRequest<void>("/api/months/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiRequest("/api/months")).rejects.toMatchObject({
      code: "network_error",
      status: 0,
    });
  });
});

describe("months API helpers", () => {
  it("listMonths GETs /api/months", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify([
          {
            id: 1,
            year: 2026,
            month: 7,
            status: "draft",
            snapshot_date: "2026-07-31",
            source: "manual",
          },
        ]),
    });
    vi.stubGlobal("fetch", fetchMock);

    const months = await listMonths();
    expect(months).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("createMonth POSTs JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      text: async () =>
        JSON.stringify({
          id: 2,
          year: 2026,
          month: 8,
          status: "draft",
          snapshot_date: "2026-08-31",
          source: "manual",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createMonth({ year: 2026, month: 8, snapshot_date: "2026-08-31" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ year: 2026, month: 8, snapshot_date: "2026-08-31" }),
      }),
    );
  });

  it("deleteMonth issues DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchMock);

    await deleteMonth(9);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/9",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("formatApiError", () => {
  it("includes field details when present", () => {
    const err = new ApiClientError(422, {
      code: "unprocessable",
      message: "Request validation failed",
      details: [{ field: "month", message: "Input should be less than or equal to 12" }],
    });
    expect(formatApiError(err)).toContain("month:");
  });
});
