export function uiV2TaxIisPath(
  searchParams: URLSearchParams,
  defaultMonthId: number | null,
): string {
  const query = new URLSearchParams(searchParams);
  if (query.getAll("month").length === 0 && defaultMonthId !== null) {
    query.set("month", String(defaultMonthId));
  }
  const suffix = query.toString();
  return `/v2/income/tax-iis${suffix ? `?${suffix}` : ""}`;
}
