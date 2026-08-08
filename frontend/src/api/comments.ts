import { apiRequest } from "./client";
import type { MonthlyComment } from "./types";

export function listComments(monthId: number, signal?: AbortSignal): Promise<MonthlyComment[]> {
  return apiRequest<MonthlyComment[]>(`/api/comments?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createComment(
  payload: { reporting_month_id: number; text: string },
  signal?: AbortSignal,
): Promise<MonthlyComment> {
  return apiRequest<MonthlyComment>("/api/comments", { method: "POST", body: payload, signal });
}

export function deleteComment(id: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/comments/${id}`, { method: "DELETE", signal });
}

export function moveComment(
  id: number,
  newPosition: number,
  signal?: AbortSignal,
): Promise<MonthlyComment> {
  return apiRequest<MonthlyComment>(`/api/comments/${id}/move`, {
    method: "POST",
    body: { new_position: newPosition },
    signal,
  });
}
