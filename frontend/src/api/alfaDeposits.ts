import { apiRequest } from "./client";
import type { DepositSnapshot } from "./types";

export type AlfaDepositRequest = {
  month_id: number;
  csv: string;
  full_month: boolean;
  bindings: Record<string, number>;
};

type Values = {
  balance: string | null;
  actual_interest_received: string | null;
  annual_rate: string | null;
};

export type AlfaDepositRow = {
  source_key: string;
  label: string;
  first_line: number;
  count: number;
  first_date: string | null;
  last_date: string | null;
  account_id: number | null;
  mapped: boolean;
  snapshot_id: number | null;
  current: Values;
  proposed: Values;
  difference: string | null;
  messages: string[];
  token: string | null;
};

export type AlfaDepositPreview = {
  month_id: number;
  period_start: string;
  period_end: string;
  accounts: { id: number; name: string }[];
  rows: AlfaDepositRow[];
};

export function previewAlfaDeposits(body: AlfaDepositRequest, signal: AbortSignal) {
  return apiRequest<AlfaDepositPreview>("/api/deposits/alfa/preview", {
    method: "POST",
    body,
    signal,
  });
}

export function applyAlfaDeposit(body: AlfaDepositRequest, sourceKey: string, token: string) {
  return apiRequest<DepositSnapshot>("/api/deposits/alfa/apply", {
    method: "POST",
    body: { ...body, source_key: sourceKey, token },
  });
}
