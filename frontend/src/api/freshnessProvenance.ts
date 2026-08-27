import { apiRequest } from "./client";
import type { FreshnessProvenanceSummary } from "./types";

export function getFreshnessProvenance(
  monthId: number,
  signal?: AbortSignal,
): Promise<FreshnessProvenanceSummary> {
  return apiRequest<FreshnessProvenanceSummary>(`/api/months/${monthId}/freshness-provenance`, {
    method: "GET",
    signal,
  });
}
