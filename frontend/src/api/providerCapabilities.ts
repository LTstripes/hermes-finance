import { apiRequest } from "./client";

export type ProviderCapabilityStatus = "supported" | "partial" | "unsupported" | (string & {});

export type ProviderCapabilityItem = {
  name: string;
  status: ProviderCapabilityStatus;
  limitations: string[];
};

export type ProviderCapabilities = {
  provider: string;
  supported_instrument_types: string[];
  capabilities: ProviderCapabilityItem[];
  limitations: string[];
};

/** Static capability profiles — backend does no provider I/O. */
export function listProviderCapabilities(signal?: AbortSignal): Promise<ProviderCapabilities[]> {
  return apiRequest<ProviderCapabilities[]>("/api/market-data/providers/capabilities", {
    method: "GET",
    signal,
  });
}
