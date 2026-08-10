import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type AppSettings = {
  base_currency: string;
  locale: string;
  timezone: string;
  passive_income_goal: MoneyValue;
  formula_version: string;
};

export type AppSettingsUpdate = {
  locale?: string;
  timezone?: string;
};

export function getSettings(signal?: AbortSignal): Promise<AppSettings> {
  return apiRequest<AppSettings>("/api/settings", { method: "GET", signal });
}

export function updateSettings(
  payload: AppSettingsUpdate,
  signal?: AbortSignal,
): Promise<AppSettings> {
  return apiRequest<AppSettings>("/api/settings", {
    method: "PUT",
    body: payload,
    signal,
  });
}
