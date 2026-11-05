import { apiMultipart, apiRequest } from "./client";

export type BrokerSourceIssue = {
  code: string;
  isin?: string | null;
  name?: string | null;
  source_account?: string | null;
  date?: string | null;
  quantity?: string | null;
  amount?: string | null;
  currency?: string | null;
  section?: string;
  ordinal?: number;
};

export type BrokerSource = {
  intake_id: number | null;
  receipt_seq?: number;
  document_sha256: string;
  filename_digest: string;
  kind: "mybroker_xml" | "income_pdf";
  slot: string;
  source_accounts: string[];
  covered_from: string;
  covered_to: string;
  state: "file_saved" | "needs_decision" | "financial_data_accepted";
  exceptions: string[];
  review_issues?: BrokerSourceIssue[];
  information_codes?: string[];
  head_seq: number;
  request_ids: string[];
};
export type BrokerSources = {
  reporting_month_id: number;
  items: BrokerSource[];
  confirmation_count: number;
  status: "empty" | "ok" | "needs_confirmation";
  severity: "warning" | null;
  financial_effects: 0;
};
export type BrokerSourceResult = {
  index: number;
  item: BrokerSource | null;
  duplicate?: boolean;
  error: { code: string; message: string } | null;
};
export const readBrokerSources = (monthId: number, signal?: AbortSignal) =>
  apiRequest<BrokerSources>(`/api/months/${monthId}/broker-sources`, { signal });
export function uploadBrokerSources(monthId: number, files: File[], requestId: string) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("request_id", requestId);
  return apiMultipart<BrokerSources & { results: BrokerSourceResult[] }>(
    `/api/months/${monthId}/broker-sources`,
    form,
  );
}

export async function brokerFileIdentity(file: File) {
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
  const sha = async (value: BufferSource) =>
    [...new Uint8Array(await crypto.subtle.digest("SHA-256", value))]
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("");
  const name = JSON.stringify(file.name).replace(
    /[\u007f-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
  return {
    document_sha256: await sha(bytes),
    filename_digest: await sha(new TextEncoder().encode(name)),
  };
}
