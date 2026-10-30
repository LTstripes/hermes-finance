import { apiMultipart, apiRequest } from "./client";

export type SourceMetric = { value: string | null; status: string; reason_codes: string[] };
export type SourceInstrumentResult = {
  isin: string;
  pnl: SourceMetric;
  known_subtotal: SourceMetric;
  modified_dietz: SourceMetric;
  xirr_annualized: SourceMetric;
  xirr_period: SourceMetric;
  event_count: number;
  reason_codes: string[];
};
export type SourceIntervalResult = Omit<
  SourceInstrumentResult,
  "isin" | "known_subtotal" | "event_count"
> & {
  source_account: string;
  source_sha256: string;
  opening_date: string;
  closing_date: string;
  period_kind: string;
  history_from_zero: boolean;
  known_subtotal?: SourceMetric;
  source_advisories?: string[];
  unresolved_movements?: { isin: string | null; reason: string }[];
  instruments: SourceInstrumentResult[];
  account_only: { kind: string; amount_kopecks: string }[];
  unallocated_payouts: { reference: string; amount_kopecks: string; reason: string }[];
  exceptions?: {
    reference: string;
    date: string;
    amount_kopecks: string | null;
    currency: string;
    classification: string;
    registration: string | null;
  }[];
  reconciliation: {
    xml_payout_occurrences: number;
    linked_payout_occurrences: number;
    cash_delta_kopecks: string | null;
    pdf_closing_delta_kopecks: string | null;
    pdf_pnl_delta_kopecks: string | null;
  };
};
export type SourceReportPreview = {
  persistence?: {
    available: boolean;
    reason_codes: string[];
    preview_digest?: string;
    form_token?: string;
    replacements: {
      source_account: string;
      proof_id: number;
      covered_from: string;
      covered_to: string;
    }[];
  };
  contract: "xml-pdf-source-return-preview-v1";
  financial_apply_available: false;
  close_available: false;
  pdf_period: { covered_from: string; covered_to: string };
  pdf_payout_rows: number;
  source_accounts: string[];
  intervals: SourceIntervalResult[];
  comparison: {
    source_account: string;
    source_sha256?: string;
    kind?: string;
    repeated_native_trades?: number;
    conflicting_native_trades?: number;
    new_native_trades?: number;
    repeated_money_occurrences?: number;
    unmatched_money_occurrences?: number;
    conflicts?: { kind: string; isin: string; identity: string; settlement_date: string | null }[];
  }[];
};

export type InvestmentProofAck = {
  request_id: string;
  preview_digest: string;
  proof_ids: number[];
  current: boolean;
  financial_authority: "none";
};
export type SavedInvestmentReport = {
  pdf_period: { covered_from: string; covered_to: string };
  pdf_payout_rows: number;
  proof_id: number;
  source_account: string;
  covered_from: string;
  covered_to: string;
  status: "current" | "stale";
  reason_codes: string[];
  interval: SourceIntervalResult | null;
  financial_authority: "none";
};
const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string";
const list = (v: unknown, check: (item: unknown) => boolean) => Array.isArray(v) && v.every(check);
const texts = (v: unknown) => list(v, text);
const count = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const cash = (v: unknown) => v === null || (text(v) && /^-?\d+$/.test(v));
const rateValue = (v: unknown) =>
  v === null || (text(v) && /^[+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?$/.test(v));
const metric = (v: unknown, money = false) =>
  object(v) &&
  (money ? cash(v.value) : rateValue(v.value)) &&
  text(v.status) &&
  texts(v.reason_codes);
const bounds = (v: unknown) => object(v) && text(v.covered_from) && text(v.covered_to);
function instrument(v: unknown) {
  return (
    object(v) &&
    text(v.isin) &&
    metric(v.pnl, true) &&
    metric(v.known_subtotal, true) &&
    metric(v.modified_dietz) &&
    metric(v.xirr_period) &&
    metric(v.xirr_annualized) &&
    texts(v.reason_codes) &&
    count(v.event_count)
  );
}
function interval(v: unknown, account: string) {
  return (
    object(v) &&
    v.source_account === account &&
    text(v.source_sha256) &&
    text(v.opening_date) &&
    text(v.closing_date) &&
    text(v.period_kind) &&
    typeof v.history_from_zero === "boolean" &&
    metric(v.pnl, true) &&
    metric(v.modified_dietz) &&
    metric(v.xirr_period) &&
    metric(v.xirr_annualized) &&
    (v.known_subtotal === undefined || metric(v.known_subtotal, true)) &&
    texts(v.reason_codes) &&
    list(v.instruments, instrument) &&
    list(
      v.account_only,
      (item) =>
        object(item) && text(item.kind) && text(item.amount_kopecks) && cash(item.amount_kopecks),
    ) &&
    list(
      v.unallocated_payouts,
      (item) =>
        object(item) && text(item.reference) && cash(item.amount_kopecks) && text(item.reason),
    ) &&
    object(v.reconciliation) &&
    count(v.reconciliation.linked_payout_occurrences) &&
    count(v.reconciliation.xml_payout_occurrences) &&
    cash(v.reconciliation.cash_delta_kopecks) &&
    cash(v.reconciliation.pdf_closing_delta_kopecks) &&
    cash(v.reconciliation.pdf_pnl_delta_kopecks) &&
    (v.source_advisories === undefined || texts(v.source_advisories)) &&
    (v.unresolved_movements === undefined ||
      list(
        v.unresolved_movements,
        (item) => object(item) && (item.isin === null || text(item.isin)) && text(item.reason),
      )) &&
    (v.exceptions === undefined ||
      list(
        v.exceptions,
        (item) =>
          object(item) &&
          text(item.reference) &&
          text(item.date) &&
          text(item.currency) &&
          text(item.classification) &&
          cash(item.amount_kopecks) &&
          (item.registration === null || text(item.registration)),
      ))
  );
}
function savedReport(v: unknown) {
  return (
    object(v) &&
    count(v.proof_id) &&
    text(v.source_account) &&
    text(v.covered_from) &&
    text(v.covered_to) &&
    bounds(v.pdf_period) &&
    count(v.pdf_payout_rows) &&
    v.financial_authority === "none" &&
    texts(v.reason_codes) &&
    ((v.status === "stale" && v.interval === null) ||
      (v.status === "current" && interval(v.interval, v.source_account)))
  );
}
export async function getInvestmentReports(
  account?: string,
  signal?: AbortSignal,
): Promise<{ reports: SavedInvestmentReport[] }> {
  const response = await apiRequest<unknown>(
    `/api/source-returns/investment-reports${account ? `?source_account=${encodeURIComponent(account)}` : ""}`,
    { signal },
  );
  if (!object(response) || !list(response.reports, savedReport)) {
    throw new Error("Сохранённые PDF-связи не удалось проверить. Обновите чтение; числа скрыты.");
  }
  return response as { reports: SavedInvestmentReport[] };
}
export const getInvestmentProofRequest = (requestId: string) =>
  apiRequest<InvestmentProofAck>(
    `/api/source-returns/investment-reports/requests/${encodeURIComponent(requestId)}`,
  );
export const confirmInvestmentReport = (form: {
  form_token: string;
  preview_digest: string;
  request_id: string;
  replace_existing: boolean;
}) =>
  apiRequest<InvestmentProofAck>("/api/source-returns/investment-reports/confirm", {
    method: "POST",
    body: { ...form, attested: true },
  });

export async function previewSourceReports(
  xml: File[],
  pdf: File,
  historyFromZero: boolean,
  signal?: AbortSignal,
): Promise<SourceReportPreview> {
  const form = new FormData();
  for (const file of xml) form.append("files", file, file.name);
  form.append("income_report", pdf, pdf.name);
  form.append("intent", JSON.stringify({ history_from_zero: historyFromZero }));
  const result = await apiMultipart<{ source_return_preview: SourceReportPreview }>(
    "/api/mybroker-preflight/preview",
    form,
    signal,
  );
  const preview = result.source_return_preview;
  if (
    preview?.contract !== "xml-pdf-source-return-preview-v1" ||
    preview.financial_apply_available !== false ||
    preview.close_available !== false
  ) {
    throw new Error("Ответ совместной проверки не подтверждён. Повтори Preview.");
  }
  return preview;
}
