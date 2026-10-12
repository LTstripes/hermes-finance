import { apiRequest } from "./client";

export type StatementSourceChoice = {
  request_id: string;
  account_id: number;
  t0: string;
  t1: string;
};
type StatementEndpoint = {
  account_id: number;
  valuation_date: string;
  timing: "eod";
  currency: string;
  positions_value_kopecks: string | null;
  cash_kopecks: string | null;
  total_value_kopecks: string | null;
  inventory_state: "complete" | "unknown";
  positions: {
    instrument_id: number;
    isin: string;
    quantity: string | null;
    market_value_kopecks: string | null;
    source_ordinal: number;
  }[];
};
export type BrokerStatementReturn = {
  method: "broker_statement_mwr_period_v1";
  scope: "account";
  account_id: number;
  t0: string;
  t1: string;
  currency: "RUB";
  annualized: false;
  status: "indicative" | "unavailable";
  quality: "indicative" | "unavailable";
  rate_fraction: string | null;
  reason_codes: string[];
  warnings: string[];
  opening: StatementEndpoint;
  closing: StatementEndpoint;
  material_fingerprint: string;
  cash_coverage_state: "complete" | "unknown";
  cash_coverage_revision_id: number | null;
  membership_state: "complete" | "unknown";
  exposure_state: "assessed" | "unknown";
  bond_nkd_basis: "unknown" | "not_applicable";
  crossings: {
    event_id: string;
    account_id: number;
    event_date: string;
    currency: string;
    signed_amount_kopecks: string;
    revision_id: number;
    material_signature: string;
  }[];
  sources: {
    import_id: number;
    document_sha256: string;
    parser_version: string;
    source_signature: string;
    request_id: string;
    confirmation_digest: string;
  }[];
};

export function listStatementSources(accountId: number, signal?: AbortSignal) {
  return apiRequest<StatementSourceChoice[]>(
    `/api/broker-statement-returns/sources?account_id=${accountId}`,
    { signal },
  );
}
export function getStatementReturn(accountId: number, requestId: string, signal?: AbortSignal) {
  return apiRequest<BrokerStatementReturn>(
    `/api/broker-statement-returns?${new URLSearchParams({ account_id: String(accountId), request_id: requestId })}`,
    { signal },
  );
}
export function statementExportHref(data: BrokerStatementReturn) {
  return `/api/broker-statement-returns/export?${new URLSearchParams({ account_id: String(data.account_id), request_id: data.sources[0].request_id, expected_fingerprint: data.material_fingerprint })}`;
}

/** String/BigInt presentation only; no binary float or client return calculation. */
export function formatStatementPercent(value: string | null): string {
  if (value === null || !/^-?\d+(\.\d+)?$/.test(value)) return "Недоступна";
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
  const digits = `${fraction}00000`;
  let hundredths = BigInt(whole) * 10000n + BigInt(digits.slice(0, 4));
  if (digits[4] >= "5") hundredths += 1n;
  return `${negative && hundredths !== 0n ? "−" : ""}${hundredths / 100n},${String(hundredths % 100n).padStart(2, "0")}%`;
}
export function statementMoney(value: string | null): string {
  if (value === null || !/^-?\d+$/.test(value)) return "Не подтверждено";
  const amount = BigInt(value);
  const absolute = amount < 0n ? -amount : amount;
  return `${amount < 0n ? "−" : ""}${String(absolute / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, " ")},${String(absolute % 100n).padStart(2, "0")} ₽`;
}
