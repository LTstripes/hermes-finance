import { describe, expect, it } from "vitest";

import {
  defaultMappingDraft,
  displayPriceDelta,
  formatMarketIdentity,
  MAPPING_SUPPORTED_TYPES,
} from "./marketData";

describe("marketData helpers", () => {
  it("defaults bond drafts to the bonds market and others to shares", () => {
    expect(defaultMappingDraft("bond")).toMatchObject({
      provider: "moex_iss",
      engine: "stock",
      market: "bonds",
      boardid: "",
      secid: "",
    });
    expect(defaultMappingDraft("stock").market).toBe("shares");
    expect(defaultMappingDraft("fund").market).toBe("shares");
  });

  it("treats only stock, bond and fund as mapping-supported", () => {
    expect(MAPPING_SUPPORTED_TYPES.has("stock")).toBe(true);
    expect(MAPPING_SUPPORTED_TYPES.has("gold")).toBe(false);
  });

  it("formats a canonical identity without using legacy moex_secid", () => {
    expect(
      formatMarketIdentity({
        provider: "moex_iss",
        engine: "stock",
        market: "shares",
        boardid: "TQBR",
        secid: "SBER",
      }),
    ).toBe("moex_iss · stock/shares · TQBR · SBER");
  });

  it("computes a display-only money delta from backend decimal strings", () => {
    expect(
      displayPriceDelta(
        { amount: "200.00", currency: "RUB" },
        { amount: "215.50", currency: "RUB" },
      ),
    ).toMatch(/\+15,50/);
    expect(
      displayPriceDelta(
        { amount: "200.00", currency: "RUB" },
        { amount: "180.00", currency: "RUB" },
      ),
    ).toMatch(/−20/);
    expect(displayPriceDelta({ amount: "200.00", currency: "RUB" }, null)).toBeNull();
  });
});
