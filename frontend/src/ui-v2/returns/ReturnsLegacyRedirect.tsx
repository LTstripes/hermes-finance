import { Navigate, useLocation } from "react-router";
import { validDate, type Period } from "./model";

function monthsPeriod(value: string): Period | null {
  const first = `${value.slice(0, 7)}-01`;
  if (!validDate(first)) return null;
  const d = new Date(`${first}T00:00:00Z`);
  const start = new Date(d.getTime() - 86400000).toISOString().slice(0, 10);
  d.setUTCMonth(d.getUTCMonth() + 1);
  return { start, end: new Date(d.getTime() - 86400000).toISOString().slice(0, 10) };
}

/** Old links select the same ordinary screen; explicit diagnostics remain available. */
export function ReturnsLegacyRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const account = params.get("source_account");
  if (account) params.set("scope", `source:${account}`);
  const oldPeriod = params.get("bond_period") ?? "history";
  if (oldPeriod === "history") params.set("period", "history");
  const isin = params.get("bond_isin");
  if (isin) params.set("isin", isin);
  const period = oldPeriod ? monthsPeriod(oldPeriod) : null;
  if (period) {
    params.set("start", period.start);
    params.set("end", period.end);
  }
  params.delete("source_account");
  params.delete("bond_period");
  params.delete("bond_isin");
  return (
    <Navigate
      replace
      to={`/v2/returns/account?${params}${location.hash === "#bond-slice" ? "#returns-instruments" : ""}`}
    />
  );
}
