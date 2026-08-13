import { apiRequest } from "./client";
import type { MoneyValue } from "./types";

export type Goal = {
  id: number;
  name: string;
  goal_type: string;
  target_value: MoneyValue;
  target_date: string | null;
  is_active: boolean;
  is_main: boolean;
  calculation_mode: string;
  notes: string | null;
};

export type GoalCreatePayload = {
  name: string;
  goal_type: string;
  target_value: MoneyValue;
  target_date?: string | null;
  is_active?: boolean;
  is_main?: boolean;
  calculation_mode: string;
  notes?: string | null;
};

export type GoalUpdatePayload = {
  name?: string;
  goal_type?: string;
  target_value?: MoneyValue;
  target_date?: string | null;
  is_active?: boolean;
  is_main?: boolean;
  calculation_mode?: string;
  notes?: string | null;
};

export type GoalAchievementStatus = "achieved" | "not_projectable" | "inactive" | "unsupported";

export type GoalAchievementForecast = {
  goal_id: number;
  reporting_month_id: number;
  as_of_date: string;
  method_version: "goal_achievement_v1";
  source_forecast_version: string | null;
  status: GoalAchievementStatus;
  reason_code: string | null;
  current_value: MoneyValue | null;
  target_value: MoneyValue;
  remaining_amount: MoneyValue | null;
  progress_pct: string | null;
  estimated_achievement_date: string | null;
  is_approximate: boolean;
  warnings: string[];
  passive_income_history_start_month?: string | null;
  passive_income_months_used?: string[];
  passive_income_months_count?: number;
  passive_income_months_complete?: boolean;
};

export type GoalSummary = Goal & {
  achievement_forecast: GoalAchievementForecast;
};

export function listGoals(includeInactive = false, signal?: AbortSignal): Promise<Goal[]> {
  const suffix = includeInactive ? "?include_inactive=true" : "";
  return apiRequest<Goal[]>(`/api/goals${suffix}`, { method: "GET", signal });
}

export function listGoalSummary(
  reportingMonthId: number,
  options: { includeInactive?: boolean; forecastVersion?: string } = {},
  signal?: AbortSignal,
): Promise<GoalSummary[]> {
  const params = new URLSearchParams({ reporting_month_id: String(reportingMonthId) });
  if (options.includeInactive) params.set("include_inactive", "true");
  if (options.forecastVersion) params.set("forecast_version", options.forecastVersion);
  return apiRequest<GoalSummary[]>(`/api/goals/summary?${params.toString()}`, {
    method: "GET",
    signal,
  });
}

export function createGoal(payload: GoalCreatePayload, signal?: AbortSignal): Promise<Goal> {
  return apiRequest<Goal>("/api/goals", {
    method: "POST",
    body: payload,
    signal,
  });
}

export function updateGoal(
  goalId: number,
  payload: GoalUpdatePayload,
  signal?: AbortSignal,
): Promise<Goal> {
  return apiRequest<Goal>(`/api/goals/${goalId}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export function deleteGoal(goalId: number, signal?: AbortSignal): Promise<void> {
  return apiRequest<void>(`/api/goals/${goalId}`, { method: "DELETE", signal });
}
