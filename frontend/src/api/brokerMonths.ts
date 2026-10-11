import { apiMultipart, apiRequest } from "./client";
import type { MyBrokerDocument } from "./mybrokerImport";

export type BrokerMonthIntent = { reporting_month_id: number; account_id: number };
export type AccountBindingDecision = { identity: string; hermes_id: number };
export type BrokerMonthPreview = BrokerMonthIntent & {
  contract_version: "broker_month_v1";
  confirmation_digest: string;
  account_bindings: AccountBindingDecision[];
  account_aliases: (AccountBindingDecision & {
    origins: ("filename_account" | "acc_code")[];
    target_name: string | null;
    action: "reuse" | "stage_create";
    mapping_id: number | null;
  })[];
  document: MyBrokerDocument;
  conflicts: string[];
  exceptions: string[];
  can_apply: boolean;
  bookkeeping_ready: boolean;
  cash_control_difference_kopecks: number | null;
  opening_date: string;
  ending_date: string;
};
export type BrokerMonthReadback = BrokerMonthIntent & {
  contract_version: "broker_month_v1";
  request_id: string;
  confirmation_digest: string;
  import_id: number;
  status: "draft" | "closed";
  exceptions: string[];
  bookkeeping_ready: boolean;
  accepted: {
    document: MyBrokerDocument | null;
    position_ids: number[];
    cash_id: number;
    trade_ids: number[];
    source_digest: string;
    projection_digest: string;
  };
};

export function previewBrokerMonth(file: File, intent: BrokerMonthIntent) {
  const form = new FormData();
  form.append("file", file);
  form.append("intent", JSON.stringify(intent));
  return apiMultipart<BrokerMonthPreview>("/api/broker-months/preview", form);
}

export function applyBrokerMonth(
  file: File,
  intent: BrokerMonthIntent,
  digest: string,
  requestId: string,
  reviewedAccountBindings: AccountBindingDecision[],
) {
  const form = new FormData();
  form.append("file", file);
  form.append(
    "confirmation",
    JSON.stringify({
      ...intent,
      confirmation_digest: digest,
      request_id: requestId,
      reviewed_account_bindings: reviewedAccountBindings,
    }),
  );
  return apiMultipart<BrokerMonthReadback>("/api/broker-months/apply", form);
}

export function readBrokerMonth(requestId: string) {
  return apiRequest<BrokerMonthReadback>(`/api/broker-months/${encodeURIComponent(requestId)}`);
}

export function listBrokerMonths(monthId: number, signal?: AbortSignal) {
  return apiRequest<BrokerMonthReadback[]>(`/api/broker-months?reporting_month_id=${monthId}`, {
    signal,
  });
}
