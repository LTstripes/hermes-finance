import { apiDownload, apiRequest, type ApiDownload } from "./client";

/**
 * Scenario Lab owner-facing API module (#332).
 *
 * Typed client for the accepted read-only surfaces:
 * - `POST /api/months/{month_id}/scenario-lab` — deterministic evaluation;
 * - `POST /api/months/{month_id}/scenario-lab/export` — same envelope as an
 *   `application/json` attachment for the exact same scenario input.
 *
 * The types below mirror the #329 response envelope defensively: money/rate
 * values are decimal strings plus integer minor-unit (`*_kopecks`) fields and
 * never binary floats. The frontend never recomputes scenario formulas — it
 * formats the server envelope only. Machine-readable error codes flow through
 * the shared ApiClientError and stay available for the UI.
 */

export type ScenarioShockType =
  | "equity_drawdown"
  | "deposit_rate_assumption"
  | "inflation_real_value"
  | "fx_translation_shock";

export type EquityDrawdownShock = {
  equity_drawdown: { drawdown_pct: string };
};

export type DepositRateAssumptionShock = {
  deposit_rate_assumption: {
    /** Hypothetical absolute annual rate (percentage points), not a delta. */
    assumed_annual_rate_pct: string;
    /** UI v1 always targets all eligible deposits; explicit deposit_ids stay out of scope. */
    all_eligible_deposits: true;
  };
};

export type InflationRealValueShock = {
  inflation_real_value: { annual_inflation_pct: string };
};

export type FxTranslationShock = {
  fx_translation_shock: {
    target_currency: string;
    reporting_value_change_pct: string;
  };
};

export type ScenarioLabShock =
  | EquityDrawdownShock
  | DepositRateAssumptionShock
  | InflationRealValueShock
  | FxTranslationShock;

export type ScenarioLabEvaluationEnvelope = {
  contract_version: string;
  calculation_version: string;
  shock_schema_version: string;
  reporting_month: ScenarioReportingMonth;
  base_fingerprint: string;
  semantic_fingerprint: string;
  normalized_shock_input: Record<string, string | number>;
  normalized_target_scope: Record<string, unknown>;
  assumptions: string[];
  base: Record<string, unknown>;
  stressed: Record<string, unknown>;
  impact: Record<string, unknown>;
  row_applicability: Record<string, string>;
  metric_support: Record<string, ScenarioMetricSupport>;
  coverage: Record<string, string | number>;
  affected_canonical_refs: Record<string, unknown>;
  warnings: string[];
  generated_at: string | null;
  presentation_metadata: {
    account_names?: Record<string, string>;
    instrument_names?: Record<string, string>;
    deposit_names?: Record<string, string>;
  } | null;
};

export type ScenarioReportingMonth = {
  id: number;
  year: number;
  month: number;
  snapshot_date: string;
  status: "draft" | "closed" | (string & {});
};

export type ScenarioSupportStatus = "supported" | "unknown" | "unavailable" | (string & {});

export type ScenarioMetricSupport = {
  status: ScenarioSupportStatus;
  reason_codes: string[];
};

export type ScenarioLiquidSummary = {
  liquid_assets: string;
  liquid_assets_kopecks: number;
  liquid_capital_net: string;
  liquid_capital_net_kopecks: number;
  debts_included: string;
  debts_included_kopecks: number;
};

export type ScenarioPerPositionRow = {
  account_id: number;
  instrument_id: number;
  instrument_type: string;
  market_value: string;
  market_value_kopecks: number;
};

export type ScenarioTopPositionRow = {
  position_id: number;
  account_id: number;
  instrument_id: number;
  instrument_type: string;
  amount: string;
  amount_kopecks: number;
  share_pct: string | null;
};

export type ScenarioAccountAllocationRow = {
  account_id: number;
  amount: string;
  amount_kopecks: number;
  share_pct: string | null;
};

export type ScenarioPerPositionImpact = {
  applicability: string;
  delta: string;
  delta_kopecks: number;
  reason_codes?: string[];
};

export type EquityPositionStateBlock = ScenarioLiquidSummary & {
  asset_allocation: Record<string, string | number | null>;
  account_allocation: ScenarioAccountAllocationRow[];
  top_positions: ScenarioTopPositionRow[];
  capital_goals: unknown[];
  future_cash_flow_rows_unchanged: boolean;
  passive_income_effect: { status: string; reason: string } | null;
  per_position: Record<string, ScenarioPerPositionRow>;
};

export type EquityEvaluation = ScenarioLabEvaluationEnvelope & {
  normalized_shock_input: {
    shock_type: "equity_drawdown";
    drawdown_pct: string;
  };
  base: EquityPositionStateBlock;
  stressed: EquityPositionStateBlock;
  impact: ScenarioLiquidSummary & {
    known_scope_impact: string;
    known_scope_impact_kopecks: number;
    per_position: Record<string, ScenarioPerPositionImpact>;
  };
  coverage: {
    applied: number;
    not_applicable: number;
    unknown: number;
    total_positions: number;
    eligible_positions: number;
    known_scope_impact: string;
    known_scope_impact_kopecks: number;
  };
};

export type ScenarioPerDepositRow = {
  deposit_id: number;
  account_id: number;
  deposit_type: string;
  balance: string;
  balance_kopecks: number;
  annual_rate_basis_points: number;
  annual_rate_pct: string;
  expected_monthly_interest: string;
  expected_monthly_interest_kopecks: number;
};

export type ScenarioForecastPassiveIncome = {
  monthly_total: string;
  monthly_total_kopecks: number;
  annual_total: string;
  annual_total_kopecks: number;
  is_approximate: boolean;
  breakdown: Record<string, string | number>;
};

export type DepositEvaluation = ScenarioLabEvaluationEnvelope & {
  normalized_shock_input: {
    shock_type: "deposit_rate_assumption";
    assumed_annual_rate_pct: string;
    annual_rate_basis_points: number;
  };
  base: ScenarioLiquidSummary & {
    forecast_passive_income: ScenarioForecastPassiveIncome;
    cash_flow_ladder: Record<string, unknown>;
    per_deposit: Record<string, ScenarioPerDepositRow>;
    top_positions: ScenarioTopPositionRow[];
    asset_allocation: Record<string, string | number | null>;
    account_allocation: ScenarioAccountAllocationRow[];
    capital_goals: unknown[];
    passive_income_goal_effect: { status: string; basis: string; affected: boolean };
  };
  stressed: DepositEvaluation["base"];
  impact: {
    liquid_assets_delta: string;
    liquid_assets_delta_kopecks: number;
    liquid_capital_net_delta: string;
    liquid_capital_net_delta_kopecks: number;
    monthly_interest_delta: string;
    monthly_interest_delta_kopecks: number;
    annual_deposit_interest_delta: string;
    annual_deposit_interest_delta_kopecks: number;
    forecast_annual_total_delta: string;
    forecast_annual_total_delta_kopecks: number;
    known_scope_monthly_interest_delta: string;
    known_scope_monthly_interest_delta_kopecks: number;
    per_deposit: Record<string, { applicability: string; delta: string; delta_kopecks: number }>;
  };
  coverage: {
    applied: number;
    not_applicable: number;
    unknown: number;
    total_deposits: number;
    eligible_deposits: number;
    known_scope_monthly_interest_delta: string;
    known_scope_monthly_interest_delta_kopecks: number;
  };
};

export type ScenarioRealValueMonthRow = {
  year: number;
  month: number;
  months_ahead: number;
  is_approximate: boolean;
  nominal_income: string;
  nominal_income_kopecks: number;
  real_income: string;
  real_income_kopecks: number;
  income_delta: string;
  income_delta_kopecks: number;
  nominal_redemption: string;
  nominal_redemption_kopecks: number;
  real_redemption: string;
  real_redemption_kopecks: number;
  redemption_delta: string;
  redemption_delta_kopecks: number;
  nominal_total_cash_flow: string;
  nominal_total_cash_flow_kopecks: number;
  real_total_cash_flow: string;
  real_total_cash_flow_kopecks: number;
  total_cash_flow_delta: string;
  total_cash_flow_delta_kopecks: number;
};

export type InflationEvaluation = ScenarioLabEvaluationEnvelope & {
  normalized_shock_input: {
    shock_type: "inflation_real_value";
    annual_inflation_pct: string;
  };
  base: ScenarioLiquidSummary & {
    cash_flow_real_value: Record<string, ScenarioRealValueMonthRow>;
    cash_flow_ladder: Record<string, unknown>;
    forecast_passive_income: ScenarioForecastPassiveIncome;
    top_positions: ScenarioTopPositionRow[];
    capital_goals: unknown[];
  };
  stressed: InflationEvaluation["base"];
  impact: {
    liquid_assets_delta: string;
    liquid_assets_delta_kopecks: number;
    liquid_capital_net_delta: string;
    liquid_capital_net_delta_kopecks: number;
    future_income_real_value_delta: string;
    future_income_real_value_delta_kopecks: number;
    future_redemption_real_value_delta: string;
    future_redemption_real_value_delta_kopecks: number;
    future_total_cash_flow_real_value_delta: string;
    future_total_cash_flow_real_value_delta_kopecks: number;
    per_month: Record<string, unknown>;
  };
  coverage: {
    applied: number;
    not_applicable: number;
    unknown: number;
    total_months: number;
    eligible_months: number;
    known_scope_income_real_value_delta: string;
    known_scope_income_real_value_delta_kopecks: number;
    known_scope_redemption_real_value_delta: string;
    known_scope_redemption_real_value_delta_kopecks: number;
    known_scope_total_cash_flow_real_value_delta: string;
    known_scope_total_cash_flow_real_value_delta_kopecks: number;
  };
};

export type FxEvaluation = ScenarioLabEvaluationEnvelope & {
  normalized_shock_input: {
    shock_type: "fx_translation_shock";
    target_currency: string;
    reporting_value_change_pct: string;
  };
  base: EquityPositionStateBlock;
  stressed: EquityPositionStateBlock;
  impact: ScenarioLiquidSummary & {
    known_scope_impact: string;
    known_scope_impact_kopecks: number;
    per_position: Record<string, ScenarioPerPositionImpact>;
  };
  coverage: {
    applied: number;
    not_applicable: number;
    unknown: number;
    total_positions: number;
    eligible_positions: number;
    candidate_target_currency: number;
    known_scope_impact: string;
    known_scope_impact_kopecks: number;
  };
};

export type ScenarioLabEvaluation =
  | EquityEvaluation
  | DepositEvaluation
  | InflationEvaluation
  | FxEvaluation;

export function shockTypeOf(evaluation: ScenarioLabEvaluation): ScenarioShockType {
  return evaluation.normalized_shock_input.shock_type as ScenarioShockType;
}

export function evaluateScenarioLab(
  monthId: number,
  shock: ScenarioLabShock,
  signal?: AbortSignal,
): Promise<ScenarioLabEvaluation> {
  return apiRequest<ScenarioLabEvaluation>(`/api/months/${monthId}/scenario-lab`, {
    method: "POST",
    body: { shock },
    signal,
  });
}

export function downloadScenarioLabExport(
  monthId: number,
  shock: ScenarioLabShock,
): Promise<ApiDownload> {
  return apiDownload(`/api/months/${monthId}/scenario-lab/export`, {
    method: "POST",
    body: { shock },
  });
}
