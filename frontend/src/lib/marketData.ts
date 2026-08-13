import type { MarketIdentity, MarketIdentityWrite, MoneyValue } from "../api/types";
import { formatMoneyDelta } from "./format";
import { fromKopecks, toKopecks } from "./money";

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

export function defaultMappingDraft(instrumentType: string): MarketIdentityWrite {
  if (instrumentType === "bond") {
    return {
      provider: "moex_iss",
      engine: "stock",
      market: "bonds",
      boardid: "",
      secid: "",
    };
  }
  return {
    provider: "moex_iss",
    engine: "stock",
    market: "shares",
    boardid: "",
    secid: "",
  };
}

export function formatMarketIdentity(identity: MarketIdentity): string {
  return `${identity.provider} · ${identity.engine}/${identity.market} · ${identity.boardid} · ${identity.secid}`;
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
