import { apiRequest } from "./client";
import type { ExpenseEntry } from "./types";

export function listExpenses(monthId: number, signal?: AbortSignal): Promise<ExpenseEntry[]> {
  return apiRequest<ExpenseEntry[]>(`/api/expenses?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createExpense(
  payload: {
    reporting_month_id: number;
    category: string;
    amount: { amount: string; currency: string };
    expense_type: string;
    is_recurring?: boolean;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<ExpenseEntry> {
  return apiRequest<ExpenseEntry>("/api/expenses", { method: "POST", body: payload, signal });
}

export function deleteExpense(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/expenses/${id}`, { method: "DELETE", signal });
}
