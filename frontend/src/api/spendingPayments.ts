import { apiRequest } from "./client";
import type { SpendingSource } from "./spending";

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
  version: number;
};

export type PaymentCard = {
  token: string;
  title: string;
  fact_amount: string;
  category_mandatory: boolean;
  rule: PaymentRule | null;
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
  card: (purchase: Purchase, signal?: AbortSignal) =>
    apiRequest<PaymentCard>(path(purchase), { signal, cache: "no-store" }),
  save: (purchase: Purchase, token: string, edit: PaymentEdit) =>
    apiRequest<PaymentCard>(path(purchase), { method: "PUT", body: { ...edit, token } }),
  reattach: (purchase: Purchase, token: string, rule: PaymentRule) =>
    apiRequest<PaymentCard>(path(purchase, "/reattach"), {
      method: "POST",
      body: { token, rule_id: rule.id, version: rule.version },
    }),
};
