import { apiRequest } from "../../api/client";
import { formatMoneyDelta, formatMoney } from "../../lib/format";
import { fromKopecks } from "../../lib/money";
import { formatSourceReturnRate } from "../../lib/sourceReturnFormat";

export type Period = { start: string; end: string };
export type Metric = {
  value: string | null;
  reason_codes: string[];
  method: string;
  unit: "kopecks" | "fraction" | "percentage_points";
  estimate: boolean;
};
export type Result = {
  period: Period;
  pnl: Metric;
  rate: Metric;
  coupons: Metric;
  dividends: Metric;
};
export type Instrument = Omit<Result, "period"> & {
  isin: string;
  name: string;
  kind: string | null;
  period: Period;
  conditional: boolean;
};
export type Context = {
  source_periods: Record<string, Period[]>;
  accounts: { id: string; label: string; basis: "statements" | "accepted" }[];
  default_period: Period | null;
  closed_periods: Period[];
};
export type Overview = {
  scope: string;
  selected: Result;
  all_history: Result | null;
  history: Result[];
  periods: Period[];
  instruments: Instrument[];
  instrument_reason_codes: string[];
  proof_status: string;
};
export type Detail = Instrument & {
  scope: string;
  opening_quantity: string | null;
  closing_quantity: string | null;
  buys: Metric;
  sells: Metric;
  conditional_pnl: Metric;
  conditional_rate: Metric;
  reason_codes: string[];
  events: {
    ordinal: number;
    kind: string;
    date: string | null;
    cash_date: string | null;
    quantity_date: string | null;
    quantity: string | null;
    amount: Metric;
    counted: boolean;
  }[];
};
export const unavailable: Metric = {
  value: null,
  reason_codes: [],
  method: "",
  unit: "kopecks",
  estimate: false,
};
export const periodKey = (p: Period) => `${p.start}/${p.end}`;
export const samePeriod = (a: Period, b: Period) => periodKey(a) === periodKey(b);
export function validDate(value: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  );
}
export const dateLabel = (s: string) => s.split("-").reverse().join(".");
export const periodLabel = (p: Period) => `${dateLabel(p.start)} — ${dateLabel(p.end)}`;
export const monthLabel = (p: Period) =>
  new Intl.DateTimeFormat("ru-RU", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${p.end}T00:00:00Z`));

function decimal(value: string) {
  const m = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(value);
  if (!m) return null;
  const places = (m[3]?.length ?? 0) - Number(m[4] ?? 0);
  return { n: BigInt(`${m[1]}${m[2]}${m[3] ?? ""}`), places };
}
/** Exact ordering only, never a return calculation. */
export function compareDecimal(a: string, b: string) {
  const x = decimal(a);
  const y = decimal(b);
  if (!x || !y) return 0;
  const places = Math.max(x.places, y.places);
  const left = x.n * 10n ** BigInt(places - x.places);
  const right = y.n * 10n ** BigInt(places - y.places);
  return left < right ? -1 : left > right ? 1 : 0;
}
export function displayMetric(m: Metric, signed = false) {
  if (m.value == null || !decimal(m.value)) return "—";
  if (m.unit !== "kopecks") return formatSourceReturnRate(m.value, m.unit === "fraction");
  if (!/^-?\d+$/.test(m.value)) return "—";
  return (signed ? formatMoneyDelta : formatMoney)(fromKopecks(BigInt(m.value)));
}
export function ranked(
  rows: Instrument[],
  period: Period,
  mode: "pnl" | "rate",
  positive: boolean,
) {
  const method = mode === "pnl" ? "instrument_return_v2" : "modified_dietz";
  return rows
    .filter(
      (r) =>
        samePeriod(r.period, period) &&
        r[mode].method === method &&
        r[mode].unit === (mode === "pnl" ? "kopecks" : "fraction") &&
        r[mode].value != null &&
        decimal(r[mode].value) &&
        compareDecimal(r[mode].value, "0") === (positive ? 1 : -1),
    )
    .sort(
      (a, b) =>
        (positive ? -1 : 1) * compareDecimal(a[mode].value ?? "0", b[mode].value ?? "0") ||
        a.isin.localeCompare(b.isin),
    )
    .slice(0, 5);
}
export const getContext = (signal: AbortSignal) =>
  apiRequest<Context>("/api/returns/context", { signal });
function query(scope: string, period: Period) {
  return new URLSearchParams({ scope, ...period });
}
export async function getOverview(scope: string, period: Period, signal: AbortSignal) {
  const value = await apiRequest<Overview>(`/api/returns/overview?${query(scope, period)}`, {
    signal,
  });
  if (
    value.scope !== scope ||
    !samePeriod(value.selected.period, period) ||
    value.instruments.some((r) => !samePeriod(r.period, period))
  )
    throw new Error("Return context mismatch");
  return value;
}
export async function getDetail(scope: string, period: Period, isin: string, signal: AbortSignal) {
  const params = query(scope, period);
  params.set("isin", isin);
  const value = await apiRequest<Detail>(`/api/returns/instrument?${params}`, { signal });
  if (value.scope !== scope || value.isin !== isin || !samePeriod(value.period, period))
    throw new Error("Return context mismatch");
  return value;
}
