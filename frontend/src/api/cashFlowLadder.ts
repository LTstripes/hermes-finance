import { apiRequest } from "./client";
import type { CashFlowLadder } from "./types";

export function getCashFlowLadder(monthId: number, signal?: AbortSignal): Promise<CashFlowLadder> {
  const params = new URLSearchParams({ forecast_version: "v1" });
  return apiRequest<CashFlowLadder>(
    `/api/months/${monthId}/cash-flow-ladder?${params.toString()}`,
    { method: "GET", signal },
  );
}
