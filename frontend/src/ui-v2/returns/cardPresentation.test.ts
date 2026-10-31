import { expect, test } from "vitest";
import {
  cardContributions,
  cardHasCompleteBreakdown,
  cardOperations,
  cardQuantityStatus,
  contributionWidth,
  instrumentBackTarget,
} from "./cardPresentation";
import { instrumentCardFixture } from "./overallFixtures";

test("sold requires current known zero quantities on every account, not merely an eligible detail", () => {
  const card = instrumentCardFixture();
  card.summary.quantity.value = "0";
  for (const account of card.accounts) {
    if (!account.detail) throw new Error("missing synthetic detail");
    account.detail.closing_quantity = account.detail.analysis.closing.quantity = "0.000000";
    account.detail.analysis.coverage.quantity.complete = true;
    account.detail.analysis.closing.reason_codes = [];
  }
  expect(cardQuantityStatus(card)).toEqual({ partial: false, sold: true });
  card.summary.quantity.reason_codes = ["instrument_accounts_missing_or_excluded"];
  expect(cardQuantityStatus(card)).toEqual({ partial: true, sold: false });
  card.summary.quantity.reason_codes = [];
  if (!card.accounts[1].detail) throw new Error("missing synthetic detail");
  card.accounts[1].detail.closing_quantity = card.accounts[1].detail.analysis.closing.quantity =
    null;
  expect(cardQuantityStatus(card)).toEqual({ partial: true, sold: false });
});

test("exact breakdown requires the same fully known account set for P&L and every component", () => {
  const card = instrumentCardFixture();
  for (const account of card.accounts) {
    if (!account.detail) throw new Error("missing synthetic detail");
    account.detail.pnl.estimate = false;
    account.detail.analysis.pnl = {
      value: account.detail.pnl.value,
      status: "supported",
      reason_codes: [],
      assumptions: [],
    };
    for (const metric of Object.values(account.detail.analysis.components))
      Object.assign(metric, { value: "0", status: "supported", reason_codes: [], assumptions: [] });
    account.detail.analysis.components.valuation_and_trades.value = account.detail.pnl.value;
  }
  card.summary.valuation_and_trades.value = "800";
  card.summary.pnl.estimate = card.summary.valuation_and_trades.estimate = false;
  for (const metric of [
    card.summary.coupons,
    card.summary.dividends,
    card.summary.redemption,
    card.summary.costs,
    card.summary.taxes,
  ])
    Object.assign(metric, { value: "0", estimate: false });
  expect(cardHasCompleteBreakdown(card)).toBe(true);
  for (const account of card.accounts) {
    if (!account.detail || !account.period) throw new Error("missing synthetic detail");
    account.detail.pnl.estimate = true;
    account.detail.analysis.assumptions = ["source_only_xml_pdf"];
    account.detail.analysis.opening_date = account.period.start;
    account.detail.analysis.closing_date = account.period.end;
    for (const metric of [
      account.detail.analysis.pnl,
      ...Object.values(account.detail.analysis.components),
    ])
      Object.assign(metric, {
        status: "provisional",
        reason_codes: ["source_sections_not_financially_accepted"],
      });
  }
  expect(cardHasCompleteBreakdown(card)).toBe(true);
  if (!card.accounts[0].detail) throw new Error("missing synthetic detail");
  card.accounts[0].detail.analysis.assumptions = ["conditional_amount"];
  expect(cardHasCompleteBreakdown(card)).toBe(false);
  card.accounts[0].detail.analysis.assumptions = ["source_only_xml_pdf"];
  const partial = card.accounts[1].detail;
  if (!partial) throw new Error("missing synthetic detail");
  partial.analysis.pnl.value = partial.pnl.value = null;
  partial.analysis.components.coupons.value = "777";
  card.summary.pnl.value = "1200";
  card.summary.coupons.value = "777";
  expect(cardHasCompleteBreakdown(card)).toBe(false);
  expect(card.summary.pnl.value).toBe("1200");
  expect(partial.analysis.components.coupons.value).toBe("777");
});

test("Back retains local filters and rejects external, escaped and nested-card targets", () => {
  expect(instrumentBackTarget("/v2/returns?account=source%3ASYNTH-A&q=paper#instruments")).toBe(
    "/v2/returns?account=source%3ASYNTH-A&q=paper#instruments",
  );
  expect(
    instrumentBackTarget(
      "/v2/returns/account?scope=source%3ASYNTH-B&start=2030-04-30&end=2030-05-31",
    ),
  ).toContain("scope=source%3ASYNTH-B");
  expect(instrumentBackTarget("/v2/capital?month=2030-05")).toBe("/v2/capital?month=2030-05");
  for (const unsafe of [
    null,
    "https://example.test/v2/returns",
    "//example.test/v2/returns",
    "/\\example.test/v2/returns",
    "/v2/returns/instrument/RU000A000001",
    "/api/returns",
    "\n/v2/returns",
  ])
    expect(instrumentBackTarget(unsafe)).toBe("/v2/returns");
});

test("native trade rows retain account grain, exclude NKD cash legs, stale and mismatched rows", () => {
  const card = instrumentCardFixture();
  for (const account of card.accounts) {
    const original = account.detail?.analysis.events[0];
    if (!original || !account.detail) throw new Error("missing synthetic detail");
    const principal = {
      ...original,
      native_identity: "native-pair",
      effective_isin: card.isin,
      native_trade_amount_kopecks: "1234567890123456789",
      quantity_delta: "-7.500000",
    };
    account.detail.analysis.events = [
      principal,
      {
        ...principal,
        event_key: "nkd-only",
        native_identity: null,
        native_trade_amount_kopecks: null,
        quantity_delta: null,
      },
      { ...principal, event_key: "stale", current: false },
      { ...principal, event_key: "uncounted", counted: false },
      { ...principal, event_key: "foreign", effective_isin: "RU000A000099" },
      { ...principal, event_key: "wrong-sign", quantity_delta: "7.5" },
      { ...principal, event_key: "missing-quantity", quantity_delta: null },
    ];
  }
  const rows = cardOperations(card.accounts);
  expect(rows).toHaveLength(2);
  expect(new Set(rows.map((row) => row.key)).size).toBe(2);
  expect(rows.map((row) => row.scope)).toEqual(["source:SYNTH-A", "source:SYNTH-B"]);
  expect(rows[0]).toMatchObject({
    quantity: "7.500000",
    amount: "1234567890123456789",
    side: "SELL",
  });
});

test("component chart renders signed costs once and bounds geometry after exact BigInt ratio", () => {
  const { summary } = instrumentCardFixture();
  summary.costs.value = "50";
  summary.taxes.value = null;
  const rows = cardContributions(summary);
  expect(rows.find((row) => row.label === "Комиссии")?.value).toBe("-50");
  expect(rows.find((row) => row.label === "Учтённые налоги")).toBeUndefined();
  expect(summary.pnl.value).toBe("800");
  expect(summary.costs.value).toBe("50");
  expect(contributionWidth("900719925474099312345", 1801439850948198624690n)).toBe(50);
  expect(contributionWidth("-25", 100n)).toBe(25);
});
