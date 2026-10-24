import { afterEach, expect, it, vi } from "vitest";
import { closeIntentionallyEmptyMonth, getIntentionalEmptyCloseReceipt } from "./months";
import type { IntentionalEmptyCloseCommand, IntentionalEmptyCloseReceipt } from "./types";

afterEach(() => vi.unstubAllGlobals());

it("preserves exact command identity and uses GET receipt to recover lost ACK", async () => {
  const command: IntentionalEmptyCloseCommand = {
    command: "close_intentionally_empty_manual_month",
    policy_version: "intentional_empty_manual_month_v1",
    month_id: 17,
    year: 2030,
    month: 1,
    snapshot_date: "2030-01-31",
    expected_identity: "a".repeat(64),
    request_id: "same-original-intent",
    reason: "No recorded financial facts for this period",
  };
  const receipt: IntentionalEmptyCloseReceipt = {
    ...command,
    closed_at: "2030-02-01T00:00:00Z",
    result_status: "closed",
  };
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("lost ACK"))
    .mockResolvedValueOnce({ ok: true, status: 200, text: async () => JSON.stringify(receipt) });
  vi.stubGlobal("fetch", fetcher);
  await expect(closeIntentionallyEmptyMonth(17, command)).rejects.toThrow("lost ACK");
  expect(await getIntentionalEmptyCloseReceipt(17, command.request_id)).toEqual(receipt);
  expect(fetcher.mock.calls[0][0]).toBe("/api/months/17/close-intentionally-empty");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(command);
  expect(fetcher.mock.calls[1][0]).toBe(
    "/api/months/17/intentional-empty-close-receipts/same-original-intent",
  );
  expect(fetcher.mock.calls[1][1].method).toBe("GET");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("preserves the typed empty guard from ordinary Close", async () => {
  const { closeMonth } = await import("./months");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({
          error: { code: "empty_manual_month", message: "No saved facts", details: [] },
        }),
    }),
  );
  await expect(closeMonth(17)).rejects.toMatchObject({ code: "empty_manual_month", status: 422 });
});
