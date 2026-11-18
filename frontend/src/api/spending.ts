import { apiDownload, apiMultipart, apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type ExpenseType = "mandatory" | "comfortable" | "other";
export type SpendingSource = "alfa" | "cash" | "sber" | "manual_other" | "month_entries";
export type Coverage = { from: string | null; to: string | null; full: boolean };
export type SpendingHistoryItem = {
  month: string;
  loaded: boolean;
  total: MoneyValue | null;
  by_type: Record<ExpenseType, MoneyValue | null>;
  refunds_total: MoneyValue | null;
  coverage: Coverage;
  partial: boolean;
  has_statement: boolean;
  has_manual: boolean;
  month_entries_total: MoneyValue;
};
type History = { items: SpendingHistoryItem[]; has_more: boolean };
export type SpendingCategory = { id: number; name: string; expense_type: ExpenseType };
export type CategoryAmount = {
  id: number;
  name: string;
  type: ExpenseType;
  amount: MoneyValue;
  share_percent: string | null;
  average_3m: MoneyValue | null;
  delta_percent: string | null;
  is_new: boolean;
};
export type SpendingOperation = {
  id: number;
  date: string | null;
  description: string;
  category_id: number | null;
  category_name: string;
  source: SpendingSource;
  amount: MoneyValue;
  kind: "refund" | "purchase";
  processing: boolean;
  linked_entry: { category: string; amount: MoneyValue } | null;
  is_month_entry: boolean;
};
type OperationList = {
  items: SpendingOperation[];
  total_count: number;
  filtered_total: MoneyValue;
};
export type EntryLink = {
  id: number | null;
  expense_entry_id: number;
  entry_category: string;
  month_amount: MoneyValue;
  diary_amount: MoneyValue;
  automatic: boolean;
  confirmed: boolean;
  operation_ids: number[];
};
type Day = { day: number; cumulative: MoneyValue };
export type SpendingMonth = SpendingHistoryItem & {
  known_subtotal: MoneyValue;
  processing_total: MoneyValue;
  by_source: Record<SpendingSource, MoneyValue>;
  categories: CategoryAmount[];
  positive_categories: CategoryAmount[];
  comparison: {
    average_total: MoneyValue;
    delta_percent: string | null;
    months: { month: string; has_manual: boolean }[];
  } | null;
  cash: { withdrawn: MoneyValue | null; recorded: MoneyValue };
  entry_links: EntryLink[];
  open_exceptions: { count: number; excluded_count: number; double_risk_count: number };
  top_purchases: SpendingOperation[];
  daily: {
    current: Day[];
    previous: { month: string; points: Day[] } | null;
    previous_unavailable_reason: "not_loaded" | "partial" | null;
    undated_total: MoneyValue;
    month_entries_total: MoneyValue;
  };
};
export type SpendingRule = {
  id: number;
  scope: "merchant" | "bank_category";
  key: string;
  action: "expense" | "refund" | "not_spending";
  category_id: number | null;
};
export type FileKind = "statement" | "manual";
export type FileProblem = {
  file: FileKind;
  code: string;
  line?: number;
  file_month?: string | null;
  from?: string;
  to?: string;
};
export type PreviewRow = {
  id: number;
  operation_date: string | null;
  description: string;
  category?: string | null;
  bank_category?: string | null;
  amount_kopecks: number;
  currency: string;
  kind?: string;
  fingerprint: string;
  ordinal: number;
};
export type ExceptionGroup =
  | "transfer"
  | "possible_duplicate"
  | "refund"
  | "entry_link"
  | "foreign_currency"
  | "unknown_debit"
  | "new_category"
  | "uncategorized";
export type RowAction = "expense" | "refund" | "not_spending" | "separate" | "duplicate";
type PreviousDecision = { action?: RowAction; decision?: RowAction; description?: string };
export type SpendingException = {
  id: string;
  expense_entry_id?: number;
  review_id?: number;
  link_id?: number;
  fingerprint?: string;
  ordinal?: number;
  group: ExceptionGroup;
  date?: string | null;
  description?: string;
  amount?: MoneyValue;
  bank_category?: string | null;
  category?: string;
  candidates: PreviewRow[];
  remember_key: string | null;
  remember_default: boolean;
  carried_over_failed: boolean;
  previous_decision?: PreviousDecision | null;
  previous_decisions?: PreviousDecision[];
  counted_now: boolean;
  kind_hint: string | null;
  recurring: boolean;
};
export type Resolution = {
  id: string;
  action: RowAction | "link" | "unlink" | "acknowledge";
  category?: string;
  duplicate_of_id?: number;
  operation_ids?: number[];
  remember?: boolean;
};
export type PreviewDecision = {
  choices?: (Omit<Resolution, "id" | "action" | "operation_ids"> & {
    action: RowAction;
    fingerprint: string;
    ordinal: number;
  })[];
  entry_links?: {
    expense_entry_id: number;
    action: "link" | "separate";
    operation_ids?: number[];
    remember?: boolean;
  }[];
  skip_error_lines?: number[];
};
export type SpendingPreview = {
  preview_id: string;
  month: string;
  stale: boolean;
  applicable: boolean;
  total_before: MoneyValue | null;
  total_after: MoneyValue | null;
  sets: {
    label: string;
    kind: FileKind;
    added: number;
    changed: number;
    removed: number;
    total_before: MoneyValue | null;
    total_after: MoneyValue;
    removed_items: PreviewRow[];
    changed_items: PreviewRow[];
  }[];
  exceptions: SpendingException[];
  operations: PreviewRow[];
  technical: { count: number; items: PreviewRow[] };
  processing: { count: number; amount: MoneyValue };
  coverage: Coverage;
  out_of_month: { count: number; from: string | null; to: string | null };
  file_errors: FileProblem[];
  blocking: { needs_removal_confirmation: boolean; unreadable_manual_rows: number[] };
  entry_links: EntryLink[];
  added: number;
  changed: number;
  removed: number;
};
type Exceptions = {
  month: string;
  items: SpendingException[];
  count: number;
  total: MoneyValue | null;
};
type ApplyResult = Pick<SpendingPreview, "added" | "changed" | "removed"> & {
  month: SpendingMonth;
};

const root = "/api/spending";
function query(params: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  return search.size ? `?${search}` : "";
}

export const spendingApi = {
  history: (until?: string, count = 12, category?: number, signal?: AbortSignal) =>
    apiRequest<History>(
      `${root}${category === undefined ? "/months" : `/categories/${category}/history`}${query({ until, count })}`,
      { signal },
    ),
  month: (month: string, signal?: AbortSignal) =>
    apiRequest<SpendingMonth>(`${root}/months/${month}`, { signal, cache: "no-store" }),
  operations: (
    month: string,
    category?: number,
    source?: SpendingSource,
    limit?: number,
    signal?: AbortSignal,
  ) =>
    apiRequest<OperationList>(`${root}/operations${query({ month, category, source, limit })}`, {
      signal,
    }),
  template: (month: string) => apiDownload(`${root}/manual-template${query({ month })}`),
  preview: (month: string, files: Partial<Record<FileKind, File>>) => {
    const form = new FormData();
    form.set("month", month);
    for (const kind of ["statement", "manual"] as const) {
      const file = files[kind];
      if (file) form.set(kind, file);
    }
    return apiMultipart<SpendingPreview>(`${root}/preview`, form);
  },
  decide: (id: string, body: PreviewDecision) =>
    apiRequest<SpendingPreview>(`${root}/preview/${id}/decisions`, { method: "POST", body }),
  apply: (id: string, confirm_removal: boolean, skip_unreadable_manual: boolean) =>
    apiRequest<ApplyResult>(`${root}/preview/${id}/apply`, {
      method: "POST",
      body: { confirm_removal, skip_unreadable_manual },
    }),
  exceptions: (month: string, signal?: AbortSignal) =>
    apiRequest<Exceptions>(`${root}/exceptions${query({ month })}`, { signal, cache: "no-store" }),
  resolve: (month: string, decision: Resolution) =>
    apiRequest<{ exceptions: Exceptions; month: SpendingMonth }>(
      `${root}/exceptions/decisions${query({ month })}`,
      { method: "POST", body: { decisions: [decision] } },
    ),
  categories: (signal?: AbortSignal) =>
    apiRequest<SpendingCategory[]>(`${root}/categories`, { signal, cache: "no-store" }),
  patchCategory: (id: number, body: Partial<Pick<SpendingCategory, "name" | "expense_type">>) =>
    apiRequest<SpendingCategory>(`${root}/categories/${id}`, { method: "PATCH", body }),
  mergeCategory: (id: number, target_id: number) =>
    apiRequest<SpendingCategory>(`${root}/categories/${id}/merge`, {
      method: "POST",
      body: { target_id },
    }),
  rules: (signal?: AbortSignal) =>
    apiRequest<SpendingRule[]>(`${root}/rules`, { signal, cache: "no-store" }),
  deleteRule: (id: number) => apiRequest(`${root}/rules/${id}`, { method: "DELETE" }),
  links: (signal?: AbortSignal) =>
    apiRequest<(EntryLink & { month: string })[]>(`${root}/entry-links`, {
      signal,
      cache: "no-store",
    }),
  unlink: (id: number) => apiRequest(`${root}/entry-links/${id}`, { method: "DELETE" }),
};
