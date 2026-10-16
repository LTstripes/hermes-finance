import { beforeEach, expect, it, vi } from "vitest";
import { apiMultipart } from "./client";
import { originalContext, previewOriginalContext } from "./mybrokerPreflight";
vi.mock("./client", () => ({ apiMultipart: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
const dto = () => ({
  contract: "mybroker-batch-preflight-v1",
  kind: "preflight",
  documents: [
    {
      filename: "synthetic.xml",
      upload_count: 1,
      binder_blockers: [] as string[],
      document: {
        filename_account: "FILE",
        source_accounts: ["FILE", "ROW"],
        covered_from: "2030-01-01",
        covered_to: "2030-01-31",
      },
      mappings: {
        state: "blocked",
        conflicts: [] as string[],
        accounts: ["FILE", "ROW"].map((identity, index) => ({
          identity,
          mapping_id: index + 1,
          hermes_id: 7,
          action: "reuse",
          state: "ready",
        })),
      },
      statuses: { potential_incomplete_draft: "blocked", close_performance: "blocked" },
    },
  ],
});
it("sends one unchanged original with its filename and abort signal; ignores aggregate readiness", async () => {
  vi.mocked(apiMultipart).mockResolvedValue(dto());
  const file = new File(["<synthetic/>"], "synthetic.xml");
  const signal = new AbortController().signal;
  expect(await previewOriginalContext(file, signal)).toEqual({
    coveredFrom: "2030-01-01",
    coveredTo: "2030-01-31",
    accountId: 7,
  });
  const [url, form, received] = vi.mocked(apiMultipart).mock.calls[0];
  expect(url).toBe("/api/mybroker-preflight/preview");
  expect(Array.from(form.keys())).toEqual(["files"]);
  expect(await (form.get("files") as File).text()).toBe(await file.text());
  expect((form.get("files") as File).name).toBe(file.name);
  expect(received).toBe(signal);
});
it.each([
  "account_mapping_conflict",
  "revoked_account_binding_conflict",
  "source_account_conflict",
  "duplicate_account_alias",
])("does not resolve %s", (code) => {
  const value = dto();
  value.documents[0].mappings.conflicts.push(code);
  expect(originalContext(value, "synthetic.xml").accountId).toBeNull();
});
it.each(["missing", "ambiguous", "stage_create", "other-account", "no-mapping", "binder"])(
  "does not resolve %s",
  (kind) => {
    const value = dto(),
      entry = value.documents[0],
      row = entry.mappings.accounts[1];
    if (kind === "stage_create") row.action = kind;
    else if (kind === "other-account") row.hermes_id = 8;
    else if (kind === "no-mapping") row.mapping_id = 0;
    else if (kind === "binder") entry.binder_blockers.push("immutable_source_binder_mismatch");
    else row.state = kind;
    expect(originalContext(value, "synthetic.xml").accountId).toBeNull();
  },
);
it.each([
  null,
  {},
  { ...dto(), documents: [] },
  { ...dto(), documents: [dto().documents[0], dto().documents[0]] },
])("rejects malformed envelope %j", (value) => {
  expect(() => originalContext(value, "synthetic.xml")).toThrow(/не подтверждён/);
});
it.each([
  "missing-alias",
  "duplicate-alias",
  "empty-alias",
  "wrong-filename",
  "missing-diagnostics",
  "invalid-date",
])("rejects malformed boundary %s", (kind) => {
  const value = dto(),
    entry = value.documents[0];
  if (kind === "missing-alias") entry.mappings.accounts.pop();
  if (kind === "duplicate-alias") entry.mappings.accounts[1].identity = "FILE";
  if (kind === "empty-alias") entry.document.source_accounts[1] = "";
  if (kind === "wrong-filename") entry.filename = "other.xml";
  if (kind === "missing-diagnostics") Object.assign(entry.mappings, { conflicts: null });
  if (kind === "invalid-date") entry.document.covered_to = "2030-02-31";
  expect(() => originalContext(value, "synthetic.xml")).toThrow(/не подтверждён/);
});
