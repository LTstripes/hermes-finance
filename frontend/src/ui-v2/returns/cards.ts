import { apiRequest } from "../../api/client";
import type { InstrumentMetric } from "../../api/sourceReturns";
import {
  type AccountLink,
  type Detail,
  detailMatchesContext,
  type Metric,
  type Period,
} from "./model";
import { validDetailPeriod, validIsin } from "./navigation";
import type { CouponIncome } from "./overall";

export type CleanInstrument = {
  isin: string;
  opening_date: string;
  closing_date: string;
  opening_value: InstrumentMetric<string>;
  closing_value: InstrumentMetric<string>;
  buys: InstrumentMetric<string>;
  sells: InstrumentMetric<string>;
  coupons: InstrumentMetric<string>;
  dividends: InstrumentMetric<string>;
  payouts: InstrumentMetric<string>;
  redemption: InstrumentMetric<string>;
  valuation_and_trades: InstrumentMetric<string>;
  known_result: InstrumentMetric<string>;
  pnl: InstrumentMetric<string>;
  modified_dietz: InstrumentMetric<string>;
};

export function cleanMetric(value: InstrumentMetric<string>, rate = false): Metric {
  return {
    value: value.value,
    unit: rate ? "fraction" : "kopecks",
    method: rate ? "modified_dietz" : "clean_instrument_return_v1",
    estimate: value.status !== "supported",
    reason_codes: [
      ...value.reason_codes,
      ...value.assumptions,
      ...(value.status === "partial" ? ["clean_partial_result"] : []),
    ],
  };
}

export type InstrumentCard = {
  contract_version: "returns_instrument_card_v2";
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
    valuation_date: string | null;
    account_link?: AccountLink | null;
    scope: string;
    label: string;
    canonical_account_id: number | null;
    period: Period | null;
    proof_status: "current" | "stale" | "absent" | "conflict";
    included: boolean;
    exclusion_reason: string | null;
    reason_codes: string[];
    detail: Detail | null;
    clean?: CleanInstrument | null;
  }[];
  reason_codes: string[];
};

/** Select one producer-owned account, never reuse another account's aggregate. */
export function selectCardScope(
  card: InstrumentCard,
  scope: string | null | undefined,
  start: string | null | undefined,
  end: string | null | undefined,
): { card: InstrumentCard | null; mismatch: boolean } {
  if (scope == null && start == null && end == null) return { card, mismatch: false };
  const matches = card.accounts.filter((account) => account.scope === scope);
  if (
    !scope ||
    matches.length !== 1 ||
    (start == null) !== (end == null) ||
    (start != null &&
      end != null &&
      (!validDetailPeriod({ start, end }) ||
        matches[0].period?.start !== start ||
        matches[0].period?.end !== end))
  )
    return { card: null, mismatch: true };
  const account = matches[0];
  const clean = account.clean;
  const empty = {
    ...card.summary.pnl,
    value: null,
    estimate: true,
    reason_codes: ["selected_components_incomplete"],
  };
  const metric = (key: keyof CleanInstrument): Metric => {
    const value = clean?.[key];
    return value && typeof value === "object" && "status" in value ? cleanMetric(value) : empty;
  };
  const quantity = account.detail?.closing_quantity ?? null;
  return {
    card: {
      ...card,
      accounts: [account],
      summary: {
        ...card.summary,
        quantity: {
          value: quantity,
          partial: true,
          reason_codes: quantity === null ? ["instrument_accounts_missing_or_excluded"] : [],
        },
        valuation_dates: account.valuation_date ? [account.valuation_date] : [],
        reported_value: metric("closing_value"),
        pnl:
          clean?.pnl.value !== null && clean?.pnl.value !== undefined
            ? metric("pnl")
            : metric("known_result"),
        coupons: metric("coupons"),
        dividends: metric("dividends"),
        valuation_and_trades: metric("valuation_and_trades"),
        redemption: metric("redemption"),
        costs: empty,
        taxes: empty,
        rate: clean ? cleanMetric(clean.modified_dietz, true) : { ...empty, unit: "fraction" },
        reason_codes: account.reason_codes,
      },
    },
    mismatch: false,
  };
}
export type IncomeKind = "coupon" | "dividend";
export type Income = {
  contract_version: "returns_income_v2";
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
    value.contract_version !== "returns_instrument_card_v2" ||
    value.isin !== isin ||
    value.accounts.some(
      (account) =>
        (account.clean &&
          (!validDetailPeriod(account.period) ||
            account.clean.isin !== isin ||
            account.clean.opening_date !== account.period.start ||
            account.clean.closing_date !== account.period.end)) ||
        (account.detail &&
          (!validDetailPeriod(account.period) ||
            !detailMatchesContext(account.detail, account.scope, account.period, isin))),
    )
  )
    throw new Error("Return card context mismatch");
  return value;
}
export async function getIncome(kind: IncomeKind, signal: AbortSignal) {
  const value = await apiRequest<Income>(`/api/returns/income?${new URLSearchParams({ kind })}`, {
    signal,
  });
  if (value.contract_version !== "returns_income_v2" || value.kind !== kind)
    throw new Error("Return income context mismatch");
  return value;
}
