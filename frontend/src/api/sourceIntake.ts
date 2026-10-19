import type { BrokerMonthPreview, InstrumentDecision } from "./brokerMonths";
import { apiMultipart, apiRequest } from "./client";
import type { MyBrokerDocument } from "./mybrokerImport";

export type IntakeIntent = {
  expected_head_seq: number;
  account_id: number | null;
  reporting_month_id: number | null;
  default_enabled: boolean;
  account_currency: string | null;
  overrides: { isin: string; currency: string | null }[];
  instrument_decisions: InstrumentDecision[];
  deferred_isins: string[];
  finance_request_id?: string;
};
export type CurrencyAssessment = {
  observed_denomination: string | null;
  effective_currency: string | null;
  basis: string;
  denomination_proven: boolean;
  provisional: boolean;
  policy_revision: number;
  override_revision: number | null;
  reasons: string[];
};
export type SourceIntake = {
  contract_version: "source_intake_v1";
  id: number;
  document_sha256: string;
  generation: number;
  head_seq: number;
  manifest_digest: string;
  original_required: boolean;
  covered_from: string;
  covered_to: string;
  state: Omit<IntakeIntent, "expected_head_seq" | "overrides" | "finance_request_id"> & {
    policy_revision: number;
    overrides: Record<string, string>;
  };
  document: MyBrokerDocument;
  proposals: (NonNullable<BrokerMonthPreview["identity"]>["instruments"][number] & {
    currency_assessment: CurrencyAssessment;
  })[];
  observations: { id: number; row_class: string; section: string; ordinal: number }[];
  exceptions: string[];
  financial_authority: "none";
  finance_link: { request_id: string; blockers: string[] } | null;
  history: { seq: number; operation: string; request_id: string; reviewer: string }[];
};
export type IntakeAck = {
  intake_id: number;
  request_id: string;
  head_seq: number;
  duplicate: boolean;
};

const base = "/api/broker-months/intakes";
export const listSourceIntakes = (monthId: number, signal?: AbortSignal) =>
  apiRequest<SourceIntake[]>(`${base}?reporting_month_id=${monthId}&include_unbound=true`, {
    signal,
  });
export const listAllSourceIntakes = (signal?: AbortSignal) =>
  apiRequest<SourceIntake[]>(`${base}?include_unbound=true`, { signal });
export const readSourceIntake = (id: number, signal?: AbortSignal) =>
  apiRequest<SourceIntake>(`${base}/${id}`, { signal });

function form(file: File, field: string, intent: unknown) {
  const value = new FormData();
  value.append("file", file);
  value.append(field, JSON.stringify(intent));
  return value;
}
export function saveSourceIntake(
  file: File,
  requestId: string,
  monthId: number,
  accountId: number | null,
) {
  return apiMultipart<IntakeAck>(
    base,
    form(file, "intent", {
      request_id: requestId,
      reporting_month_id: accountId === null ? null : monthId,
      account_id: accountId,
    }),
  );
}
export const previewIntakeReview = (id: number, file: File, intent: IntakeIntent) =>
  apiMultipart<{ confirmation_digest: string; financial_effects: number }>(
    `${base}/${id}/review-preview`,
    form(file, "intent", intent),
  );
export function confirmIntakeReview(
  id: number,
  file: File,
  intent: IntakeIntent,
  confirmationDigest: string,
  requestId: string,
  link = false,
) {
  return apiMultipart<IntakeAck>(
    `${base}/${id}/${link ? "finance-link" : "decisions"}`,
    form(file, "confirmation", {
      ...intent,
      request_id: requestId,
      confirmation_digest: confirmationDigest,
    }),
  );
}
