import type { MarketIdentity, MarketIdentityWrite, MoneyValue } from "../api/types";
import { formatMoneyDelta } from "./format";
import { fromKopecks, toKopecks } from "./money";

export const MOEX_ISS_PROVIDER = "moex_iss";
export const T_INVEST_PROVIDER = "t_invest";

export const MAPPING_SUPPORTED_TYPES = new Set(["stock", "bond", "fund"]);

export const MAPPING_STATE_LABELS: Record<string, string> = {
  unmapped: "Не настроен",
  mapped: "Подключён",
  excluded: "Отключён",
};

export const QUOTE_PREVIEW_STATUS_LABELS: Record<string, string> = {
  ok: "Котировка получена",
  stale: "Котировка старая",
  unmapped: "Внешний источник не настроен",
  excluded: "Обновление отключено",
  unsupported: "Обновляется вручную",
  ambiguous: "Нельзя выбрать источник автоматически",
  unavailable: "Подходящей котировки нет",
  network_error: "Внешний источник временно недоступен",
  malformed_response: "Данные источника нельзя безопасно использовать",
};

export const QUOTE_FAILURE_REASON_GUIDANCE: Record<string, string> = {
  token_unavailable:
    "Автообновление котировок недоступно: read-only токен не настроен. Текущая цена не меняется. Можно ввести цену вручную в таблице позиций.",
  provider_network:
    "Внешний источник котировок временно недоступен. Локальное приложение Hermes Finance работает.",
  quote_unavailable: "Подходящей котировки нет. Текущая сохранённая цена не меняется.",
  unsupported: "Этот инструмент обновляется вручную. Текущая цена остаётся как есть.",
  malformed: "Ответ источника нельзя безопасно использовать. Текущая цена не меняется.",
  unmapped: "Внешний источник для этой позиции не настроен. Можно ввести цену вручную.",
  excluded: "Автообновление для этой позиции отключено. Можно ввести цену вручную.",
  ambiguous: "Нельзя автоматически выбрать источник. Текущая цена не меняется.",
};

export function quoteFailureGuidance(reason: string | null | undefined): string | null {
  if (!reason) {
    return null;
  }
  return QUOTE_FAILURE_REASON_GUIDANCE[reason] ?? null;
}

export type MappingProviderId = typeof T_INVEST_PROVIDER | typeof MOEX_ISS_PROVIDER;

export type MoexMappingDraft = {
  provider: string;
  engine: string;
  market: string;
  boardid: string;
  secid: string;
};

export type TInvestMappingDraft = {
  provider: typeof T_INVEST_PROVIDER;
  providerInstrumentId: string;
  isin: string | null;
};

export function mappingStateTone(state: string): "ok" | "draft" | "info" | "neutral" {
  if (state === "mapped") return "ok";
  if (state === "excluded") return "info";
  return "neutral";
}

export function quoteStatusTone(status: string): "ok" | "draft" | "closed" | "info" | "neutral" {
  if (status === "ok") return "ok";
  if (status === "stale" || status === "ambiguous") return "draft";
  if (status === "unmapped" || status === "excluded" || status === "unsupported") return "info";
  if (status === "unavailable" || status === "network_error" || status === "malformed_response") {
    return "closed";
  }
  return "neutral";
}

export function encodeMoexVenue(engine: string, market: string, boardid: string): string {
  const engineN = engine.trim().toLowerCase();
  const marketN = market.trim().toLowerCase();
  const boardidN = boardid.trim().toUpperCase();
  if (!engineN || !marketN || !boardidN) {
    throw new Error("MOEX venue requires non-empty engine, market and boardid");
  }
  if (engineN.includes("/") || marketN.includes("/") || boardidN.includes("/")) {
    throw new Error("MOEX venue components cannot contain '/'");
  }
  return `${engineN}/${marketN}/${boardidN}`;
}

export function decodeMoexVenue(venueId: string): {
  engine: string;
  market: string;
  boardid: string;
} {
  const parts = venueId.split("/");
  if (parts.length !== 3 || parts.some((part) => !part.trim())) {
    throw new Error("MOEX provider_venue_id must be engine/market/boardid");
  }
  return {
    engine: parts[0].trim().toLowerCase(),
    market: parts[1].trim().toLowerCase(),
    boardid: parts[2].trim().toUpperCase(),
  };
}

export function moexDraftToIdentity(draft: MoexMappingDraft): MarketIdentityWrite {
  return {
    provider: draft.provider.trim().toLowerCase(),
    provider_instrument_id: draft.secid.trim().toUpperCase(),
    provider_venue_id: encodeMoexVenue(draft.engine, draft.market, draft.boardid),
  };
}

export function identityToMoexDraft(
  identity: MarketIdentity | null | undefined,
  instrumentType: string,
): MoexMappingDraft {
  if (identity?.provider === MOEX_ISS_PROVIDER && identity.provider_venue_id) {
    try {
      const venue = decodeMoexVenue(identity.provider_venue_id);
      return {
        provider: identity.provider,
        engine: venue.engine,
        market: venue.market,
        boardid: venue.boardid,
        secid: identity.provider_instrument_id,
      };
    } catch {
      return defaultMappingDraft(instrumentType);
    }
  }
  return defaultMappingDraft(instrumentType);
}

export function defaultMappingDraft(instrumentType: string): MoexMappingDraft {
  if (instrumentType === "bond") {
    return {
      provider: MOEX_ISS_PROVIDER,
      engine: "stock",
      market: "bonds",
      boardid: "",
      secid: "",
    };
  }
  return {
    provider: MOEX_ISS_PROVIDER,
    engine: "stock",
    market: "shares",
    boardid: "",
    secid: "",
  };
}

export function defaultTInvestDraft(): TInvestMappingDraft {
  return { provider: T_INVEST_PROVIDER, providerInstrumentId: "", isin: null };
}

export function defaultMappingProvider(
  identity: MarketIdentity | null | undefined,
): MappingProviderId {
  if (identity?.provider === MOEX_ISS_PROVIDER) return MOEX_ISS_PROVIDER;
  return T_INVEST_PROVIDER;
}

export function tInvestDraftToIdentity(draft: TInvestMappingDraft): MarketIdentityWrite {
  const isin = draft.isin?.trim().toUpperCase() || null;
  return {
    provider: T_INVEST_PROVIDER,
    provider_instrument_id: draft.providerInstrumentId.trim(),
    provider_venue_id: null,
    ...(isin ? { isin } : {}),
  };
}

export function identityToTInvestDraft(
  identity: MarketIdentity | null | undefined,
): TInvestMappingDraft {
  if (identity?.provider === T_INVEST_PROVIDER) {
    return {
      provider: T_INVEST_PROVIDER,
      providerInstrumentId: identity.provider_instrument_id,
      isin: null,
    };
  }
  return defaultTInvestDraft();
}

export function formatMarketIdentity(identity: MarketIdentity): string {
  if (identity.provider === T_INVEST_PROVIDER) {
    return `T-Invest · ${identity.provider_instrument_id}`;
  }
  if (identity.provider === MOEX_ISS_PROVIDER && identity.provider_venue_id) {
    try {
      const venue = decodeMoexVenue(identity.provider_venue_id);
      return `${identity.provider} · ${venue.engine}/${venue.market} · ${venue.boardid} · ${identity.provider_instrument_id}`;
    } catch {
      // Fall through to the generic formatter.
    }
  }
  if (identity.provider_venue_id) {
    return `${identity.provider} · ${identity.provider_venue_id} · ${identity.provider_instrument_id}`;
  }
  return `${identity.provider} · ${identity.provider_instrument_id}`;
}

/** Display-only comparison of two backend money values. Never send this back. */
export function displayPriceDelta(
  current: MoneyValue | null | undefined,
  proposed: MoneyValue | null | undefined,
): string | null {
  if (!current?.amount || !proposed?.amount) {
    return null;
  }
  try {
    const delta = fromKopecks(toKopecks(proposed.amount) - toKopecks(current.amount));
    return formatMoneyDelta(delta);
  } catch {
    return null;
  }
}
