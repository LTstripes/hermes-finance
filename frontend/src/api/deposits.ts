import { apiRequest } from "./client";
import type { DepositCreate, DepositSnapshot, DepositUpdate } from "./types";

export function listDeposits(monthId: number, signal?: AbortSignal): Promise<DepositSnapshot[]> {
  return apiRequest<DepositSnapshot[]>(`/api/deposits?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}

export function createDeposit(
  payload: DepositCreate,
  signal?: AbortSignal,
): Promise<DepositSnapshot> {
  return apiRequest<DepositSnapshot>("/api/deposits", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateDeposit(
  snapshotId: number,
  payload: DepositUpdate,
  ifMatch: string,
  signal?: AbortSignal,
): Promise<DepositSnapshot> {
  return apiRequest<DepositSnapshot>(`/api/deposits/${snapshotId}`, {
    method: "PATCH",
    body: payload,
    headers: { "If-Match": ifMatch },
    signal,
  });
}

export function deleteDeposit(snapshotId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/deposits/${snapshotId}`, { method: "DELETE", signal });
}
