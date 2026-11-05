import { expect, test } from "vitest";
import {
  brokerageResult,
  compactQuantity,
  instrumentSummary,
  knownMoney,
  selectedIncome,
} from "./dashboard";
import { m } from "./fixtures";
import { overallFixture } from "./overallFixtures";

test("money projection is exact above JS safe range and preserves source authority/reasons", () => {
  const total = knownMoney([
    { ...m("9007199254740993123"), reason_codes: ["source_only"] },
    m("-9007199254740993000"),
    m(null),
  ]);
  expect(total.value).toBe("123");
  expect(total.estimate).toBe(true);
  expect(total.reason_codes).toEqual([
    "source_only",
    "missing_endpoint",
    "selected_components_incomplete",
  ]);
  expect(knownMoney([m(null)]).value).toBeNull();
  expect(knownMoney([m("0")]).value).toBe("0");
});
test("brokerage headline keeps different periods separate and excludes gold/deposit", () => {
  const data = overallFixture();
  data.mixed_result.components.push({
    ...data.mixed_result.components[2],
    category: "deposits",
    included: true,
    amount: m("999999"),
  });
  expect(brokerageResult(data, "all").amount.value).toBeNull();
  expect(brokerageResult(data, "source:SYNTH-B").amount.value).toBe("-400");
});
test("instrument and income remain known if current account P&L is unavailable", () => {
  const data = overallFixture();
  data.mixed_result.components[0].included = false;
  data.mixed_result.components[0].amount = m(null);
  expect(instrumentSummary(data, data.instruments[0], "source:SYNTH-A").pnl.value).toBe("1200");
  expect(selectedIncome(data, "source:SYNTH-A", "coupon").known_total.value).toBe("3500");
});
test("a stale sibling is excluded independently and never creates a common rate", () => {
  const data = overallFixture();
  data.source_accounts[1].proof_status = "stale";
  const summary = instrumentSummary(data, data.instruments[0], "all");
  expect(summary.pnl.value).toBe("1200");
  expect(summary.partial).toBe(true);
  expect(summary.pnl.reason_codes).toContain("selected_components_incomplete");
  expect(summary.rate.value).toBeNull();
});
test("explicit mapping conflict excludes instrument numbers despite a current proof", () => {
  const data = overallFixture();
  data.mixed_result.components[0].coverage.status = "conflict";
  expect(instrumentSummary(data, data.instruments[0], "source:SYNTH-A").pnl.value).toBeNull();
});
test("a supported native period remains visible for one source despite stale proof or mapping conflict", () => {
  const data = overallFixture();
  data.source_accounts[0].proof_status = "stale";
  const account = data.instruments[0].accounts[0];
  account.native_period = true;
  let summary = instrumentSummary(data, data.instruments[0], "source:SYNTH-A");
  expect(summary.pnl.value).toBe("1200");
  expect(summary.accounts[0].resultAvailable).toBe(true);
  account.details_loaded = false;
  expect(instrumentSummary(data, data.instruments[0], "source:SYNTH-A").pnl.value).toBeNull();
  account.details_loaded = true;
  data.mixed_result.components[0].coverage.status = "conflict";
  summary = instrumentSummary(data, data.instruments[0], "source:SYNTH-A");
  expect(summary.pnl.value).toBe("1200");
  expect(summary.accounts[0].resultAvailable).toBe(true);
});
test("decimal quantity formatting changes no significant digits", () => {
  expect(compactQuantity("100.000000")).toBe("100");
  expect(compactQuantity("0.0001200")).toBe("0.00012");
  expect(compactQuantity("0")).toBe("0");
});

test("explicit IIS and brokerage categories both retain their eligible source result", () => {
  const data = overallFixture();
  data.mixed_result.components[0].category = "iis";
  data.mixed_result.components[1].category = "brokerage";
  expect(brokerageResult(data, "all").amount.value).toBeNull();
  expect(brokerageResult(data, "source:SYNTH-A").amount.value).toBe("1200");
  expect(brokerageResult(data, "source:SYNTH-B").amount.value).toBe("-400");
});
