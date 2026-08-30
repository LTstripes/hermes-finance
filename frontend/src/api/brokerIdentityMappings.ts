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

export type BrokerIdentityMappingConfirmPayload = {
  provider: string;
  subject_kind: "account" | "instrument";
  provider_identity: string;
  hermes_target_id: number;
  observed_isin?: string | null;
  source_as_of?: string | null;
  captured_at?: string | null;
};

export type BrokerIdentityMappingRemapPayload = {
  hermes_target_id: number;
  observed_isin?: string | null;
  source_as_of?: string | null;
  captured_at?: string | null;
};

export function listBrokerIdentityMappings(provider: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ provider });
  return apiRequest<BrokerIdentityMapping[]>(`/api/broker-identity-mappings?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

export async function listEffectiveBrokerIdentityMappings(
  provider: string,
  signal?: AbortSignal,
): Promise<BrokerIdentityMapping[]> {
  const rows = await listBrokerIdentityMappings(provider, signal);
  return rows.filter((row) => row.status === "effective");
}

export function confirmBrokerIdentityMapping(
  payload: BrokerIdentityMappingConfirmPayload,
  signal?: AbortSignal,
) {
  return apiRequest<BrokerIdentityMapping>("/api/broker-identity-mappings", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function remapBrokerIdentityMapping(
  mappingId: number,
  payload: BrokerIdentityMappingRemapPayload,
  signal?: AbortSignal,
) {
  return apiRequest<BrokerIdentityMapping>(`/api/broker-identity-mappings/${mappingId}/remap`, {
    method: "POST",
    body: payload,
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
