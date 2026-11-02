import { Navigate, useLocation } from "react-router";
import { validDate, type Period } from "./model";

export function legacyMonthPeriod(value: string): Period | null {
  if (!/^\d{4}-\d{2}(?:-01)?$/.test(value)) return null;
  const first = `${value.slice(0, 7)}-01`;
  if (!validDate(first)) return null;
  const d = new Date(`${first}T00:00:00Z`);
  const start = new Date(d.getTime() - 86400000).toISOString().slice(0, 10);
  d.setUTCMonth(d.getUTCMonth() + 1);
  return { start, end: new Date(d.getTime() - 86400000).toISOString().slice(0, 10) };
}

/** Translate retired selection keys; repeated identities still reach the validators. */
export function legacyReturnsHref(search: string, hash: string) {
  const params = new URLSearchParams(search);
  const accounts = params.getAll("account_id");
  if (accounts.length && params.getAll("scope").length === 1 && params.get("scope") === "account")
    params.delete("scope");
  for (const account of params.getAll("source_account"))
    params.append("scope", `source:${account}`);
  for (const account of accounts) params.append("scope", `account:${account}`);
  for (const isin of params.getAll("bond_isin")) params.append("isin", isin);
  const periods = params.getAll("bond_period");
  if (periods.length === 1) {
    const period = legacyMonthPeriod(periods[0]);
    if (period && !params.has("start") && !params.has("end")) {
      params.set("start", period.start);
      params.set("end", period.end);
    }
    if (periods[0] === "history") params.set("period", "history");
  } else if (!periods.length && (params.has("source_account") || hash === "#bond-slice")) {
    if (!params.has("start") && !params.has("end")) params.set("period", "history");
  }
  for (const key of ["source_account", "account_id", "bond_isin", "bond_period", "diagnostics"])
    params.delete(key);
  const query = params.toString();
  const anchor = hash === "#bond-slice" ? "#returns-instruments" : hash;
  const detail = ["scope", "start", "end", "period", "month", "categories"].some((key) =>
    params.has(key),
  );
  return `/v2/returns${detail ? "/account" : ""}${query ? `?${query}` : ""}${anchor}`;
}

export function ReturnsLegacyRedirect() {
  const { search, hash } = useLocation();
  return <Navigate replace to={legacyReturnsHref(search, hash)} />;
}
