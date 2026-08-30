import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatMoneyDelta,
  formatMonth,
  formatMonthKey,
  formatPercent,
  formatQuantity,
  formatRatio,
} from "./format";

describe("formatMoney", () => {
  it("groups thousands with non-breaking spaces and ruble sign", () => {
    expect(formatMoney("1234567")).toBe("1\u00a0234\u00a0567\u00a0₽");
  });

  it("keeps two fraction digits when present", () => {
    expect(formatMoney("1234.5")).toBe("1\u00a0234,50\u00a0₽");
    expect(formatMoney("86.42")).toBe("86,42\u00a0₽");
  });

  it("renders negative with minus and empty as dash", () => {
    expect(formatMoney("-48200")).toBe("−48\u00a0200\u00a0₽");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("not-a-number")).toBe("—");
  });
});

describe("formatMoneyDelta", () => {
  it("prefixes positive deltas with plus", () => {
    expect(formatMoneyDelta("1200")).toBe("+1\u00a0200\u00a0₽");
    expect(formatMoneyDelta("-48200")).toBe("−48\u00a0200\u00a0₽");
  });
});

describe("formatPercent", () => {
  it("formats with comma decimal and optional sign", () => {
    expect(formatPercent("2.4")).toBe("2,4%");
    expect(formatPercent("2.45", { digits: 2, signed: true })).toBe("+2,45%");
    expect(formatPercent("-1.2", { signed: true })).toBe("−1,2%");
  });
});

describe("formatDate", () => {
  it("formats ISO dates as DD.MM.YYYY", () => {
    expect(formatDate("2026-07-31")).toBe("31.07.2026");
    expect(formatDate(new Date(2026, 5, 30))).toBe("30.06.2026");
    expect(formatDate("")).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("keeps the UTC clock from the ISO timestamp", () => {
    expect(formatDateTime("2026-08-21T11:00:00+00:00")).toBe("21.08.2026\u00a011:00\u00a0UTC");
    expect(formatDateTime("2026-08-10")).toBe("10.08.2026");
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("formatMonth", () => {
  it("returns Russian month labels", () => {
    expect(formatMonth(2026, 7)).toBe("Июль\u00a02026");
    expect(formatMonthKey("2026-05")).toBe("Май\u00a02026");
    expect(formatMonthKey("bad")).toBe("—");
  });
});

describe("formatRatio", () => {
  it("formats coverage multipliers", () => {
    expect(formatRatio("0.68")).toBe("0,68×");
    expect(formatRatio(1)).toBe("1,00×");
  });
});

describe("formatQuantity", () => {
  it("groups the integer part and trims meaningless fractional zeroes", () => {
    expect(formatQuantity("64.000000")).toBe("64");
    expect(formatQuantity("1234567.500000")).toBe("1\u00a0234\u00a0567,5");
  });

  it("accepts comma input without using binary float conversion", () => {
    expect(formatQuantity("00012,3400")).toBe("12,34");
    expect(formatQuantity("-1")).toBe("—");
  });
});
