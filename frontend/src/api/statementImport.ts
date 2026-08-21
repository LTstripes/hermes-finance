import { apiMultipart } from "./client";

export type StatementMapping = {
  account_mappings: { hermes_account_id: number; provider_account_ref: string }[];
  instrument_mappings: { hermes_instrument_id: number; isin: string }[];
};

export type StatementRow = {
  status: string;
  duplicate_class: "duplicate" | "correction" | null;
  provider_account_ref?: string | null;
  expected_hermes_account_id: number | null;
  expected_hermes_instrument_id: number | null;
  natural_identity: string | null;
  material_fingerprint: string | null;
  expected_candidate_ids: number[];
  reason: string | null;
  [key: string]: unknown;
};

export type StatementPreparation = {
  provider: string;
  document_sha256: string;
  status: string;
  rows: StatementRow[];
  warnings: string[];
  reason: string | null;
};

function baseForm(file: File, mapping: StatementMapping) {
  const form = new FormData();
  form.append("document", file, file.name);
  form.append("account_mappings", JSON.stringify(mapping.account_mappings));
  form.append("instrument_mappings", JSON.stringify(mapping.instrument_mappings));
  return form;
}

export function inspectStatement(file: File, signal?: AbortSignal) {
  const form = new FormData();
  form.append("document", file, file.name);
  return apiMultipart<{
    document_sha256: string;
    status: string;
    rows: StatementRow[];
    warnings: string[];
    reason: string | null;
  }>("/api/statement-import/inspect", form, signal);
}

export function prepareStatement(file: File, mapping: StatementMapping, signal?: AbortSignal) {
  return apiMultipart<StatementPreparation>(
    "/api/statement-import/prepare",
    baseForm(file, mapping),
    signal,
  );
}

export function applyStatement(
  file: File,
  mapping: StatementMapping,
  selections: unknown[],
  expectedDocumentSha256: string,
  signal?: AbortSignal,
) {
  const form = baseForm(file, mapping);
  form.append("selections", JSON.stringify(selections));
  form.append("expected_document_sha256", expectedDocumentSha256);
  return apiMultipart<{
    success: boolean;
    selected_count: number;
    error_code: string | null;
    message: string | null;
  }>("/api/statement-import/apply", form, signal);
}
