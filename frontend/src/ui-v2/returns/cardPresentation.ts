import type { InstrumentEvent } from "../../api/sourceReturns";
import type { InstrumentCard } from "./cards";
import { compareDecimal, type Metric, validDate } from "./model";

/** Back targets are local product pages; never navigate to a supplied external URL. */
export function instrumentBackTarget(value: string | null): string {
  if (!value || value.includes("\\") || [...value].some((letter) => letter.charCodeAt(0) < 32))
    return "/v2/returns";
  try {
    const url = new URL(value, "http://local.invalid");
    if (
      url.origin !== "http://local.invalid" ||
      !/^\/v2\/(?:returns(?:\/account)?|capital)$/.test(url.pathname)
    )
      return "/v2/returns";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/v2/returns";
  }
}

const integer = (value: string | null): value is string => value !== null && /^-?\d+$/.test(value);
export const hasAmount = (metric: Metric) => integer(metric.value);
export const nonzeroAmount = (metric: Metric) =>
  integer(metric.value) && BigInt(metric.value) !== 0n;

const zeroQuantity = (value: string | null) => value !== null && /^0(?:\.0+)?$/.test(value);
const knownQuantity = (value: string | null) => value !== null && /^\d+(?:\.\d+)?$/.test(value);
const quantityMetadata = new Set([
  "known_instrument_accounts_only",
  "instrument_account_valuation_dates_differ",
]);
/** An eligible detail is not evidence of a known closing quantity. */
export function cardQuantityStatus(card: InstrumentCard) {
  const partial =
    card.accounts.length === 0 ||
    !knownQuantity(card.summary.quantity.value) ||
    card.summary.quantity.reason_codes.some((code) => !quantityMetadata.has(code)) ||
    card.accounts.some(
      (account) =>
        !account.included ||
        account.proof_status !== "current" ||
        !account.detail ||
        !knownQuantity(account.detail.closing_quantity) ||
        !knownQuantity(account.detail.analysis.closing.quantity) ||
        !account.detail.analysis.coverage.quantity.complete ||
        compareDecimal(
          account.detail.closing_quantity ?? "",
          account.detail.analysis.closing.quantity ?? "",
        ) !== 0,
    );
  const sold =
    !partial &&
    zeroQuantity(card.summary.quantity.value) &&
    card.accounts.every(
      (account) =>
        account.detail &&
        zeroQuantity(account.detail.closing_quantity) &&
        zeroQuantity(account.detail.analysis.closing.quantity) &&
        account.detail.analysis.coverage.quantity.complete &&
        account.detail.analysis.closing.reason_codes.length === 0,
    );
  return { partial, sold };
}

const bridgeComponents = [
  "valuation_and_trades",
  "coupons",
  "dividends",
  "redemption",
  "fees",
  "taxes",
] as const;
const authorityOnly = (codes: string[]) =>
  codes.every((code) => code === "source_sections_not_financially_accepted");
/** Completeness of account operands only; all financial values remain producer-owned. */
export function cardHasCompleteBreakdown(card: InstrumentCard) {
  const summary = card.summary;
  if (
    !card.accounts.length ||
    [
      summary.pnl,
      summary.valuation_and_trades,
      summary.coupons,
      summary.dividends,
      summary.redemption,
      summary.costs,
      summary.taxes,
    ].some((metric) => !hasAmount(metric) || metric.estimate || !authorityOnly(metric.reason_codes))
  )
    return false;
  return card.accounts.every((account) => {
    const detail = account.detail;
    const sourceOnlyEstimate =
      !!detail &&
      !!account.period &&
      detail.analysis.contract_version === "instrument_return_v2" &&
      detail.analysis.opening_date === account.period.start &&
      detail.analysis.closing_date === account.period.end &&
      detail.analysis.assumptions.length === 1 &&
      detail.analysis.assumptions[0] === "source_only_xml_pdf";
    if (
      !account.included ||
      account.proof_status !== "current" ||
      !detail ||
      !hasAmount(detail.pnl) ||
      (detail.pnl.estimate && !sourceOnlyEstimate) ||
      detail.pnl.value !== detail.analysis.pnl.value
    )
      return false;
    return [
      detail.analysis.pnl,
      ...bridgeComponents.map((key) => detail.analysis.components[key]),
    ].every(
      (metric) =>
        integer(metric.value) &&
        (metric.status === "supported" || metric.status === "provisional") &&
        authorityOnly(metric.reason_codes) &&
        metric.assumptions.length === 0,
    );
  });
}

export type CardOperation = {
  key: string;
  account: string;
  scope: string;
  date: string;
  side: "BUY" | "SELL";
  quantity: string;
  amount: string;
};

/** Cash-only BUY/SELL components (including NKD) are not additional trades. */
export function cardOperations(accounts: InstrumentCard["accounts"]): CardOperation[] {
  return accounts
    .flatMap((account) =>
      (account.detail?.analysis.events ?? []).flatMap((event: InstrumentEvent<string>) => {
        if (
          !event.current ||
          !event.counted ||
          (event.kind !== "BUY" && event.kind !== "SELL") ||
          !event.native_identity ||
          !event.event_date ||
          !validDate(event.event_date) ||
          event.effective_isin !== account.detail?.isin ||
          !event.quantity_delta ||
          !/^-?\d+(?:\.\d+)?$/.test(event.quantity_delta) ||
          /^-?0(?:\.0+)?$/.test(event.quantity_delta) ||
          !integer(event.native_trade_amount_kopecks) ||
          BigInt(event.native_trade_amount_kopecks) < 0n ||
          (event.kind === "BUY" && event.quantity_delta.startsWith("-")) ||
          (event.kind === "SELL" && !event.quantity_delta.startsWith("-"))
        )
          return [];
        return [
          {
            key: `${account.scope}/${event.event_key}`,
            account: account.label,
            scope: account.scope,
            date: event.event_date,
            side: event.kind,
            quantity: event.quantity_delta.replace(/^-/, ""),
            amount: event.native_trade_amount_kopecks,
          },
        ];
      }),
    )
    .sort((a, b) => b.date.localeCompare(a.date) || a.key.localeCompare(b.key));
}

/** Only geometry uses Number, after the exact monetary ratio is bounded. */
export function contributionWidth(value: string, maximum: bigint): number {
  if (!integer(value) || maximum <= 0n) return 0;
  const amount = BigInt(value);
  const magnitude = amount < 0n ? -amount : amount;
  return Number((magnitude * 10000n) / maximum) / 100;
}

export function cardContributions(summary: InstrumentCard["summary"]) {
  return [
    { label: "Стоимость и сделки", metric: summary.valuation_and_trades, subtract: false },
    { label: "Купоны", metric: summary.coupons, subtract: false },
    { label: "Дивиденды", metric: summary.dividends, subtract: false },
    { label: "Погашения", metric: summary.redemption, subtract: false },
    { label: "Комиссии", metric: summary.costs, subtract: true },
    { label: "Учтённые налоги", metric: summary.taxes, subtract: true },
  ]
    .filter((row) => nonzeroAmount(row.metric))
    .map((row) => ({
      ...row,
      // Display the already-authoritative cost as an outgoing contribution, once.
      value: String(BigInt(row.metric.value as string) * (row.subtract ? -1n : 1n)),
    }));
}
