import { apiRequest } from "./client";

export type BrokerIdentityMapping = {
  mapping_id: number;
  provider: string;
  subject_kind: "account" | "instrument" | string;
  provider_identity: string;
  hermes_target_id: number;
  status: "effective" | "revoked" | "superseded" | string;
  observed_isin: string | null;
  confirmed_at: string;
  source_as_of: string | null;
  captured_at: string | null;
  predecessor_mapping_id: number | null;
  successor_mapping_id: number | null;
  revoked_at: string | null;
  revoke_reason: string | null;
};

export function listBrokerIdentityMappings(provider: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ provider });
  return apiRequest<BrokerIdentityMapping[]>(`/api/broker-identity-mappings?${query.toString()}`, {
    signal,
  });
}

export function revokeBrokerIdentityMapping(
  mappingId: number,
  reason?: string | null,
  signal?: AbortSignal,
) {
  return apiRequest<BrokerIdentityMapping>(`/api/broker-identity-mappings/${mappingId}/revoke`, {
    method: "POST",
    body: { reason: reason ?? null },
    signal,
  });
}
