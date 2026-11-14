/** Calendar boundaries for navigation only; no financial calculation. */
export function monthReturnsPath(month: { year: number; month: number }): string {
  const start = new Date(Date.UTC(month.year, month.month - 1, 0)).toISOString().slice(0, 10);
  const end = new Date(Date.UTC(month.year, month.month, 0)).toISOString().slice(0, 10);
  return `/v2/returns/account?${new URLSearchParams({ scope: "portfolio", start, end })}`;
}
