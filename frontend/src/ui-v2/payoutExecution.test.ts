import { expect, it, vi } from "vitest";
import type { PayoutApplyResult, PayoutPreviewRow } from "../api/payouts";
import { executePayoutSelection, type FrozenPayoutGroup, receiptMatches } from "./payoutExecution";

function group(id: number): FrozenPayoutGroup {
  return {
    payload: { account_id: 1, instrument_id: id, position_snapshot_id: id, forecast_version: "v1" },
    quantity: "10",
    label: `Synthetic ${id}`,
    rows: [
      {
        provider: "t_invest",
        instrument_uid: `UID-${id}`,
        event_kind: "coupon",
        identity_key: `K-${id}`,
        fingerprint: `FP-${id}`,
      },
    ],
    reviewedRows: [
      {
        provider: "t_invest",
        instrument_uid: `UID-${id}`,
        event_kind: "coupon",
        identity_key: `K-${id}`,
        total_amount: { amount: "10.00", currency: "RUB" },
      } as PayoutPreviewRow,
    ],
  };
}
function success(value: FrozenPayoutGroup): PayoutApplyResult {
  return {
    success: true,
    selected_count: 1,
    error_code: null,
    message: null,
    items: [
      {
        ...value.rows[0],
        payout_id: value.payload.instrument_id,
        revision_id: 1,
        revision_kind: "APPLY",
        lifecycle: "active",
        total_amount: { amount: "10.00", currency: "RUB" },
        expected_cash_flow_id: null,
        counting_decision: null,
        reconciliation_id: null,
      },
    ],
  };
}
function hooks() {
  return {
    current: () => true,
    before: vi.fn(async () => true),
    apply: vi.fn(async (value: FrozenPayoutGroup) => success(value)),
    verify: vi.fn(async () => true),
    progress: vi.fn(),
    stop: () => false,
  };
}
it("matches a reviewed existing reconciliation on REVISED without a new duplicate decision", () => {
  const value = group(1);
  value.reviewedRows[0].reconciliation = {
    reconciliation_id: 7,
    counting_decision: "count_manual",
    expected_cash_flow_id: 9,
  } as PayoutPreviewRow["reconciliation"];
  const receipt = success(value);
  Object.assign(receipt.items[0], {
    revision_kind: "REVISE",
    reconciliation_id: 7,
    counting_decision: "count_manual",
    expected_cash_flow_id: 9,
  });
  expect(receiptMatches(receipt, value.rows, value.reviewedRows)).toBe(true);
  receipt.items[0].reconciliation_id = 8;
  expect(receiptMatches(receipt, value.rows, value.reviewedRows)).toBe(false);
});
it("confirms a frozen selection sequentially after exact receipt and authoritative readback", async () => {
  const input = [group(1), group(2)];
  const h = hooks();
  let resolve!: (value: boolean) => void;
  h.verify.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const pending = executePayoutSelection(input, h);
  await vi.waitFor(() => expect(h.verify).toHaveBeenCalledTimes(1));
  input[1].rows[0].identity_key = "changed-after-confirm";
  expect(h.apply).toHaveBeenCalledTimes(1);
  // Individual/bulk/remount use the same lock for the entire readback lifetime.
  expect(await executePayoutSelection([group(3)], hooks())).toBeNull();
  resolve(true);
  expect((await pending)?.map((row) => row.outcome)).toEqual(["CONFIRMED", "CONFIRMED"]);
  expect(h.apply.mock.calls[1][0].rows[0].identity_key).toBe("K-2");
});
it.each(["preview_changed", "closed_month", "provider_error", "persistence_error"] as const)(
  "stops on %s and keeps prior successes",
  async (code) => {
    const h = hooks();
    h.apply
      .mockImplementationOnce(async (value) => success(value))
      .mockResolvedValueOnce({
        success: false,
        selected_count: 1,
        items: [],
        error_code: code,
        message: code,
      });
    expect(
      (await executePayoutSelection([group(1), group(2), group(3)], h))?.map((row) => row.outcome),
    ).toEqual([
      "CONFIRMED",
      code === "closed_month" || code === "preview_changed"
        ? "STALE_NO_WRITE"
        : "REJECTED_NO_WRITE",
      "NOT_SENT",
    ]);
    expect(h.apply).toHaveBeenCalledTimes(2);
  },
);
it("continues only a proven local validation with unchanged context", async () => {
  const h = hooks();
  h.apply.mockResolvedValueOnce({
    success: false,
    selected_count: 1,
    items: [],
    error_code: "validation_error",
    message: "manual duplicate decision is required",
  });
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["REJECTED_NO_WRITE", "CONFIRMED"]);
});
it("stops when context changes after local validation", async () => {
  const h = hooks();
  let current = true;
  h.current = () => current;
  h.apply.mockImplementationOnce(async () => {
    current = false;
    return {
      success: false,
      selected_count: 1,
      items: [],
      error_code: "validation_error",
      message: "manual duplicate decision is required",
    };
  });
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["REJECTED_NO_WRITE", "NOT_SENT"]);
});
it("treats a generic validation/non-applyable status as stale", async () => {
  const h = hooks();
  h.apply.mockResolvedValueOnce({
    success: false,
    selected_count: 1,
    items: [],
    error_code: "validation_error",
    message: "preview status unchanged is not applyable",
  });
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["STALE_NO_WRITE", "NOT_SENT"]);
});
it("lost response is UNKNOWN, never retried and stops later submissions", async () => {
  const h = hooks();
  h.apply.mockRejectedValueOnce(new Error("connection lost after commit"));
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["UNKNOWN", "NOT_SENT"]);
  expect(h.apply).toHaveBeenCalledTimes(1);
  expect(h.verify).not.toHaveBeenCalled();
});
it.each(["failure", "mismatch"])(
  "retains a successful receipt as APPLIED_UNVERIFIED on readback %s",
  async (kind) => {
    const h = hooks();
    if (kind === "failure") h.verify.mockRejectedValueOnce(new Error("read failed"));
    else h.verify.mockResolvedValueOnce(false);
    expect(
      (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
    ).toEqual(["APPLIED_UNVERIFIED", "NOT_SENT"]);
  },
);
it("rejects a same-count foreign receipt and duplicate identities", async () => {
  const h = hooks();
  h.apply.mockResolvedValueOnce(success(group(999)));
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["APPLIED_UNVERIFIED", "NOT_SENT"]);
  expect(h.verify).not.toHaveBeenCalled();
  const result = success(group(1));
  result.selected_count = 2;
  result.items.push(result.items[0]);
  expect(
    receiptMatches(
      result,
      [...group(1).rows, ...group(2).rows],
      [...group(1).reviewedRows, ...group(2).reviewedRows],
    ),
  ).toBe(false);
});
it("rejects an exact identity with an unreviewed amount or manual link", () => {
  const value = group(1);
  const result = success(value);
  result.items[0].total_amount.amount = "999.00";
  expect(receiptMatches(result, value.rows, value.reviewedRows)).toBe(false);
  const linked = success(value);
  value.rows[0].manual_duplicate_decision = {
    expected_cash_flow_id: 42,
    counting_decision: "count_manual",
  };
  expect(receiptMatches(linked, value.rows, value.reviewedRows)).toBe(false);
  linked.items[0] = {
    ...linked.items[0],
    expected_cash_flow_id: 42,
    counting_decision: "count_manual",
    reconciliation_id: 7,
  };
  expect(receiptMatches(linked, value.rows, value.reviewedRows)).toBe(true);
});
it("stops before POST on stale identity/CLOSED or unavailable local reads", async () => {
  const h = hooks();
  h.before.mockResolvedValueOnce(false);
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["STALE_NO_WRITE", "NOT_SENT"]);
  expect(h.apply).not.toHaveBeenCalled();
});
it("deliberate stop waits for current group and preserves its confirmed outcome", async () => {
  const h = hooks();
  let stop = false;
  h.stop = () => stop;
  h.verify.mockImplementationOnce(async () => {
    stop = true;
    return true;
  });
  expect(
    (await executePayoutSelection([group(1), group(2)], h))?.map((row) => row.outcome),
  ).toEqual(["CONFIRMED", "NOT_SENT"]);
});
