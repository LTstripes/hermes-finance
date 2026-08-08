import { apiRequest } from "./client";
import type { Account } from "./types";

export function listAccounts(signal?: AbortSignal): Promise<Account[]> {
  return apiRequest<Account[]>("/api/accounts", { method: "GET", signal });
}

export function createAccount(
  payload: {
    name: string;
    account_type: string;
    status?: string;
    include_in_capital?: boolean;
    include_in_returns?: boolean;
  },
  signal?: AbortSignal,
): Promise<Account> {
  return apiRequest<Account>("/api/accounts", {
    method: "POST",
    body: payload,
    signal,
  });
}
