import type { ScenarioShockType } from "../api/scenarioLab";

export const SCENARIO_OPTIONS: {
  value: ScenarioShockType;
  label: string;
  description: string;
}[] = [
  {
    value: "equity_drawdown",
    label: "Падение акций",
    description:
      "Просадка рыночной стоимости позиций с типом инструмента «Акции» на выбранный процент. Фонды не раскрываются (без look-through), купоны, дивиденды и погашения не меняются.",
  },
  {
    value: "deposit_rate_assumption",
    label: "Ставка по вкладам",
    description:
      "Гипотетическая абсолютная годовая ставка по всем подходящим вкладам. Тело вкладов и ликвидный капитал не меняются — пересчитывается только прогнозный процентный доход.",
  },
  {
    value: "inflation_real_value",
    label: "Инфляция и реальная стоимость",
    description:
      "Покупательная способность известных будущих потоков при годовой инфляции. Номинальные факты не меняются; это не прогноз будущего капитала.",
  },
  {
    value: "fx_translation_shock",
    label: "Валютный шок",
    description:
      "Изменение стоимости в отчётной валюте для инструментов с явной валютой. Валюта инструмента — только кандидатный признак: без авторитетной базы пересчёта точный результат недоступен и не выдаётся за ноль.",
  },
];

/** Normalize an owner-typed percent/rate: "10,5" → "10.5". Returns null when not a decimal string. No financial caps here. */
export function normalizeDecimalInput(raw: string, allowSigned: boolean): string | null {
  const value = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (value === "" || value === "." || value === "-." || value === "-") return null;
  const pattern = allowSigned ? /^-?\d+(\.\d+)?$/ : /^\d+(\.\d+)?$/;
  if (!pattern.test(value)) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return value;
}

export function isWithinRange(value: string | null, max: number): boolean {
  if (value == null) return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 && numeric <= max;
}

export function isAtLeast(value: string | null, min: number): boolean {
  if (value == null) return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= min;
}

export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
