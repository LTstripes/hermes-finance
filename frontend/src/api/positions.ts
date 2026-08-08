import { apiRequest } from "./client";
import type { PositionCreate, PositionSnapshot, PositionUpdate } from "./types";

export function listPositions(
  monthId: number,
  accountId?: number,
  signal?: AbortSignal,
): Promise<PositionSnapshot[]> {
  const query = new URLSearchParams({ month_id: String(monthId) });
  if (accountId != null) {
    query.set("account_id", String(accountId));
  }
  return apiRequest<PositionSnapshot[]>(`/api/positions?${query.toString()}`, {
    method: "GET",
    signal,
  });
}

export function createPosition(
  payload: PositionCreate,
  signal?: AbortSignal,
): Promise<PositionSnapshot> {
  return apiRequest<PositionSnapshot>("/api/positions", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updatePosition(
  snapshotId: number,
  payload: PositionUpdate,
  ifMatch: string,
  signal?: AbortSignal,
): Promise<PositionSnapshot> {
  return apiRequest<PositionSnapshot>(`/api/positions/${snapshotId}`, {
    method: "PATCH",
    body: payload,
    headers: { "If-Match": ifMatch },
    signal,
  });
}

export function deletePosition(snapshotId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/positions/${snapshotId}`, { method: "DELETE", signal });
}
