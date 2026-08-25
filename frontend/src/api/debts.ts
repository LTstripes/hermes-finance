import { apiRequest } from "./client";
import type { DebtEntry, DebtUpdate } from "./types";

export function listDebts(monthId: number, signal?: AbortSignal): Promise<DebtEntry[]> {
  return apiRequest<DebtEntry[]>(`/api/debts?month_id=${monthId}`, { method: "GET", signal });
}

export function createDebt(
  payload: {
    reporting_month_id: number;
    debt_type: string;
    name: string;
    current_balance: { amount: string; currency: string };
    include_in_liquid_capital?: boolean;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<DebtEntry> {
  return apiRequest<DebtEntry>("/api/debts", { method: "POST", body: payload, signal });
}

export function updateDebt(
  id: number,
  payload: DebtUpdate,
  signal?: AbortSignal,
): Promise<DebtEntry> {
  return apiRequest<DebtEntry>(`/api/debts/${id}`, { method: "PATCH", body: payload, signal });
}

export function deleteDebt(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/debts/${id}`, { method: "DELETE", signal });
}
