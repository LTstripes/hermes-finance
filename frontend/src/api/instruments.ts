import { apiRequest } from "./client";
import type { Instrument, InstrumentCreate } from "./types";

export function listInstruments(
  params: { active?: boolean; instrument_type?: string } = {},
  signal?: AbortSignal,
): Promise<Instrument[]> {
  const query = new URLSearchParams();
  if (params.active !== undefined) {
    query.set("active", String(params.active));
  }
  if (params.instrument_type) {
    query.set("instrument_type", params.instrument_type);
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return apiRequest<Instrument[]>(`/api/instruments${suffix}`, { method: "GET", signal });
}

export function createInstrument(
  payload: InstrumentCreate,
  signal?: AbortSignal,
): Promise<Instrument> {
  return apiRequest<Instrument>("/api/instruments", {
    method: "POST",
    body: payload,
    signal,
  });
}
