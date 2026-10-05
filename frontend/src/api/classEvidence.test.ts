import { afterEach, expect, it, vi } from "vitest";
import { classReturnsFixture } from "../test/classReturnsFixture";
import { saveClassCoverage } from "./classEvidence";

afterEach(() => vi.unstubAllGlobals());
it("POSTs new claims and PUTs full replacement with exact If-Match revision", async () => {
  const row = classReturnsFixture("stock", "2030-01-31", "2030-02-28").coverage_provenance[0];
  const { id: _id, revision: _revision, ...body } = row;
  const fetch = vi
    .fn()
    .mockImplementation(async () => new Response(JSON.stringify(row), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await saveClassCoverage(body);
  await saveClassCoverage({ ...body, coverage_state: "revoked" }, row);
  expect(fetch.mock.calls[0][0]).toBe("/api/class-evidence/coverages");
  expect(fetch.mock.calls[0][1].method).toBe("POST");
  expect(fetch.mock.calls[1][0]).toBe(`/api/class-evidence/coverages/${row.id}`);
  expect(fetch.mock.calls[1][1]).toMatchObject({
    method: "PUT",
    headers: { "If-Match": String(row.revision) },
  });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ ...body, coverage_state: "revoked" });
});
