export function isContiguousMonth(
  prev: { year: number; month: number },
  next: { year: number; month: number },
): boolean {
  if (prev.month === 12) {
    return next.year === prev.year + 1 && next.month === 1;
  }
  return next.year === prev.year && next.month === prev.month + 1;
}

/** Compact Y-axis label: 1.2 млн / 45 тыс / 300. Display-only. */
export function axisMoney(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    const millions = (value / 1_000_000)
      .toFixed(1)
      .replace(".", ",")
      .replace(/0$/, "")
      .replace(/,$/, "");
    return `${millions} млн`;
  }
  if (abs >= 1_000) {
    return `${Math.round(value / 1_000)} тыс`;
  }
  return String(Math.round(value));
}
