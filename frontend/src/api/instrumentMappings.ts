import { apiRequest } from "./client";
import type { InstrumentMarketMapping, MarketDiscoverResult, MarketIdentityWrite } from "./types";

export function getInstrumentMapping(
  instrumentId: number,
  signal?: AbortSignal,
): Promise<InstrumentMarketMapping> {
  return apiRequest<InstrumentMarketMapping>(`/api/instruments/${instrumentId}/market-mapping`, {
    method: "GET",
    signal,
  });
}

export function putInstrumentMapping(
  instrumentId: number,
  payload: MarketIdentityWrite,
  signal?: AbortSignal,
): Promise<InstrumentMarketMapping> {
  return apiRequest<InstrumentMarketMapping>(`/api/instruments/${instrumentId}/market-mapping`, {
    method: "PUT",
    body: payload,
    signal,
  });
}

export function deleteInstrumentMapping(
  instrumentId: number,
  signal?: AbortSignal,
): Promise<InstrumentMarketMapping> {
  return apiRequest<InstrumentMarketMapping>(`/api/instruments/${instrumentId}/market-mapping`, {
    method: "DELETE",
    signal,
  });
}

export function putInstrumentMappingExclusion(
  instrumentId: number,
  signal?: AbortSignal,
): Promise<InstrumentMarketMapping> {
  return apiRequest<InstrumentMarketMapping>(
    `/api/instruments/${instrumentId}/market-mapping/exclusion`,
    { method: "PUT", signal },
  );
}

export function deleteInstrumentMappingExclusion(
  instrumentId: number,
  signal?: AbortSignal,
): Promise<InstrumentMarketMapping> {
  return apiRequest<InstrumentMarketMapping>(
    `/api/instruments/${instrumentId}/market-mapping/exclusion`,
    { method: "DELETE", signal },
  );
}

export function discoverInstrumentMapping(
  instrumentId: number,
  payload: { provider: string; query?: string | null },
  signal?: AbortSignal,
): Promise<MarketDiscoverResult> {
  return apiRequest<MarketDiscoverResult>(
    `/api/instruments/${instrumentId}/market-mapping/discover`,
    { method: "POST", body: payload, signal },
  );
}
