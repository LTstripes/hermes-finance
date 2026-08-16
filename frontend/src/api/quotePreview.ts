import { apiRequest } from "./client";
import type { QuoteApplyResult, QuoteApplyRowRequest, QuotePreview } from "./types";

export function previewMonthQuotes(monthId: number, signal?: AbortSignal): Promise<QuotePreview> {
  return apiRequest<QuotePreview>(`/api/months/${monthId}/quote-preview`, {
    method: "POST",
    signal,
  });
}

export function applyMonthQuotes(
  monthId: number,
  rows: QuoteApplyRowRequest[],
  signal?: AbortSignal,
): Promise<QuoteApplyResult> {
  return apiRequest<QuoteApplyResult>(`/api/months/${monthId}/quote-apply`, {
    method: "POST",
    body: { rows },
    signal,
  });
}
