export const MONTH_MAY = {
  id: 1,
  year: 2030,
  month: 5,
  status: "closed" as const,
  snapshot_date: "2030-05-12",
  source: "manual",
};

export const MONTH_JUNE = {
  id: 2,
  year: 2030,
  month: 6,
  status: "draft" as const,
  snapshot_date: "2030-06-12",
  source: "manual",
};

export const MONTHS = [MONTH_JUNE, MONTH_MAY];

function stockRow(_positionId: number, instrumentId: number, marketValue: string, kopecks: number) {
  return {
    account_id: 1,
    instrument_id: instrumentId,
    instrument_type: "stock",
    market_value: marketValue,
    market_value_kopecks: kopecks,
  };
}

function bondRow(_positionId: number, instrumentId: number, marketValue: string, kopecks: number) {
  return {
    account_id: 1,
    instrument_id: instrumentId,
    instrument_type: "bond",
    market_value: marketValue,
    market_value_kopecks: kopecks,
  };
}

function positionImpact(
  applicability: string,
  delta: string,
  kopecks: number,
  reasonCodes: string[] = [],
) {
  return {
    applicability,
    delta,
    delta_kopecks: kopecks,
    ...(reasonCodes.length ? { reason_codes: reasonCodes } : {}),
  };
}

export function equityEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-equity",
    semantic_fingerprint: "fp-sem-equity",
    normalized_shock_input: { shock_type: "equity_drawdown", drawdown_pct: "10" },
    normalized_target_scope: { selector: "all_eligible", eligible_position_ids: [1, 2] },
    assumptions: ["dividends_unchanged", "no_fund_lookthrough", "no_probabilistic_forecast"],
    base: {
      liquid_assets: "150000.00",
      liquid_assets_kopecks: 15000000,
      liquid_capital_net: "150000.00",
      liquid_capital_net_kopecks: 15000000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      per_position: {
        "1": stockRow(1, 10, "100000.00", 10000000),
        "2": bondRow(2, 11, "50000.00", 5000000),
      },
    },
    stressed: {
      liquid_assets: "140000.00",
      liquid_assets_kopecks: 14000000,
      liquid_capital_net: "140000.00",
      liquid_capital_net_kopecks: 14000000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      per_position: {
        "1": stockRow(1, 10, "90000.00", 9000000),
        "2": bondRow(2, 11, "50000.00", 5000000),
      },
    },
    impact: {
      known_scope_impact: "-10000.00",
      known_scope_impact_kopecks: -1000000,
      liquid_assets_delta: "-10000.00",
      liquid_assets_delta_kopecks: -1000000,
      liquid_capital_net_delta: "-10000.00",
      liquid_capital_net_delta_kopecks: -1000000,
      per_position: {
        "1": positionImpact("applied", "-10000.00", -1000000),
        "2": positionImpact("not_applicable", "0.00", 0),
      },
    },
    row_applicability: { "1": "applied", "2": "not_applicable" },
    metric_support: {
      liquid_assets: { status: "supported", reason_codes: [] },
      liquid_capital_net: { status: "supported", reason_codes: [] },
      per_position: { status: "supported", reason_codes: [] },
      passive_income_effect: {
        status: "unavailable",
        reason_codes: ["no_deterministic_income_relationship"],
      },
    },
    coverage: {
      applied: 1,
      not_applicable: 1,
      unknown: 0,
      total_positions: 2,
      eligible_positions: 2,
      known_scope_impact: "-10000.00",
      known_scope_impact_kopecks: -1000000,
    },
    affected_canonical_refs: { reporting_month_id: month.id, position_ids: [1, 2] },
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      account_names: { "1": "Брокер" },
      instrument_names: { "10": "Сбер", "11": "ОФЗ" },
    },
  };
}

export function depositEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-deposit",
    semantic_fingerprint: "fp-sem-deposit",
    normalized_shock_input: {
      shock_type: "deposit_rate_assumption",
      assumed_annual_rate_pct: "8.00",
      annual_rate_basis_points: 800,
    },
    normalized_target_scope: { selector: "all_eligible_deposits", deposit_ids: [1] },
    assumptions: [
      "principal_unchanged",
      "no_reinvestment_assumption",
      "no_provider_network_access",
    ],
    base: {
      liquid_assets: "120000.00",
      liquid_assets_kopecks: 12000000,
      liquid_capital_net: "120000.00",
      liquid_capital_net_kopecks: 12000000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      forecast_passive_income: {
        monthly_total: "600.00",
        monthly_total_kopecks: 60000,
        annual_total: "7200.00",
        annual_total_kopecks: 720000,
        is_approximate: true,
        breakdown: {
          expected_deposit_interest: "7200.00",
          expected_deposit_interest_kopecks: 720000,
        },
      },
      per_deposit: {
        "1": {
          deposit_id: 1,
          account_id: 1,
          deposit_type: "deposit",
          balance: "120000.00",
          balance_kopecks: 12000000,
          annual_rate_basis_points: 600,
          annual_rate_pct: "6.00",
          expected_monthly_interest: "600.00",
          expected_monthly_interest_kopecks: 60000,
        },
      },
      passive_income_goal_effect: {
        status: "unchanged",
        basis: "historical_actual_rolling_average",
        affected: false,
      },
    },
    stressed: {
      liquid_assets: "120000.00",
      liquid_assets_kopecks: 12000000,
      liquid_capital_net: "120000.00",
      liquid_capital_net_kopecks: 12000000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      forecast_passive_income: {
        monthly_total: "800.00",
        monthly_total_kopecks: 80000,
        annual_total: "9600.00",
        annual_total_kopecks: 960000,
        is_approximate: true,
        breakdown: {
          expected_deposit_interest: "9600.00",
          expected_deposit_interest_kopecks: 960000,
        },
      },
      per_deposit: {
        "1": {
          deposit_id: 1,
          account_id: 1,
          deposit_type: "deposit",
          balance: "120000.00",
          balance_kopecks: 12000000,
          annual_rate_basis_points: 800,
          annual_rate_pct: "8.00",
          expected_monthly_interest: "800.00",
          expected_monthly_interest_kopecks: 80000,
        },
      },
      passive_income_goal_effect: {
        status: "unchanged",
        basis: "historical_actual_rolling_average",
        affected: false,
      },
    },
    impact: {
      liquid_assets_delta: "0.00",
      liquid_assets_delta_kopecks: 0,
      liquid_capital_net_delta: "0.00",
      liquid_capital_net_delta_kopecks: 0,
      monthly_interest_delta: "200.00",
      monthly_interest_delta_kopecks: 20000,
      annual_deposit_interest_delta: "2400.00",
      annual_deposit_interest_delta_kopecks: 240000,
      forecast_annual_total_delta: "2400.00",
      forecast_annual_total_delta_kopecks: 240000,
      known_scope_monthly_interest_delta: "200.00",
      known_scope_monthly_interest_delta_kopecks: 20000,
      per_deposit: { "1": positionImpact("applied", "200.00", 20000) },
    },
    row_applicability: { "1": "applied" },
    metric_support: {
      liquid_assets: { status: "supported", reason_codes: [] },
      liquid_capital_net: { status: "supported", reason_codes: [] },
      forecast_passive_income: { status: "supported", reason_codes: [] },
      deposit_interest: { status: "supported", reason_codes: [] },
      passive_income_goal: { status: "supported", reason_codes: [] },
    },
    coverage: {
      applied: 1,
      not_applicable: 0,
      unknown: 0,
      total_deposits: 1,
      eligible_deposits: 1,
      known_scope_monthly_interest_delta: "200.00",
      known_scope_monthly_interest_delta_kopecks: 20000,
    },
    affected_canonical_refs: { reporting_month_id: month.id, deposit_ids: [1] },
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      account_names: { "1": "Банк" },
      deposit_names: { "1": "Вклад Альфа" },
    },
  };
}

export function inflationEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  const baseRow = {
    year: 2030,
    month: 5,
    months_ahead: 0,
    is_approximate: true,
    nominal_income: "600.00",
    nominal_income_kopecks: 60000,
    real_income: "600.00",
    real_income_kopecks: 60000,
    income_delta: "0.00",
    income_delta_kopecks: 0,
    nominal_redemption: "0.00",
    nominal_redemption_kopecks: 0,
    real_redemption: "0.00",
    real_redemption_kopecks: 0,
    redemption_delta: "0.00",
    redemption_delta_kopecks: 0,
    nominal_total_cash_flow: "600.00",
    nominal_total_cash_flow_kopecks: 60000,
    real_total_cash_flow: "600.00",
    real_total_cash_flow_kopecks: 60000,
    total_cash_flow_delta: "0.00",
    total_cash_flow_delta_kopecks: 0,
  };
  const stressedLaterRow = {
    ...baseRow,
    year: 2031,
    month: 4,
    months_ahead: 11,
    real_income: "537.79",
    real_income_kopecks: 53779,
    income_delta: "-62.21",
    income_delta_kopecks: -6221,
    real_total_cash_flow: "537.79",
    real_total_cash_flow_kopecks: 53779,
    total_cash_flow_delta: "-62.21",
    total_cash_flow_delta_kopecks: -6221,
  };
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-inflation",
    semantic_fingerprint: "fp-sem-inflation",
    normalized_shock_input: { shock_type: "inflation_real_value", annual_inflation_pct: "12" },
    normalized_target_scope: {
      selector: "cash_flow_ladder_months",
      ladder_months: ["2030-05", "2031-04"],
    },
    assumptions: [
      "nominal_values_unchanged",
      "v1_monthly_inflation_convention",
      "no_future_capital_trajectory",
      "no_probabilistic_forecast",
    ],
    base: {
      liquid_assets: "121000.00",
      liquid_assets_kopecks: 12100000,
      liquid_capital_net: "121000.00",
      liquid_capital_net_kopecks: 12100000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      forecast_passive_income: {
        monthly_total: "600.00",
        monthly_total_kopecks: 60000,
        annual_total: "7300.00",
        annual_total_kopecks: 730000,
        is_approximate: true,
        breakdown: {},
      },
      cash_flow_real_value: { "2030-05": baseRow },
      capital_goals: [],
    },
    stressed: {
      liquid_assets: "121000.00",
      liquid_assets_kopecks: 12100000,
      liquid_capital_net: "121000.00",
      liquid_capital_net_kopecks: 12100000,
      debts_included: "0.00",
      debts_included_kopecks: 0,
      forecast_passive_income: {
        monthly_total: "600.00",
        monthly_total_kopecks: 60000,
        annual_total: "7300.00",
        annual_total_kopecks: 730000,
        is_approximate: true,
        breakdown: {},
      },
      cash_flow_real_value: { "2030-05": baseRow, "2031-04": stressedLaterRow },
      capital_goals: [],
    },
    impact: {
      liquid_assets_delta: "0.00",
      liquid_assets_delta_kopecks: 0,
      liquid_capital_net_delta: "0.00",
      liquid_capital_net_delta_kopecks: 0,
      future_income_real_value_delta: "-62.21",
      future_income_real_value_delta_kopecks: -6221,
      future_redemption_real_value_delta: "0.00",
      future_redemption_real_value_delta_kopecks: 0,
      future_total_cash_flow_real_value_delta: "-62.21",
      future_total_cash_flow_real_value_delta_kopecks: -6221,
      per_month: {},
    },
    row_applicability: { "2030-05": "applied", "2031-04": "applied" },
    metric_support: {
      liquid_assets: { status: "supported", reason_codes: [] },
      liquid_capital_net: { status: "supported", reason_codes: [] },
      forecast_passive_income: { status: "supported", reason_codes: [] },
      future_income_real_value: { status: "supported", reason_codes: [] },
      future_capital_purchasing_power: {
        status: "unavailable",
        reason_codes: ["no_future_capital_trajectory"],
      },
    },
    coverage: {
      applied: 2,
      not_applicable: 0,
      unknown: 0,
      total_months: 2,
      eligible_months: 2,
      known_scope_income_real_value_delta: "-62.21",
      known_scope_income_real_value_delta_kopecks: -6221,
      known_scope_redemption_real_value_delta: "0.00",
      known_scope_redemption_real_value_delta_kopecks: 0,
      known_scope_total_cash_flow_real_value_delta: "-62.21",
      known_scope_total_cash_flow_real_value_delta_kopecks: -6221,
    },
    affected_canonical_refs: { reporting_month_id: month.id },
    warnings: [],
    generated_at: null,
    presentation_metadata: { account_names: { "1": "Банк" } },
  };
}

export function fxEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  const baseBlock = {
    liquid_assets: "150000.00",
    liquid_assets_kopecks: 15000000,
    liquid_capital_net: "150000.00",
    liquid_capital_net_kopecks: 15000000,
    debts_included: "0.00",
    debts_included_kopecks: 0,
    per_position: {
      "1": stockRow(1, 10, "100000.00", 10000000),
      "2": bondRow(2, 11, "50000.00", 5000000),
    },
  };
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-fx",
    semantic_fingerprint: "fp-sem-fx",
    normalized_shock_input: {
      shock_type: "fx_translation_shock",
      target_currency: "USD",
      reporting_value_change_pct: "10",
    },
    normalized_target_scope: {
      selector: "all_eligible",
      target_currency: "USD",
      reporting_currency: "RUB",
    },
    assumptions: ["no_live_fx_lookup", "no_inferred_fx_exposure", "no_probabilistic_forecast"],
    base: baseBlock,
    stressed: baseBlock,
    impact: {
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
      liquid_assets_delta: "0.00",
      liquid_assets_delta_kopecks: 0,
      liquid_capital_net_delta: "0.00",
      liquid_capital_net_delta_kopecks: 0,
      per_position: {
        "1": positionImpact("unknown", "0.00", 0, ["fx_translation_basis_unavailable"]),
        "2": positionImpact("not_applicable", "0.00", 0),
      },
    },
    row_applicability: { "1": "unknown", "2": "not_applicable" },
    metric_support: {
      liquid_assets: {
        status: "unavailable",
        reason_codes: ["fx_translation_basis_unavailable"],
      },
      liquid_capital_net: {
        status: "unavailable",
        reason_codes: ["fx_translation_basis_unavailable"],
      },
      per_position: {
        status: "unavailable",
        reason_codes: ["fx_translation_basis_unavailable"],
      },
      redemption: { status: "supported", reason_codes: [] },
    },
    coverage: {
      applied: 0,
      candidate_target_currency: 1,
      not_applicable: 1,
      unknown: 0,
      total_positions: 2,
      eligible_positions: 2,
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
    },
    affected_canonical_refs: { reporting_month_id: month.id, position_ids: [1, 2] },
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      account_names: { "1": "Брокер" },
      instrument_names: { "10": "Акция США", "11": "ОФЗ" },
    },
  };
}

export function fxEmptyScopeEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  // Owner UAT shape (#333): 0 candidates, 0 unknown, only not-applicable rows.
  // Server aggregate support stays `supported` with exact zero impact.
  const baseBlock = {
    liquid_assets: "150000.00",
    liquid_assets_kopecks: 15000000,
    liquid_capital_net: "150000.00",
    liquid_capital_net_kopecks: 15000000,
    debts_included: "0.00",
    debts_included_kopecks: 0,
    per_position: {
      "1": stockRow(1, 10, "100000.00", 10000000),
      "2": bondRow(2, 11, "50000.00", 5000000),
    },
  };
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-fx-empty",
    semantic_fingerprint: "fp-sem-fx-empty",
    normalized_shock_input: {
      shock_type: "fx_translation_shock",
      target_currency: "USD",
      reporting_value_change_pct: "10",
    },
    normalized_target_scope: {
      selector: "all_eligible",
      target_currency: "USD",
      reporting_currency: "RUB",
    },
    assumptions: ["no_live_fx_lookup", "no_inferred_fx_exposure", "no_probabilistic_forecast"],
    base: baseBlock,
    stressed: baseBlock,
    impact: {
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
      liquid_assets_delta: "0.00",
      liquid_assets_delta_kopecks: 0,
      liquid_capital_net_delta: "0.00",
      liquid_capital_net_delta_kopecks: 0,
      per_position: {
        "1": positionImpact("not_applicable", "0.00", 0),
        "2": positionImpact("not_applicable", "0.00", 0),
      },
    },
    row_applicability: { "1": "not_applicable", "2": "not_applicable" },
    metric_support: {
      liquid_assets: { status: "supported", reason_codes: [] },
      liquid_capital_net: { status: "supported", reason_codes: [] },
      per_position: { status: "supported", reason_codes: [] },
      redemption: { status: "supported", reason_codes: [] },
    },
    coverage: {
      applied: 0,
      candidate_target_currency: 0,
      not_applicable: 2,
      unknown: 0,
      total_positions: 2,
      eligible_positions: 2,
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
    },
    affected_canonical_refs: { reporting_month_id: month.id, position_ids: [1, 2] },
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      account_names: { "1": "Брокер" },
      instrument_names: { "10": "Акция США", "11": "ОФЗ" },
    },
  };
}

export function fxUnknownEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
  // Missing/invalid currency only: no candidates, server aggregate is `unknown`.
  const baseBlock = {
    liquid_assets: "150000.00",
    liquid_assets_kopecks: 15000000,
    liquid_capital_net: "150000.00",
    liquid_capital_net_kopecks: 15000000,
    debts_included: "0.00",
    debts_included_kopecks: 0,
    per_position: {
      "1": stockRow(1, 10, "100000.00", 10000000),
      "2": bondRow(2, 11, "50000.00", 5000000),
    },
  };
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "fp-base-fx-unknown",
    semantic_fingerprint: "fp-sem-fx-unknown",
    normalized_shock_input: {
      shock_type: "fx_translation_shock",
      target_currency: "USD",
      reporting_value_change_pct: "10",
    },
    normalized_target_scope: {
      selector: "all_eligible",
      target_currency: "USD",
      reporting_currency: "RUB",
    },
    assumptions: ["no_live_fx_lookup", "no_inferred_fx_exposure", "no_probabilistic_forecast"],
    base: baseBlock,
    stressed: baseBlock,
    impact: {
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
      liquid_assets_delta: "0.00",
      liquid_assets_delta_kopecks: 0,
      liquid_capital_net_delta: "0.00",
      liquid_capital_net_delta_kopecks: 0,
      per_position: {
        "1": positionImpact("unknown", "0.00", 0, ["missing_currency"]),
        "2": positionImpact("not_applicable", "0.00", 0),
      },
    },
    row_applicability: { "1": "unknown", "2": "not_applicable" },
    metric_support: {
      liquid_assets: { status: "unknown", reason_codes: ["missing_currency"] },
      liquid_capital_net: { status: "unknown", reason_codes: ["missing_currency"] },
      per_position: { status: "unknown", reason_codes: ["missing_currency"] },
      redemption: { status: "supported", reason_codes: [] },
    },
    coverage: {
      applied: 0,
      candidate_target_currency: 0,
      not_applicable: 1,
      unknown: 1,
      total_positions: 2,
      eligible_positions: 2,
      known_scope_impact: "0.00",
      known_scope_impact_kopecks: 0,
    },
    affected_canonical_refs: { reporting_month_id: month.id, position_ids: [1, 2] },
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      account_names: { "1": "Брокер" },
      instrument_names: { "10": "Акция США", "11": "ОФЗ" },
    },
  };
}
