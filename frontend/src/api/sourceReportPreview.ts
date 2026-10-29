import { apiMultipart } from "./client";

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
