/**
 * Canonical UI v2 asset-class presentation.
 *
 * One taxonomy and one palette for every native v2 surface (Home, Capital,
 * archive, historical report): the five accepted classes in canonical order.
 * Presentation only — no amount, share or class is ever derived here.
 */
export const ASSET_CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Деньги", color: "#5f7e9e" },
  deposits: { label: "Депозиты", color: "#8e73a6" },
  stocks: { label: "Акции", color: "#c68b51" },
  bonds: { label: "Облигации", color: "#5f9b82" },
  gold_other: { label: "Золото и прочее", color: "#a4a8ad" },
};

export const CLASS_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(ASSET_CLASS_META).map(([assetClass, meta]) => [assetClass, meta.color]),
);

export function classMeta(assetClass: string): { label: string; color: string } {
  return ASSET_CLASS_META[assetClass] ?? { label: assetClass, color: "#a4a8ad" };
}

/** Row context of a brokerage position; not a financial fact. */
export const POSITION_TYPE_LABELS: Record<string, string> = {
  stock: "Акция",
  bond: "Облигация",
  fund: "Фонд",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
};
