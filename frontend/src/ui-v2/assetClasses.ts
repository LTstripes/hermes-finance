/**
 * Canonical UI v2 asset-class presentation.
 *
 * One taxonomy and one palette for every native v2 surface (Home, Capital,
 * archive, historical report): the five accepted classes in canonical order.
 * Colours match the --c-* tokens in styles/tokens.css (#1079); SVG charts need
 * literal values, so they are repeated here.
 * Presentation only — no amount, share or class is ever derived here.
 */
export const ASSET_CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Деньги", color: "#9aa3ae" },
  deposits: { label: "Депозиты", color: "#8a6bbe" },
  stocks: { label: "Акции", color: "#d0843a" },
  bonds: { label: "Облигации", color: "#3d6fb6" },
  gold_other: { label: "Золото и прочее", color: "#c8a227" },
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
