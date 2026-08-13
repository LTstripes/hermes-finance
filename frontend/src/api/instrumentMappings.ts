import { apiRequest } from "./client";
import type { InstrumentMarketMapping, MarketIdentityWrite } from "./types";

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
