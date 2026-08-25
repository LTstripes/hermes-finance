import { apiRequest } from "./client";
import type { SavingAllocation, SavingUpdate } from "./types";

export function listSavings(monthId: number, signal?: AbortSignal): Promise<SavingAllocation[]> {
  return apiRequest<SavingAllocation[]>(`/api/savings?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createSaving(
  payload: {
    reporting_month_id: number;
    destination: string;
    amount: { amount: string; currency: string };
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<SavingAllocation> {
  return apiRequest<SavingAllocation>("/api/savings", { method: "POST", body: payload, signal });
}

export function updateSaving(
  id: number,
  payload: SavingUpdate,
  signal?: AbortSignal,
): Promise<SavingAllocation> {
  return apiRequest<SavingAllocation>(`/api/savings/${id}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteSaving(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/savings/${id}`, { method: "DELETE", signal });
}
