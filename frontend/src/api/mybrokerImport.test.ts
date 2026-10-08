import { beforeEach, expect, it, vi } from "vitest";
import { apiMultipart } from "./client";
import { applyMyBroker, previewMyBroker, type MyBrokerPreview } from "./mybrokerImport";

vi.mock("./client", () => ({ apiMultipart: vi.fn(), apiRequest: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("sends original full file and explicit decisions, never browser source rows", async () => {
  const file = new File(["<synthetic>entire unchanged XML</synthetic>"], "synthetic.xml");
  await previewMyBroker(file, ["RU000A000001"]);
  const form = vi.mocked(apiMultipart).mock.calls[0][1];
  expect(form.get("file")).toBe(file);
  expect(JSON.parse(String(form.get("decisions")))).toEqual({
    skipped_isins: ["RU000A000001"],
    owner_reviewed: true,
  });
  const preview: MyBrokerPreview = {
    confirmation_digest: "a".repeat(64),
    document: {
      provider: "alfa_mybroker",
      parser: "mybroker-s1-v2",
      document_sha256: "b".repeat(64),
      filename_account: "1234567",
      covered_from: "2030-01-01",
      covered_to: "2030-01-31",
      source_accounts: ["1234567"],
      section_inventory: {},
      trades: [],
      positions: [],
      money: [],
    },
    mappings: [],
    instrument_choices: [{ isin: "RU000A000001", choice: "skip" }],
    counts: { mapped: 0, skipped: 1, unsupported: 0 },
    missing_mappings: [],
    conflicts: [],
    blockers: [],
    coverage_state: "unknown",
    can_apply: true,
  };
  await applyMyBroker(file, preview);
  const confirmation = JSON.parse(
    String(vi.mocked(apiMultipart).mock.calls[1][1].get("confirmation")),
  );
  expect(confirmation.skipped_isins).toEqual(["RU000A000001"]);
  expect(confirmation.owner_reviewed).toBe(true);
  expect(confirmation.request_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(confirmation).not.toHaveProperty("document");
  expect(vi.mocked(apiMultipart).mock.calls[1][1].get("file")).toBe(file);
});
