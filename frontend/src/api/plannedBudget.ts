import { apiRequest } from "./client";
import type { PlannedBudgetLine, PlannedBudgetUpdate, PlanVsActualRow } from "./types";

export function listPlannedBudget(
  monthId: number,
  signal?: AbortSignal,
): Promise<PlannedBudgetLine[]> {
  return apiRequest<PlannedBudgetLine[]>(`/api/planned-budget?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function plannedVsActual(monthId: number, signal?: AbortSignal): Promise<PlanVsActualRow[]> {
  return apiRequest<PlanVsActualRow[]>(`/api/planned-budget/comparison?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createPlannedBudget(
  payload: {
    reporting_month_id: number;
    category: string;
    planned_amount: { amount: string; currency: string };
    expense_type: string;
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<PlannedBudgetLine> {
  return apiRequest<PlannedBudgetLine>("/api/planned-budget", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updatePlannedBudget(
  id: number,
  payload: PlannedBudgetUpdate,
  signal?: AbortSignal,
): Promise<PlannedBudgetLine> {
  return apiRequest<PlannedBudgetLine>(`/api/planned-budget/${id}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deletePlannedBudget(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/planned-budget/${id}`, { method: "DELETE", signal });
}
