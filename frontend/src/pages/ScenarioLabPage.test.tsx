import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScenarioLabPage } from "./ScenarioLabPage";

const MONTH_MAY = {
  id: 1,
  year: 2030,
  month: 5,
  status: "closed" as const,
  snapshot_date: "2030-05-12",
  source: "manual",
};

const MONTH_JUNE = {
  id: 2,
  year: 2030,
  month: 6,
  status: "draft" as const,
  snapshot_date: "2030-06-12",
  source: "manual",
};

const MONTHS = [MONTH_JUNE, MONTH_MAY];

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(code: string, message: string, status = 422): Response {
  return jsonResponse({ error: { code, message, details: [] } }, status);
}

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  const calls: string[] = [];
  const bodies: { url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    calls.push(key);
    if (init?.body != null) {
      bodies.push({ url: key, body: JSON.parse(String(init.body)) });
    }
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return apiError("not_found", `no mock for ${key}`, 404);
    }
    return handler(init);
  });
  return { fetchMock, calls, bodies };
}

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

function equityEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

function depositEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

function inflationEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

function fxEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

function fxEmptyScopeEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

function fxUnknownEnvelope(month: typeof MONTH_MAY = MONTH_MAY) {
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

const CALCULATE = "Рассчитать сценарий";

async function selectScenario(user: ReturnType<typeof userEvent.setup>, value: string) {
  await user.selectOptions(screen.getByLabelText("Сценарий"), value);
}

async function runEquity(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
  await user.click(screen.getByRole("button", { name: CALCULATE }));
}

describe("ScenarioLabPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders month + scenario controls and never auto-runs a scenario", async () => {
    const { fetchMock, calls } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Сценарии" })).toBeInTheDocument();
    expect(screen.getByLabelText("Отчётный месяц")).toBeInTheDocument();
    expect(screen.getByLabelText("Сценарий")).toBeInTheDocument();
    // Defaults: latest closed month + equity scenario, but no evaluation yet.
    expect(screen.getByLabelText("Отчётный месяц")).toHaveValue("1");
    expect(screen.getByLabelText("Размер просадки акций, %")).toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.includes("scenario-lab"))).toBe(false);
  });

  it("calculates equity on an explicit action with the canonical payload and renders server values", async () => {
    const user = userEvent.setup();
    const envelope = equityEnvelope();
    const { fetchMock, calls, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();
    expect(calls).toContain("POST /api/months/1/scenario-lab");
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
    ]);

    // Server-stressed value is rendered verbatim: 140 000 ₽, never a client-side
    // recompute of 150 000 × 0.9 = 135 000.
    expect(screen.getAllByText(/140\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/135\s*000/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);

    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Детали по позициям" })
      .closest("section");
    expect(detailPanel).not.toBeNull();
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Сбер"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("ОФЗ"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("Учтено"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("Не применимо"))).toBe(true);
    // Copyable fingerprints are present but secondary.
    expect(screen.getByText("fp-sem-equity")).toBeInTheDocument();
  });

  it("deposit-rate payload targets all eligible deposits and renders forecast impact without touching principal", async () => {
    const user = userEvent.setup();
    const envelope = depositEnvelope();
    const { fetchMock, calls, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "deposit_rate_assumption");
    await user.type(screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %"), "8");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Ставка по вкладам/ }),
    ).toBeInTheDocument();
    expect(calls).toContain("POST /api/months/1/scenario-lab");
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: {
          shock: {
            deposit_rate_assumption: {
              assumed_annual_rate_pct: "8",
              all_eligible_deposits: true,
            },
          },
        },
      },
    ]);

    // Principal/capital is unchanged: liquid capital delta is a plain 0 with an
    // explicit note, while forecast interest rises (600 → 800 ₽/мес).
    expect(screen.getByText("тело вкладов не меняется")).toBeInTheDocument();
    expect(screen.getAllByText(/800\s*₽/).length).toBeGreaterThan(0);
    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Пересчёт прогнозных процентов" })
      .closest("section");
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Вклад Альфа"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("8,0%"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("6,0%"))).toBe(true);
    expect(rows.some((row) => /120\s*000\s*₽/.test(row.textContent ?? ""))).toBe(true);
  });

  it("inflation renders nominal vs real rows from the stressed month grid", async () => {
    const user = userEvent.setup();
    const envelope = inflationEnvelope();
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "inflation_real_value");
    await user.type(screen.getByLabelText("Годовая инфляция, %"), "12");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /Май\s*2030\s*·\s*Инфляция и реальная стоимость/,
      }),
    ).toBeInTheDocument();
    expect(bodies[0].body).toEqual({
      shock: { inflation_real_value: { annual_inflation_pct: "12" } },
    });

    const gridPanel = screen
      .getByRole("heading", { level: 2, name: "Номинал против реальной стоимости" })
      .closest("section");
    const rows = within(gridPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => /Май\s*2030/.test(row.textContent ?? ""))).toBe(true);
    expect(rows.some((row) => /Апрель\s*2031/.test(row.textContent ?? ""))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("11 мес."))).toBe(true);
    // Real purchasing-power value comes from the server row (537.79 ₽) — never recomputed.
    expect(screen.getAllByText(/537,79\s*₽/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/600\s*₽/).length).toBeGreaterThan(0);
  });

  it("FX unavailable state is prominent and never rendered as an exact zero-impact success", async () => {
    const user = userEvent.setup();
    const envelope = fxEnvelope();
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "fx_translation_shock");
    await user.type(screen.getByLabelText("Изменение стоимости в отчёте, %"), "10");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Валютный шок/ }),
    ).toBeInTheDocument();
    expect(bodies[0].body).toEqual({
      shock: { fx_translation_shock: { target_currency: "USD", reporting_value_change_pct: "10" } },
    });

    // Explicit limitation callout, machine reason code survives into the UI.
    expect(screen.getByText("Недоступен точный пересчёт")).toBeInTheDocument();
    expect(screen.getAllByText("fx_translation_basis_unavailable").length).toBeGreaterThan(0);
    // The other two FX states must not leak into an unavailable result.
    expect(screen.queryByText("Нет данных для точного пересчёта")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет позиций в валюте шока")).not.toBeInTheDocument();
    // Candidate scope is explicit, not a success.
    expect(screen.getByText(/Кандидаты \(валюта совпадает\):/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Недоступно$/).length).toBeGreaterThan(0);
    // Numeric base is shown without an implied stressed revaluation.
    expect(screen.getByText("точный стресс-пересчёт недоступен")).toBeInTheDocument();
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);
    // No fabricated “impact” numbers for an unavailable aggregate.
    expect(screen.queryByText(/Известный скоуп · влияние/)).not.toBeInTheDocument();
    // Row-level candidate status explains the limitation.
    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Кандидаты и доступность пересчёта" })
      .closest("section");
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Кандидат · пересчёт недоступен"))).toBe(
      true,
    );
    expect(rows.some((row) => row.textContent?.includes("Акция США"))).toBe(true);
  });

  it("FX empty affected scope renders a supported zero no-op without the unavailable callout", async () => {
    const user = userEvent.setup();
    const envelope = fxEmptyScopeEnvelope();
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "fx_translation_shock");
    await user.type(screen.getByLabelText("Изменение стоимости в отчёте, %"), "10");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Валютный шок/ }),
    ).toBeInTheDocument();
    expect(bodies[0].body).toEqual({
      shock: { fx_translation_shock: { target_currency: "USD", reporting_value_change_pct: "10" } },
    });

    // No unavailable/unknown limitation: the affected scope is empty and supported.
    expect(screen.queryByText("Недоступен точный пересчёт")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет данных для точного пересчёта")).not.toBeInTheDocument();
    expect(screen.queryByText("fx_translation_basis_unavailable")).not.toBeInTheDocument();
    // Explicit no-matching-candidates no-op message naming the target currency.
    expect(screen.getByText("Нет позиций в валюте шока")).toBeInTheDocument();
    expect(screen.getByText(/выбранной валютой USD/)).toBeInTheDocument();
    // Supported zero result stays visible: calculated badges, base money, known-scope impact.
    expect(screen.getAllByText(/^Рассчитано$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Известный скоуп · влияние/)).toBeInTheDocument();
    expect(screen.queryByText("точный стресс-пересчёт недоступен")).not.toBeInTheDocument();
  });

  it("FX unknown currency metadata renders an unknown limitation, not zero certainty", async () => {
    const user = userEvent.setup();
    const envelope = fxUnknownEnvelope();
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "fx_translation_shock");
    await user.type(screen.getByLabelText("Изменение стоимости в отчёте, %"), "10");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Валютный шок/ }),
    ).toBeInTheDocument();
    expect(bodies[0].body).toEqual({
      shock: { fx_translation_shock: { target_currency: "USD", reporting_value_change_pct: "10" } },
    });

    // Unknown state is visible and distinct from both unavailable and empty-scope.
    expect(screen.queryByText("Недоступен точный пересчёт")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет позиций в валюте шока")).not.toBeInTheDocument();
    expect(screen.getByText("Нет данных для точного пересчёта")).toBeInTheDocument();
    expect(screen.getAllByText("missing_currency").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^Неизвестно$/).length).toBeGreaterThan(0);
    // Empty-scope zero-certainty message must not appear for unknown data.
    expect(
      screen.queryByText(/точный эффект сценария для этого снимка — 0/),
    ).not.toBeInTheDocument();
  });

  it("shows deterministic machine-readable validation errors", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () =>
        apiError("invalid_drawdown_pct", "drawdown_pct must be between 0 and 100"),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось выполнить запрос");
    expect(alert).toHaveTextContent("drawdown_pct must be between 0 and 100");
    expect(alert).toHaveTextContent("код: invalid_drawdown_pct");
  });

  it("switching scenario resets the incompatible previous result", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(equityEnvelope()),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();

    await selectScenario(user, "deposit_rate_assumption");
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    // Export is not offered for a result that no longer matches the controls.
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });

  it("changing the reporting month invalidates the visible prior result", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(equityEnvelope()),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "2");
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
  });

  it("export calls /export with the same scenario payload and triggers the owner download", async () => {
    const user = userEvent.setup();
    const envelope = equityEnvelope();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:scenario-lab");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
      "POST /api/months/1/scenario-lab/export": () =>
        new Response(JSON.stringify(envelope), {
          status: 200,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="scenario_lab_2030-05_equity_drawdown.json"',
          },
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    const exportButton = await screen.findByRole("button", { name: "Скачать JSON" });
    expect(exportButton).toBeEnabled();
    await user.click(exportButton);

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
      {
        url: "POST /api/months/1/scenario-lab/export",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
    ]);
    expect(anchorClick.mock.instances[0]).toHaveProperty(
      "download",
      "scenario_lab_2030-05_equity_drawdown.json",
    );
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:scenario-lab");
    expect(
      await screen.findByText(/Файл scenario_lab_2030-05_equity_drawdown\.json скачан/),
    ).toBeInTheDocument();
  });

  it("keeps the export action disabled until a matching result exists", async () => {
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });

  it("FX signed validation allows -10 and 150 (no positive cap, lower bound -100)", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "fx_translation_shock");
    const pctInput = screen.getByLabelText("Изменение стоимости в отчёте, %");
    const calcButton = screen.getByRole("button", { name: "Рассчитать сценарий" });
    expect(calcButton).toBeDisabled();
    await user.clear(pctInput);
    await user.type(pctInput, "-10");
    expect(calcButton).toBeEnabled();
    await user.clear(pctInput);
    await user.type(pctInput, "150");
    expect(calcButton).toBeEnabled();
    await user.clear(pctInput);
    await user.type(pctInput, "-101");
    expect(calcButton).toBeDisabled();
  });

  it("deposit and inflation accept large values without artificial 100 cap", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "deposit_rate_assumption");
    const depositInput = screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %");
    await user.type(depositInput, "250");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();

    await selectScenario(user, "inflation_real_value");
    const inflationInput = screen.getByLabelText("Годовая инфляция, %");
    await user.type(inflationInput, "250");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();
  });

  it("does not publish stale result when reporting month changes during pending calculation", async () => {
    const user = userEvent.setup();
    let resolvePending: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolvePending = resolve;
    });
    const envelope = equityEnvelope();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => pending,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    // While pending, switch month to June (id 2).
    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "2");
    // Resolve the stale request for month 1 — must be ignored.
    resolvePending(jsonResponse(envelope));
    await new Promise((r) => setTimeout(r, 50));
    expect(
      screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
  });

  it("does not publish stale result when scenario or parameters change during pending calculation", async () => {
    const user = userEvent.setup();
    let resolvePending: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolvePending = resolve;
    });
    const envelope = equityEnvelope();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => pending,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    // Change scenario while pending — invalidates stale equity result.
    await selectScenario(user, "deposit_rate_assumption");
    resolvePending(jsonResponse(envelope));
    await new Promise((r) => setTimeout(r, 50));
    expect(
      screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    // Deposit controls are visible, equity stale result is gone.
    expect(
      screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %"),
    ).toBeInTheDocument();
  });
});
