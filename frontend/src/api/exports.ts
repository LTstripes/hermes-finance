import { apiDownload, type ApiDownload } from "./client";

export function downloadMarkdownReport(
  monthId: number,
  signal?: AbortSignal,
): Promise<ApiDownload> {
  return apiDownload(`/api/months/${monthId}/export/markdown`, {
    method: "POST",
    signal,
  });
}

export function downloadJsonReport(monthId: number, signal?: AbortSignal): Promise<ApiDownload> {
  return apiDownload(`/api/months/${monthId}/export/json`, {
    method: "POST",
    signal,
  });
}

export function downloadAiAnalysisBundleJson(signal?: AbortSignal): Promise<ApiDownload> {
  return apiDownload("/api/export/ai-analysis-bundle", {
    method: "POST",
    signal,
  });
}

export function downloadAiAnalysisBundleMarkdown(signal?: AbortSignal): Promise<ApiDownload> {
  return apiDownload("/api/export/ai-analysis-bundle/markdown", {
    method: "POST",
    signal,
  });
}
