import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type ExternalFlow = {
  id: number;
  reporting_month_id: number;
  account_id: number;
  event_date: string;
  boundary_amount: MoneyValue;
  direction: string;
  kind: string;
  scope_membership: string;
  transfer_link_id: number | null;
  transfer_status: string | null;
  portfolio_scope_classification: string;
  account_scope_classification: string;
  source: string;
  notes: string | null;
};

export type BoundaryCoverage = {
  id: number;
  account_id: number;
  covered_from: string;
  covered_to: string;
  coverage_state: string;
};

export type Preparation = {
  account_id: number;
  start_date: string;
  end_date: string;
  evidence_token: string;
  flows: ExternalFlow[];
  transfer_links: { id: number; status: string; flow_ids: number[] }[];
  cash_coverages: BoundaryCoverage[];
  in_kind_coverages: BoundaryCoverage[];
  movements: {
    id: number;
    event_date: string;
    movement_kind: string;
    source_account_id: number | null;
    destination_account_id: number | null;
    quantity: string | null;
  }[];
  cash_balances: {
    id: number;
    reporting_month_id: number;
    account_id: number | null;
    name: string;
    amount: MoneyValue;
  }[];
  months: { id: number; period_start: string; period_end: string; status: string }[];
};

export function getPreparation(
  accountId: number,
  start: string,
  end: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({
    account_id: String(accountId),
    start_date: start,
    end_date: end,
  });
  return apiRequest<Preparation>(`/api/performance/preparation?${params}`, { signal });
}

// No automatic write retries, including network failures with an ambiguous outcome.
export function savePreparation(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
  token: string,
) {
  return apiRequest<unknown>(path, { method, body, headers: { "X-Performance-Evidence": token } });
}
