import { describe, expect, it } from "vitest";

import {
  defaultMappingDraft,
  defaultMappingProvider,
  displayPriceDelta,
  formatMarketIdentity,
  identityToMoexDraft,
  MAPPING_SUPPORTED_TYPES,
  moexDraftToIdentity,
  quoteFailureGuidance,
  tInvestDraftToIdentity,
} from "./marketData";

describe("marketData helpers", () => {
  it("keeps local Hermes-down text distinct from T-Invest network failure", () => {
    const localDown =
      "Не удалось подключиться к локальному приложению. Проверь, что Hermes Finance запущен.";
    const providerDown = quoteFailureGuidance("provider_network");
    expect(providerDown).toContain("Внешний источник");
    expect(providerDown).not.toContain("не запущен");
    expect(providerDown).not.toBe(localDown);
    expect(quoteFailureGuidance("token_unavailable")).toContain("токен не настроен");
    expect(quoteFailureGuidance("token_unavailable")).not.toMatch(/t\.[A-Za-z0-9]/);
  });

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
        provider_instrument_id: "SBER",
        provider_venue_id: "stock/shares/TQBR",
      }),
    ).toBe("moex_iss · stock/shares · TQBR · SBER");
  });

  it("defaults new mappings to T-Invest and formats T-Invest without a venue", () => {
    expect(defaultMappingProvider(null)).toBe("t_invest");
    expect(
      tInvestDraftToIdentity({
        provider: "t_invest",
        providerInstrumentId: "11111111-1111-1111-1111-111111111111",
        isin: null,
      }),
    ).toEqual({
      provider: "t_invest",
      provider_instrument_id: "11111111-1111-1111-1111-111111111111",
      provider_venue_id: null,
    });
    expect(
      tInvestDraftToIdentity({
        provider: "t_invest",
        providerInstrumentId: "11111111-1111-1111-1111-111111111111",
        isin: "ru0009029540",
      }),
    ).toEqual({
      provider: "t_invest",
      provider_instrument_id: "11111111-1111-1111-1111-111111111111",
      provider_venue_id: null,
      isin: "RU0009029540",
    });
    expect(
      formatMarketIdentity({
        provider: "t_invest",
        provider_instrument_id: "11111111-1111-1111-1111-111111111111",
        provider_venue_id: null,
      }),
    ).toBe("T-Invest · 11111111-1111-1111-1111-111111111111");
  });

  it("formats a generic identity without assuming MOEX venue fields", () => {
    expect(
      formatMarketIdentity({
        provider: "synthetic_provider",
        provider_instrument_id: "opaque-security-id",
        provider_venue_id: null,
      }),
    ).toBe("synthetic_provider · opaque-security-id");
  });

  it("converts the MOEX form draft through one helper before save", () => {
    expect(
      moexDraftToIdentity({
        provider: "moex_iss",
        engine: "stock",
        market: "shares",
        boardid: "tqbr",
        secid: "sber",
      }),
    ).toEqual({
      provider: "moex_iss",
      provider_instrument_id: "SBER",
      provider_venue_id: "stock/shares/TQBR",
    });
    expect(
      identityToMoexDraft(
        {
          provider: "moex_iss",
          provider_instrument_id: "SBER",
          provider_venue_id: "stock/shares/TQBR",
        },
        "stock",
      ),
    ).toEqual({
      provider: "moex_iss",
      engine: "stock",
      market: "shares",
      boardid: "TQBR",
      secid: "SBER",
    });
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
