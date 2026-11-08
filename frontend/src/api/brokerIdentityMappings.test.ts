import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmBrokerIdentityMapping, listBrokerIdentityMappings } from "./brokerIdentityMappings";

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
  };
}

const mapping = {
  mapping_id: 7,
  provider: "synthetic_broker",
  subject_kind: "account",
  provider_identity: "SYN-ACCOUNT-001",
  hermes_target_id: 3,
  status: "effective",
  observed_isin: null,
  confirmed_at: "2026-08-31T12:00:00Z",
  source_as_of: null,
  captured_at: null,
  predecessor_mapping_id: null,
  successor_mapping_id: null,
  revoked_at: null,
  revoke_reason: null,
};

describe("broker identity mapping API helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the complete registry including historical mappings", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonOk([mapping, { ...mapping, mapping_id: 8, status: "superseded" }]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listBrokerIdentityMappings("synthetic_broker")).resolves.toEqual([
      mapping,
      { ...mapping, mapping_id: 8, status: "superseded" },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/broker-identity-mappings?provider=synthetic_broker",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("posts an explicit account confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk(mapping));
    vi.stubGlobal("fetch", fetchMock);

    await confirmBrokerIdentityMapping({
      provider: "synthetic_broker",
      subject_kind: "account",
      provider_identity: "SYN-ACCOUNT-NEW",
      hermes_target_id: 4,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/broker-identity-mappings",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          provider: "synthetic_broker",
          subject_kind: "account",
          provider_identity: "SYN-ACCOUNT-NEW",
          hermes_target_id: 4,
        }),
      }),
    );
  });
});
