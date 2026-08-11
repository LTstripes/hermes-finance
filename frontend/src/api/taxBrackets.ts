import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type TaxBracketRule = {
  threshold_from: MoneyValue;
  threshold_to: MoneyValue | null;
  rate_bps: number;
};

export type TaxBracketYearConfig = {
  year: number;
  effective_from: string;
  effective_to: string;
  source: "official_default" | "manual_configuration";
  contract_version: string;
  mutable: boolean;
  closed_months: string[];
  brackets: TaxBracketRule[];
};

export type TaxBracketYearUpdate = {
  brackets: TaxBracketRule[];
};

export function getTaxBrackets(
  year: number,
  signal?: AbortSignal,
): Promise<TaxBracketYearConfig> {
  return apiRequest<TaxBracketYearConfig>(`/api/tax-brackets/${year}`, {
    method: "GET",
    signal,
  });
}

export function updateTaxBrackets(
  year: number,
  payload: TaxBracketYearUpdate,
  signal?: AbortSignal,
): Promise<TaxBracketYearConfig> {
  return apiRequest<TaxBracketYearConfig>(`/api/tax-brackets/${year}`, {
    method: "PUT",
    body: payload,
    signal,
  });
}
