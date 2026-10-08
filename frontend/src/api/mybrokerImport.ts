import { apiMultipart, apiRequest } from "./client";

export type MyBrokerBinding = {
  kind: "account" | "instrument";
  identity: string;
  mapping_id: number;
  hermes_id: number;
};
export type MyBrokerTrade = {
  section: string;
  ordinal: number;
  identity: string | null;
  ids: string[];
  state: "pending" | "settled";
  core: {
    source_account: string;
    isin: string;
    trade_time: string;
    quantity: string;
    price: string;
    trade_amount: string;
    currency: string;
  };
  blockers: string[];
};
export type MyBrokerPosition = {
  ordinal: number;
  source_account: string;
  isin: string;
  actual_quantity: string;
  forward_quantity: string;
  beginning_actual_quantity?: string | null;
  beginning_value?: string | null;
  ending_value?: string | null;
};
export type MyBrokerRubMoney = {
  ordinal: number;
  source_account: string;
  currency: string;
  beginning_amount?: string | null;
  ending_amount?: string | null;
};
export type MyBrokerDocument = {
  provider: string;
  parser: string;
  document_sha256: string;
  filename_account: string;
  covered_from: string;
  covered_to: string;
  source_accounts: string[];
  section_inventory: Record<string, number>;
  trades: MyBrokerTrade[];
  positions: MyBrokerPosition[];
  rub_money?: MyBrokerRubMoney[];
  endpoint_basis?: { beginning_value: string; ending_value: string };
  endpoint_blockers?: string[];
  endpoint_conflicts?: string[];
  money: {
    ordinal: number;
    kind: string;
    source_account: string;
    amount: string;
    currency: string;
  }[];
};
export type MyBrokerDisposition = {
  isin: string;
  source_set_fingerprint: string;
  revision_id?: number | null;
  revision?: number;
  effective_state?: "accepted" | "retired" | "revoked" | "invalid";
};
export type MyBrokerChoices = {
  instrument_choices?: { isin: string; choice: "map" | "skip" | "undecided" }[];
  instrument_dispositions?: MyBrokerDisposition[];
  counts?: { mapped: number; skipped: number; unsupported: number };
  already_imported?: number | null;
};
export type MyBrokerPreview = MyBrokerChoices & {
  document: MyBrokerDocument;
  mappings: MyBrokerBinding[];
  missing_mappings: { kind: "account" | "instrument"; identity: string }[];
  confirmation_digest: string;
  conflicts: string[];
  blockers: string[];
  coverage_state: "unknown";
  can_apply: boolean;
};
export type MyBrokerImport = MyBrokerChoices & {
  import_id: number;
  document: MyBrokerDocument;
  mappings: MyBrokerBinding[];
  confirmation_digest: string;
  coverage_state: "unknown";
};

export function previewMyBroker(file: File, skippedIsins: string[] = []) {
  const form = new FormData();
  form.append("file", file);
  form.append(
    "decisions",
    JSON.stringify({ skipped_isins: skippedIsins, owner_reviewed: skippedIsins.length > 0 }),
  );
  return apiMultipart<MyBrokerPreview>("/api/mybroker-import/preview", form);
}

export function applyMyBroker(file: File, preview: MyBrokerPreview) {
  const form = new FormData();
  form.append("file", file);
  form.append(
    "confirmation",
    JSON.stringify({
      confirmation_digest: preview.confirmation_digest,
      covered_from: preview.document.covered_from,
      covered_to: preview.document.covered_to,
      mappings: preview.mappings,
      skipped_isins:
        preview.instrument_choices?.filter((i) => i.choice === "skip").map((i) => i.isin) ?? [],
      owner_reviewed: (preview.counts?.skipped ?? 0) > 0,
      request_id: crypto.randomUUID(),
    }),
  );
  return apiMultipart<MyBrokerImport>("/api/mybroker-import/apply", form);
}

export function readMyBrokerImport(id: number) {
  return apiRequest<MyBrokerImport>(`/api/mybroker-import/${id}`);
}
