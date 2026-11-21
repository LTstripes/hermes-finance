import { apiRequest } from "./client";
import type { SpendingSource } from "./spending";

export type PaymentOccurrence = {
  id: number;
  month: string;
  source: SpendingSource;
  operation_id: number | null;
  title: string;
  decision: "payment" | "separate";
  needs_review: boolean;
};
export type PaymentRule = {
  id: number;
  title: string;
  month: string;
  source: SpendingSource;
  operation_id: number | null;
  note: string;
  mandatory_override: boolean | null;
  mandatory: boolean | null;
  repeat: boolean;
  period_months: number | null;
  next_due: string | null;
  amount: string | null;
  monthly_amount: string | null;
  needs_review: boolean;
  archived: boolean;
  was_recurring: boolean;
  occurrences: PaymentOccurrence[];
  version: number;
};

export type PaymentCard = {
  token: string;
  title: string;
  fact_amount: string;
  category_mandatory: boolean;
  rule: PaymentRule | null;
  schedules: Pick<
    PaymentRule,
    "id" | "title" | "month" | "version" | "repeat" | "amount" | "next_due"
  >[];
  decisions: (PaymentOccurrence & { rule_id: number; rule_title: string; rule_version: number })[];
};
export type PaymentEdit = {
  note: string;
  mandatory_override: boolean | null;
  repeat: boolean;
  period_months: number | null;
  next_due: string | null;
  amount: string | null;
};
export type Purchase = { month: string; source: SpendingSource; id: number };
const root = "/api/spending/payment-rules";
function path(purchase: Purchase, action = "") {
  return `${root}/${purchase.source}/${purchase.id}${action}?month=${purchase.month}`;
}
export const paymentApi = {
  list: (month: string, signal?: AbortSignal) =>
    apiRequest<PaymentRule[]>(`${root}?month=${month}`, { signal, cache: "no-store" }),
  archive: (month: string, rule: PaymentRule) =>
    apiRequest<PaymentRule>(`/api/spending/archived-payment-rules/${rule.id}?month=${month}`, {
      method: "POST",
      body: { version: rule.version },
    }),
  card: (purchase: Purchase, signal?: AbortSignal) =>
    apiRequest<PaymentCard>(path(purchase), { signal, cache: "no-store" }),
  save: (purchase: Purchase, token: string, edit: PaymentEdit) =>
    apiRequest<PaymentCard>(path(purchase), { method: "PUT", body: { ...edit, token } }),
  occurrence: (
    purchase: Purchase,
    token: string,
    rule_id: number,
    version: number,
    decision: "payment" | "separate",
  ) =>
    apiRequest<PaymentCard>(path(purchase, "/occurrence"), {
      method: "PUT",
      body: { token, rule_id, version, decision },
    }),
  undoOccurrence: (purchase: Purchase, token: string, occurrence_id: number, version: number) =>
    apiRequest<PaymentCard>(path(purchase, "/undo-occurrence"), {
      method: "POST",
      body: { token, occurrence_id, version },
    }),
  reattach: (purchase: Purchase, token: string, rule: PaymentRule) =>
    apiRequest<PaymentCard>(path(purchase, "/reattach"), {
      method: "POST",
      body: { token, rule_id: rule.id, version: rule.version },
    }),
};
