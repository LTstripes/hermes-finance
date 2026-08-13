import { apiRequest } from "./client";
import type { QuotePreview } from "./types";

export function previewMonthQuotes(monthId: number, signal?: AbortSignal): Promise<QuotePreview> {
  return apiRequest<QuotePreview>(`/api/months/${monthId}/quote-preview`, {
    method: "POST",
    signal,
  });
}
