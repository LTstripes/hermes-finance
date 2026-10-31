const rubleTicks = new Intl.NumberFormat("ru-RU", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const smallRubleTicks = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

/** Chart geometry is already numeric; exact monetary tooltip values are unchanged. */
export function rubleAxisTick(value: number): string {
  return Number.isFinite(value)
    ? `${(Math.abs(value) < 1000 ? smallRubleTicks : rubleTicks).format(value)} ₽`
    : "";
}
