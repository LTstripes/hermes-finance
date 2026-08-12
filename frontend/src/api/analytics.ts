import { apiRequest } from "./client";
import type { CapitalCompositionHistory } from "./types";

export function getCapitalComposition(signal?: AbortSignal): Promise<CapitalCompositionHistory> {
  return apiRequest<CapitalCompositionHistory>("/api/analytics/capital-composition", {
    method: "GET",
    signal,
  });
}
