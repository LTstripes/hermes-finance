import { apiRequest } from "./client";
import type { TaxIisPlanner } from "./types";

export type TaxIisPlannerQuery = {
  reportingMonthId?: number | null;
  taxYear?: number | null;
  accountId?: number | null;
};

export function getTaxIisPlanner(
  query: TaxIisPlannerQuery = {},
  signal?: AbortSignal,
): Promise<TaxIisPlanner> {
  const params = new URLSearchParams();
  if (query.reportingMonthId != null) {
    params.set("reporting_month_id", String(query.reportingMonthId));
  }
  if (query.taxYear != null) {
    params.set("tax_year", String(query.taxYear));
  }
  if (query.accountId != null) {
    params.set("account_id", String(query.accountId));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<TaxIisPlanner>(`/api/tax-iis-planner${suffix}`, {
    method: "GET",
    signal,
  });
}
