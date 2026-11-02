import { createHash, webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { brokerFileIdentity, readBrokerSources, uploadBrokerSources } from "./brokerSources";
import { apiMultipart, apiRequest } from "./client";

vi.mock("./client", () => ({ apiMultipart: vi.fn(), apiRequest: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());

it("keeps all files in one multipart month request and exposes read-only recovery", async () => {
  const files = [new File(["xml"], "one.xml"), new File(["pdf"], "two.pdf")];
  await uploadBrokerSources(12, files, "synthetic-request");
  const [path, form] = vi.mocked(apiMultipart).mock.calls.at(-1) ?? [];
  expect(path).toBe("/api/months/12/broker-sources");
  expect((form as FormData).getAll("files")).toEqual(files);
  expect((form as FormData).get("request_id")).toBe("synthetic-request");
  await readBrokerSources(12);
  expect(apiRequest).toHaveBeenCalledWith("/api/months/12/broker-sources", {
    signal: undefined,
  });
});

it("matches the server's ASCII canonical filename digest for Cyrillic names", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const identity = await brokerFileIdentity(new File(["synthetic XML"], "отчёт.pdf"));
  expect(identity.document_sha256).toBe(createHash("sha256").update("synthetic XML").digest("hex"));
  expect(identity.filename_digest).toBe(
    createHash("sha256").update('"\\u043e\\u0442\\u0447\\u0451\\u0442.pdf"').digest("hex"),
  );
});
