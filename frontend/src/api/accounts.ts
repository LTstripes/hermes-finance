import { apiRequest } from "./client";
import type { Account } from "./types";

export type AccountCreatePayload = {
  name: string;
  account_type: string;
  external_code?: string | null;
  status?: string;
  include_in_capital?: boolean;
  include_in_returns?: boolean;
  notes?: string | null;
};

export type AccountUpdatePayload = {
  name?: string;
  account_type?: string;
  external_code?: string | null;
  status?: string;
  include_in_capital?: boolean;
  include_in_returns?: boolean;
  notes?: string | null;
};

export function listAccounts(signal?: AbortSignal): Promise<Account[]> {
  return apiRequest<Account[]>("/api/accounts", { method: "GET", signal });
}

export function createAccount(
  payload: AccountCreatePayload,
  signal?: AbortSignal,
): Promise<Account> {
  return apiRequest<Account>("/api/accounts", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateAccount(
  accountId: number,
  payload: AccountUpdatePayload,
  signal?: AbortSignal,
): Promise<Account> {
  return apiRequest<Account>(`/api/accounts/${accountId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteAccount(accountId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/accounts/${accountId}`, {
    method: "DELETE",
    signal,
  });
}
