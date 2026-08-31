import { apiRequest } from "./client";
import type { Instrument, InstrumentCleanup, MoneyValue } from "./types";

export type InstrumentCreatePayload = {
  name: string;
  instrument_type: string;
  isin?: string | null;
  ticker?: string | null;
  moex_secid?: string | null;
  currency?: string;
  nominal_value?: MoneyValue | null;
  is_active?: boolean;
  manual_price_allowed?: boolean;
  notes?: string | null;
};

export type InstrumentUpdatePayload = {
  name?: string;
  instrument_type?: string;
  isin?: string | null;
  ticker?: string | null;
  moex_secid?: string | null;
  currency?: string;
  nominal_value?: MoneyValue | null;
  is_active?: boolean;
  manual_price_allowed?: boolean;
  notes?: string | null;
};

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
  payload: InstrumentCreatePayload,
  signal?: AbortSignal,
): Promise<Instrument> {
  return apiRequest<Instrument>("/api/instruments", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateInstrument(
  instrumentId: number,
  payload: InstrumentUpdatePayload,
  signal?: AbortSignal,
): Promise<Instrument> {
  return apiRequest<Instrument>(`/api/instruments/${instrumentId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteInstrument(instrumentId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/instruments/${instrumentId}`, {
    method: "DELETE",
    signal,
  });
}

export function getInstrumentCleanup(
  instrumentId: number,
  signal?: AbortSignal,
): Promise<InstrumentCleanup> {
  return apiRequest<InstrumentCleanup>(`/api/instruments/${instrumentId}/cleanup`, {
    method: "GET",
    signal,
  });
}
