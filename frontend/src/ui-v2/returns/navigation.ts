import { type Period, validDate } from "./model";
import type { GoldTarget, Overall } from "./overall";

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
/** Metadata grants entry only; it carries no valuation or accepted financial authority. */
export function goldTargets(data: Overall): GoldTarget[] {
  const pairs = new Map<string, GoldTarget>();
  for (const target of [...(data.gold.targets ?? []), ...(data.gold.histories ?? [])]) {
    if (canonicalId(target.account_id) === null || canonicalId(target.instrument_id) === null)
      continue;
    const key = `${target.account_id}/${target.instrument_id}`;
    if (!pairs.has(key))
      pairs.set(key, {
        account_id: target.account_id,
        instrument_id: target.instrument_id,
        label: target.label,
      });
  }
  return [...pairs.values()];
}
export function capitalGoldTarget(data: Overall, params: URLSearchParams) {
  const account = singleId(params, "capital_account");
  const instrument = singleId(params, "gold_instrument");
  if (account === null || instrument === null || params.has("isin")) return null;
  return (
    goldTargets(data).find(
      (target) => target.account_id === account && target.instrument_id === instrument,
    ) ?? null
  );
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

export function capitalGoldHistorySummary(data: Overall, params: URLSearchParams) {
  const account = singleId(params, "capital_account");
  const instrument = singleId(params, "gold_instrument");
  if (account === null || instrument === null || params.has("isin")) return null;
  const matches = (data.gold.histories ?? []).filter(
    (history) => history.account_id === account && history.instrument_id === instrument,
  );
  return matches.length === 1 ? matches[0] : null;
}
