import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import {
  analysisBreakdown,
  breakdownMatches,
  breakdownRows,
  type ReturnBreakdown,
} from "./breakdown";
import { detailFixture, m } from "./fixtures";
import { ReturnsBreakdown } from "./ReturnsBreakdown";

const fixture = (): ReturnBreakdown => ({
  payouts_kopecks: "1500",
  price_and_trades_kopecks: "-800",
  commissions_kopecks: "100",
  paid_nkd_kopecks: "200",
  taxes_kopecks: "0",
  other_kopecks: "0",
  total_kopecks: "400",
  complete: true,
});

test("payouts above the total reconcile exactly, including negative trades, fees and paid NKD", () => {
  const value = fixture();
  expect(breakdownMatches(value, m("400"))).toBe(true);
  expect(breakdownRows(value).map((row) => row.value)).toEqual(["1500", "-800", "-100", "-200"]);
  render(<ReturnsBreakdown value={value} total={m("400")} />);
  const region = within(screen.getByRole("region", { name: "Разложение результата" }));
  expect(region.getByText("Выплаты (купоны + дивиденды)")).toBeVisible();
  expect(region.getByText("+15 ₽")).toBeVisible();
  expect(region.getByText("+4 ₽")).toBeVisible();
  expect(region.queryByText(/недостаточно/)).toBeNull();
});

test("unknown costs stay empty, disclose incompleteness once and preserve the authoritative total", () => {
  const value = { ...fixture(), paid_nkd_kopecks: null, complete: false };
  expect(breakdownMatches(value, m("400"))).toBe(false);
  render(<ReturnsBreakdown value={value} total={m("400")} />);
  const region = within(screen.getByRole("region", { name: "Разложение результата" }));
  expect(region.getAllByText(/недостаточно/)).toHaveLength(1);
  expect(region.getByText("—")).toBeVisible();
  expect(region.getByText("+4 ₽")).toBeVisible();
});

test("even a one-kopeck mismatch is incomplete and never replaced with a balancing remainder", () => {
  expect(breakdownMatches({ ...fixture(), commissions_kopecks: "101" }, m("400"))).toBe(false);
  expect(breakdownMatches(fixture(), m("399"))).toBe(false);
  expect(breakdownMatches({ ...fixture(), total_kopecks: null }, m("400"))).toBe(false);
});

test("instrument components aggregate exact kopecks above Number precision and preserve unknown accounts", () => {
  const a = detailFixture().analysis;
  const b = detailFixture().analysis;
  const components = (value: string) =>
    Object.fromEntries(
      [
        ["payouts", value],
        ["price_and_trades", "-800"],
        ["commissions", "100"],
        ["paid_nkd", "200"],
        ["taxes", "0"],
      ].map(([name, amount]) => [
        name,
        { value: amount, status: "supported", reason_codes: [], assumptions: [] },
      ]),
    );
  Object.assign(a.components, components("90071992547409931500"));
  Object.assign(b.components, components("1500"));
  const total = m("90071992547409930800");
  const value = analysisBreakdown([a, b], total);
  expect(value.payouts_kopecks).toBe("90071992547409933000");
  expect(breakdownMatches(value, total)).toBe(true);
  expect(breakdownMatches({ ...value, commissions_kopecks: "201" }, total)).toBe(false);
  const unsupported = analysisBreakdown(
    [
      a,
      {
        ...b,
        components: { ...b.components, taxes: { ...b.components.taxes, status: "unavailable" } },
      },
    ],
    total,
  );
  expect(unsupported.taxes_kopecks).toBe("0");
  expect(breakdownMatches(unsupported, total)).toBe(false);
  const unknown = analysisBreakdown(
    [a, { ...b, components: { ...b.components, taxes: { ...b.components.taxes, value: null } } }],
    total,
  );
  expect(unknown.taxes_kopecks).toBeNull();
  expect(breakdownMatches(unknown, total)).toBe(false);
});
