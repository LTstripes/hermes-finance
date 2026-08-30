import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmBrokerIdentityMapping,
  listEffectiveBrokerIdentityMappings,
  remapBrokerIdentityMapping,
} from "./brokerIdentityMappings";

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
  };
}

const mapping = {
  mapping_id: 7,
  provider: "alfa_pro",
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

  it("lists only effective mappings from the registry response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonOk([mapping, { ...mapping, mapping_id: 8, status: "superseded" }]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listEffectiveBrokerIdentityMappings("alfa_pro")).resolves.toEqual([mapping]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/broker-identity-mappings?provider=alfa_pro",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("posts an explicit account confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk(mapping));
    vi.stubGlobal("fetch", fetchMock);

    await confirmBrokerIdentityMapping({
      provider: "alfa_pro",
      subject_kind: "account",
      provider_identity: "SYN-ACCOUNT-NEW",
      hermes_target_id: 4,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/broker-identity-mappings",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          provider: "alfa_pro",
          subject_kind: "account",
          provider_identity: "SYN-ACCOUNT-NEW",
          hermes_target_id: 4,
        }),
      }),
    );
  });

  it("posts remap to the history-preserving registry endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk({ ...mapping, mapping_id: 9 }));
    vi.stubGlobal("fetch", fetchMock);

    await remapBrokerIdentityMapping(7, { hermes_target_id: 4 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/broker-identity-mappings/7/remap",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ hermes_target_id: 4 }),
      }),
    );
  });
});
