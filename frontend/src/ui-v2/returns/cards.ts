import { apiRequest } from "../../api/client";
import { type Detail, type Metric, type Period, detailMatchesContext } from "./model";
import { validDetailPeriod, validIsin } from "./navigation";
import type { CouponIncome } from "./overall";

export type InstrumentCard = {
  contract_version: "returns_instrument_card_v1";
  isin: string;
  name: string;
  kind: string | null;
  summary: {
    quantity: { value: string | null; partial: true; reason_codes: string[] };
    reported_value: Metric;
    valuation_dates: string[];
    pnl: Metric;
    coupons: Metric;
    dividends: Metric;
    valuation_and_trades: Metric;
    redemption: Metric;
    costs: Metric;
    taxes: Metric;
    rate: Metric;
    partial: true;
    reason_codes: string[];
  };
  accounts: {
    scope: string;
    label: string;
    canonical_account_id: number | null;
    period: Period | null;
    proof_status: "current" | "stale" | "absent" | "conflict";
    included: boolean;
    exclusion_reason: string | null;
    reason_codes: string[];
    detail: Detail | null;
  }[];
  reason_codes: string[];
};
export type IncomeKind = "coupon" | "dividend";
export type Income = {
  contract_version: "returns_income_v1";
  kind: IncomeKind;
  summary: CouponIncome;
  instruments: {
    isin: string;
    name: string;
    amount: Metric;
    accounts: { scope: string; label: string; period: Period | null; amount: Metric }[];
  }[];
  events: {
    scope: string;
    label: string;
    isin: string | null;
    name: string | null;
    date: string;
    amount: Metric;
  }[];
  reason_codes: string[];
};
export async function getInstrumentCard(isin: string, signal: AbortSignal) {
  if (!validIsin(isin)) throw new Error("Invalid instrument identity");
  const value = await apiRequest<InstrumentCard>(
    `/api/returns/instrument-card?${new URLSearchParams({ isin })}`,
    { signal },
  );
  if (
    value.contract_version !== "returns_instrument_card_v1" ||
    value.isin !== isin ||
    value.accounts.some(
      (account) =>
        account.detail &&
        (!validDetailPeriod(account.period) ||
          !detailMatchesContext(account.detail, account.scope, account.period, isin)),
    )
  )
    throw new Error("Return card context mismatch");
  return value;
}
export async function getIncome(kind: IncomeKind, signal: AbortSignal) {
  const value = await apiRequest<Income>(`/api/returns/income?${new URLSearchParams({ kind })}`, {
    signal,
  });
  if (value.contract_version !== "returns_income_v1" || value.kind !== kind)
    throw new Error("Return income context mismatch");
  return value;
}
