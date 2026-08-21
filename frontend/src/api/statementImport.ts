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
  candidates: {
    investment_cash_flow_id: number;
    reporting_month_id: number;
    account_id: number;
    instrument_id: number | null;
    flow_type: string;
    event_date: string;
    gross_amount_kopecks: number;
    tax_amount_kopecks: number;
    commission_amount_kopecks: number;
    net_amount_kopecks: number;
    currency: string;
    source: string;
  }[];
  isin: string | null;
  event_date: string | null;
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

export type StatementInspect = {
  document_sha256: string;
  status: string;
  rows: {
    status: string;
    provider_account_ref: string | null;
    isin: string | null;
    event_kind: string | null;
    record_date: string | null;
    event_date: string | null;
    reason: string | null;
  }[];
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
  return apiMultipart<StatementInspect>("/api/statement-import/inspect", form, signal);
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
    items: {
      action: string;
      natural_identity: string;
      applied_statement_event_id: number;
      investment_cash_flow_id: number;
      material_fingerprint: string;
      revision_id: number | null;
    }[];
    error_code: string | null;
    message: string | null;
  }>("/api/statement-import/apply", form, signal);
}
