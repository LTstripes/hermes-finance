import { ApiClientError, apiRequest } from "./client";
import type { MonthSummary, MoneyValue } from "./types";

const UNAVAILABLE_MONEY: MoneyValue = { amount: "", currency: "RUB" };

/**
 * Load the month summary used by the editor.
 *
 * Incomplete salary-tax history is an expected backfill state: it must make
 * calculated tax unavailable, not make the whole month editor unavailable.
 * Other API errors still fail normally.
 */
export async function getMonthSummary(
  monthId: number,
  signal?: AbortSignal,
): Promise<MonthSummary> {
  try {
    return await apiRequest<MonthSummary>(`/api/months/${monthId}/summary`, {
      method: "GET",
      signal,
    });
  } catch (error) {
    if (error instanceof ApiClientError && error.code === "salary_tax_history_incomplete") {
      return {
        month: {
          id: monthId,
          year: 0,
          month: 0,
          status: "draft",
          snapshot_date: "",
          source: "manual",
        },
        salary_tax: {
          tax: UNAVAILABLE_MONEY,
          calculated_net: UNAVAILABLE_MONEY,
        },
        salary_actual_net: UNAVAILABLE_MONEY,
      };
    }
    throw error;
  }
}
