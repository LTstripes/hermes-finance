import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export interface TotalIncomePoint {
  reporting_month_id: number;
  year: number;
  month: number;
  salary_net: MoneyValue;
  salary_is_estimate: boolean;
  bonus_net: MoneyValue;
  passive_actual: MoneyValue | null;
  other_net: MoneyValue;
}

export interface TotalIncomeWindow {
  from: string | null;
  to: string | null;
  months_observed: number;
  months_used: string[];
  salary_months: number;
  passive_months: number;
  bonus_months: number;
  bonus_target_months: number;
  estimate_months: number;
  salary_sum: MoneyValue | null;
  passive_sum: MoneyValue | null;
  bonus_sum: MoneyValue | null;
  other_sum: MoneyValue | null;
  salary_monthly_average: MoneyValue | null;
  passive_monthly_average: MoneyValue | null;
  bonus_smoothed_monthly: MoneyValue | null;
  monthly_average: MoneyValue | null;
  current_level: MoneyValue | null;
  current_passive_months: number;
  total_net: MoneyValue | null;
  passive_share_pct: string | null;
  warnings: string[];
}

export interface TotalIncome {
  latest_closed_report_id: number | null;
  configured_start_month: string | null;
  points: TotalIncomePoint[];
  windows: Record<"calendar_year" | "rolling_12" | "all", TotalIncomeWindow>;
}

export function getTotalIncome(monthId: number, signal?: AbortSignal): Promise<TotalIncome> {
  return apiRequest<TotalIncome>(`/api/analytics/total-income?month_id=${monthId}`, {
    method: "GET",
    signal,
  });
}
