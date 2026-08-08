import { apiRequest } from "./client";
import type { CashBalance, CashBalanceCreate, CashBalanceUpdate, CashTotal } from "./types";

export function listCashBalances(monthId: number, signal?: AbortSignal): Promise<CashBalance[]> {
  return apiRequest<CashBalance[]>(`/api/cash-balances?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function getCashTotal(monthId: number, signal?: AbortSignal): Promise<CashTotal> {
  return apiRequest<CashTotal>(`/api/cash-balances/total?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createCashBalance(
  payload: CashBalanceCreate,
  signal?: AbortSignal,
): Promise<CashBalance> {
  return apiRequest<CashBalance>("/api/cash-balances", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateCashBalance(
  balanceId: number,
  payload: CashBalanceUpdate,
  signal?: AbortSignal,
): Promise<CashBalance> {
  return apiRequest<CashBalance>(`/api/cash-balances/${balanceId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteCashBalance(balanceId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/cash-balances/${balanceId}`, { method: "DELETE", signal });
}
