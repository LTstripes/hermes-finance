import { describe, expect, it } from "vitest";

import {
  fromKopecks,
  isBlankMoney,
  moneySharePercent,
  moneyToChartNumber,
  normalizeMoneyInput,
  rub,
  sumMoneyAmounts,
  toKopecks,
} from "./money";

describe("normalizeMoneyInput", () => {
  it("accepts integers and decimals with comma", () => {
    expect(normalizeMoneyInput("200000")).toBe("200000.00");
    expect(normalizeMoneyInput("174000,5")).toBe("174000.50");
    expect(normalizeMoneyInput(" 1 234,00 ")).toBe("1234.00");
  });

  it("rejects garbage and blank", () => {
    expect(normalizeMoneyInput("")).toBeNull();
    expect(normalizeMoneyInput("abc")).toBeNull();
    expect(normalizeMoneyInput("123x45")).toBeNull();
  });
});

describe("rub", () => {
  it("builds MoneyValue", () => {
    expect(rub("200000.00")).toEqual({ amount: "200000.00", currency: "RUB" });
  });
});

describe("isBlankMoney", () => {
  it("treats empty and zero as blank", () => {
    expect(isBlankMoney("")).toBe(true);
    expect(isBlankMoney("0")).toBe(true);
    expect(isBlankMoney("10")).toBe(false);
  });
});

describe("exact money kopecks", () => {
  it("round-trips large positive and negative values", () => {
    const amount = "123456789012345.67";
    expect(fromKopecks(toKopecks(amount))).toBe(amount);
    expect(fromKopecks(toKopecks(`-${amount}`))).toBe(`-${amount}`);
  });

  it("rejects invalid values instead of producing NaN", () => {
    expect(() => toKopecks("123x45")).toThrow("invalid money amount");
  });
});

describe("sumMoneyAmounts", () => {
  it("sums exact kopecks without decimal float drift", () => {
    expect(sumMoneyAmounts(["100.50", "0.50", "2"])).toBe("103.00");
    expect(sumMoneyAmounts(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoneyAmounts(["10.00", "-3.25", "0.05"])).toBe("6.80");
  });

  it("remains exact above Number.MAX_SAFE_INTEGER kopecks", () => {
    expect(toKopecks("90071992547409.93")).toBe(9007199254740993n);
    expect(sumMoneyAmounts(["90071992547409.93", "0.01"])).toBe("90071992547409.94");
  });

  it("keeps blank/invalid optional entries backward-compatible", () => {
    expect(sumMoneyAmounts([null, undefined, "", "not-money"])).toBe("0.00");
  });
});

describe("moneySharePercent", () => {
  it("uses exact bigint division with HALF_UP display rounding", () => {
    expect(moneySharePercent("1.00", "3.00", 1)).toBe("33.3");
    expect(moneySharePercent("2.00", "3.00", 2)).toBe("66.67");
    expect(moneySharePercent("90071992547409.93", "180143985094819.86", 1)).toBe("50.0");
  });
});

describe("moneyToChartNumber", () => {
  it("converts only at the deliberate chart boundary", () => {
    expect(moneyToChartNumber("1234.56")).toBe(1234.56);
  });
});
