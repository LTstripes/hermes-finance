import { type Period, validDate } from "./model";
import type { Overall, OverallInstrumentAccount } from "./overall";

/** Catalogue identities only; no names, amounts or source-scope guesses. */
export function canonicalId(value: unknown): number | null {
  if (typeof value !== "number" && (typeof value !== "string" || !/^[1-9]\d*$/.test(value)))
    return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
export function validIsin(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(value);
}
export function validDetailPeriod(period: Period | null): period is Period {
  return !!period && validDate(period.start) && validDate(period.end) && period.start < period.end;
}
function singleId(params: URLSearchParams, key: string) {
  return params.getAll(key).length === 1 ? canonicalId(params.get(key)) : null;
}
export function capitalInstrumentAccount(
  data: Overall,
  params: URLSearchParams,
): OverallInstrumentAccount | null {
  const id = singleId(params, "capital_account");
  const isin = params.getAll("isin").length === 1 ? params.get("isin") : null;
  if (
    id === null ||
    !validIsin(isin) ||
    params.has("gold_instrument") ||
    ["detail_scope", "detail_start", "detail_end"].some((key) => params.has(key))
  )
    return null;
  const groups = data.instruments.filter((instrument) => instrument.isin === isin);
  if (groups.length !== 1) return null;
  const matches = groups[0].accounts.filter(
    (account) =>
      typeof account.canonical_account_id === "number" &&
      canonicalId(account.canonical_account_id) === id,
  );
  if (matches.length !== 1 || !validDetailPeriod(matches[0].period)) return null;
  return matches[0];
}
export function capitalGoldSnapshot(data: Overall, params: URLSearchParams) {
  const account = singleId(params, "capital_account");
  const instrument = singleId(params, "gold_instrument");
  if (account === null || instrument === null || params.has("isin")) return null;
  const matches = data.gold.snapshots.filter(
    (snapshot) => snapshot.account_id === account && snapshot.instrument_id === instrument,
  );
  return matches.length === 1 ? matches[0] : null;
}
