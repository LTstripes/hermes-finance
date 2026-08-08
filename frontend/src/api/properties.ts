import { apiRequest } from "./client";
import type { PropertySnapshot } from "./types";

export function listProperties(monthId: number, signal?: AbortSignal): Promise<PropertySnapshot[]> {
  return apiRequest<PropertySnapshot[]>(`/api/properties?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createProperty(
  payload: {
    reporting_month_id: number;
    name: string;
    estimated_value: { amount: string; currency: string };
    mortgage_balance: { amount: string; currency: string };
    monthly_payment: { amount: string; currency: string };
    notes?: string | null;
  },
  signal?: AbortSignal,
): Promise<PropertySnapshot> {
  return apiRequest<PropertySnapshot>("/api/properties", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function deleteProperty(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/properties/${id}`, { method: "DELETE", signal });
}
