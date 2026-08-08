import { apiRequest } from "./client";
import type { IisContribution, IisProfile, TaxBenefit } from "./types";

export function getIisProfile(accountId: number, signal?: AbortSignal): Promise<IisProfile> {
  return apiRequest<IisProfile>(`/api/iis/${accountId}/profile`, { method: "GET", signal });
}

export function upsertIisProfile(
  accountId: number,
  payload: {
    iis_type: string;
    opened_at: string;
    eligible_close_at?: string | null;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<IisProfile> {
  return apiRequest<IisProfile>(`/api/iis/${accountId}/profile`, {
    method: "PUT",
    body: payload,
    signal,
  });
}

export function listIisContributions(
  accountId: number,
  signal?: AbortSignal,
): Promise<IisContribution[]> {
  return apiRequest<IisContribution[]>(`/api/iis/${accountId}/contributions`, {
    method: "GET",
    signal,
  });
}

export function createIisContribution(
  accountId: number,
  payload: {
    tax_year: number;
    amount: { amount: string; currency: string };
    is_target_reached?: boolean;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<IisContribution> {
  return apiRequest<IisContribution>(`/api/iis/${accountId}/contributions`, {
    method: "POST",
    body: payload,
    signal,
  });
}

export function listTaxBenefits(accountId: number, signal?: AbortSignal): Promise<TaxBenefit[]> {
  return apiRequest<TaxBenefit[]>(`/api/iis/${accountId}/benefits`, { method: "GET", signal });
}

export function createTaxBenefit(
  accountId: number,
  payload: {
    tax_year: number;
    benefit_type: string;
    status: string;
    amount: { amount: string; currency: string };
    received_at?: string | null;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<TaxBenefit> {
  return apiRequest<TaxBenefit>(`/api/iis/${accountId}/benefits`, {
    method: "POST",
    body: payload,
    signal,
  });
}
