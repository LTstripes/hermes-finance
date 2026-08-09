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
