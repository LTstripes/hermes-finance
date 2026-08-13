import type { MarketIdentity, MarketIdentityWrite, MoneyValue } from "../api/types";
import { formatMoneyDelta } from "./format";
import { fromKopecks, toKopecks } from "./money";

export const MOEX_ISS_PROVIDER = "moex_iss";

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
  network_error: "Источник временно недоступен",
  malformed_response: "Данные источника нельзя безопасно использовать",
};

export type MoexMappingDraft = {
  provider: string;
  engine: string;
  market: string;
  boardid: string;
  secid: string;
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

export function formatMarketIdentity(identity: MarketIdentity): string {
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
