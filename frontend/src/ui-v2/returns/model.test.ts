import { expect, test } from "vitest";
import { april, m, may, overviewFixture, row } from "./fixtures";
import { compareDecimal, displayMetric, ranked } from "./model";

test("Decimal ranks preserve sub-double differences, signed exponents and large minor units", () => {
  expect(compareDecimal("0.10000000000000000001", "0.10000000000000000002")).toBe(-1);
  expect(compareDecimal("-0.000000000001", "-1e-13")).toBe(-1);
  expect(compareDecimal("1e2", "100.000")).toBe(0);
  expect(displayMetric(m("900719925474099301"))).toBe(
    "9\u00a0007\u00a0199\u00a0254\u00a0740\u00a0993,01\u00a0₽",
  );
  expect(displayMetric(m("-0.00125", "fraction"))).toBe("−0,13%");
  expect(displayMetric(m("0", "fraction"))).toBe("0,00%");
});

test("tops exclude zeros, NULL, incompatible period, unit, method and conditional values", () => {
  const rows = overviewFixture().instruments;
  rows.push(row("RU000A000006", "Other month", "999999999", "99", april));
  rows.push({
    ...row("RU000A000007", "Legacy", "999999999", "99"),
    rate: m("99", "percentage_points", "legacy"),
  });
  expect(ranked(rows, may, "rate", true).map((r) => r.isin)).toEqual([
    "RU000A000002",
    "RU000A000001",
  ]);
  expect(ranked(rows, may, "pnl", false).map((r) => r.isin)).toEqual(["RU000A000003"]);
  expect(ranked(rows.slice(0, 5), may, "pnl", true)).toHaveLength(2);
  expect(
    ranked([row("RU000A000008", "negative zero", "0", "-0.0")], may, "rate", false),
  ).toHaveLength(0);
});
