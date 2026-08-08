import { apiRequest } from "./client";
import type { IncomeCreate, IncomeEntry, IncomeUpdate } from "./types";

export function listIncomes(monthId: number, signal?: AbortSignal): Promise<IncomeEntry[]> {
  return apiRequest<IncomeEntry[]>(`/api/incomes?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createIncome(payload: IncomeCreate, signal?: AbortSignal): Promise<IncomeEntry> {
  return apiRequest<IncomeEntry>("/api/incomes", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateIncome(
  entryId: number,
  payload: IncomeUpdate,
  signal?: AbortSignal,
): Promise<IncomeEntry> {
  return apiRequest<IncomeEntry>(`/api/incomes/${entryId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteIncome(entryId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/incomes/${entryId}`, { method: "DELETE", signal });
}
