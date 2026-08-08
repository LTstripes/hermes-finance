/** Calendar period helpers for months UI (no finance math). */

export function lastDayOfMonth(year: number, month: number): string {
  const date = new Date(year, month, 0);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Next calendar month after year/month (1–12). */
export function nextPeriod(year: number, month: number): { year: number; month: number } {
  if (month >= 12) {
    return { year: year + 1, month: 1 };
  }
  return { year, month: month + 1 };
}

export function defaultCloneTarget(source: { year: number; month: number }): {
  year: number;
  month: number;
  snapshot_date: string;
} {
  const target = nextPeriod(source.year, source.month);
  return {
    ...target,
    snapshot_date: lastDayOfMonth(target.year, target.month),
  };
}
