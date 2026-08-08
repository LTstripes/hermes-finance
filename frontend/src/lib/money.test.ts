import { describe, expect, it } from "vitest";

import { isBlankMoney, normalizeMoneyInput, rub } from "./money";

describe("normalizeMoneyInput", () => {
  it("accepts integers and decimals with comma", () => {
    expect(normalizeMoneyInput("200000")).toBe("200000.00");
    expect(normalizeMoneyInput("174000,5")).toBe("174000.50");
    expect(normalizeMoneyInput(" 1 234,00 ")).toBe("1234.00");
  });

  it("rejects garbage and blank", () => {
    expect(normalizeMoneyInput("")).toBeNull();
    expect(normalizeMoneyInput("abc")).toBeNull();
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
