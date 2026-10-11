import { beforeEach, expect, it, vi } from "vitest";
import { apiMultipart } from "./client";
import { applyBrokerMonth, previewBrokerMonth } from "./brokerMonths";

vi.mock("./client", () => ({ apiMultipart: vi.fn(), apiRequest: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("sends original plus reviewed alias decisions bound to the shared Preview digest", async () => {
  const file = new File(["<synthetic/>"], "source.xml");
  const intent = { reporting_month_id: 1, account_id: 7 };
  const decisions = ["FILE", "ROW-A", "ROW-B"].map((identity) => ({ identity, hermes_id: 7 }));
  await previewBrokerMonth(file, intent);
  const preview = vi.mocked(apiMultipart).mock.calls[0][1];
  expect(preview.get("file")).toBe(file);
  expect(JSON.parse(String(preview.get("intent")))).toEqual(intent);
  await applyBrokerMonth(file, intent, "b".repeat(64), "synthetic-request", decisions);
  const apply = vi.mocked(apiMultipart).mock.calls[1][1];
  expect(apply.get("file")).toBe(file);
  expect(JSON.parse(String(apply.get("confirmation")))).toEqual({
    ...intent,
    confirmation_digest: "b".repeat(64),
    request_id: "synthetic-request",
    reviewed_account_bindings: decisions,
  });
});
