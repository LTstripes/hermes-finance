import { apiRequest } from "../../api/client";
import type { AccountLink, Metric } from "./model";

export type HomeSummary = {
  contract_version: "returns_home_summary_v1";
  result: { amount: Metric; partial: boolean };
  positive: number;
  negative: number;
  unknown: number;
  unchanged: number;
  mixed_periods: boolean;
  ranked: {
    isin: string;
    name: string;
    pnl: Metric;
    accounts: { scope: string; label: string; account_link?: AccountLink | null }[];
  }[];
};

export async function getHomeSummary(signal: AbortSignal) {
  const value = await apiRequest<HomeSummary>("/api/returns/home-summary", { signal });
  if (value.contract_version !== "returns_home_summary_v1")
    throw new Error("Return summary contract mismatch");
  return value;
}
