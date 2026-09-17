import type { GuidedCloseStep, MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { GoalSummary } from "../api/goals";
import type {
  CapitalCompositionHistory,
  ClosedReportComparison,
  DashboardKpis,
  PassiveIncomeHistory,
  ReportingMonth,
} from "../api/types";

// Entirely fictional data; shared by component and intercepted-browser tests only.
export const uiV2Months: ReportingMonth[] = [
  { id: 91, year: 2031, month: 7, status: "closed", snapshot_date: "2031-07-31", source: "manual" },
  { id: 12, year: 2031, month: 8, status: "draft", snapshot_date: "2031-08-30", source: "manual" },
  { id: 90, year: 2031, month: 5, status: "closed", snapshot_date: "2031-05-31", source: "manual" },
  { id: 89, year: 2031, month: 4, status: "closed", snapshot_date: "2031-04-30", source: "manual" },
  { id: 88, year: 2031, month: 2, status: "closed", snapshot_date: "2031-02-28", source: "manual" },
];

function money(amount: string) {
  return { amount, currency: "RUB" };
}

const allocation = (offset = 0) => [
  { asset_class: "cash", amount: money(`${803900 + offset}.00`) },
  { asset_class: "deposits", amount: money("1000000.00") },
  { asset_class: "stocks", amount: money("610000.00") },
  { asset_class: "bonds", amount: money("790000.00") },
  { asset_class: "gold_other", amount: money("0.00") },
];

export function makeUiV2Comparison({
  firstClosed = false,
  zero = false,
}: {
  firstClosed?: boolean;
  zero?: boolean;
} = {}): ClosedReportComparison {
  const current = {
    reporting_month_id: 91,
    year: 2031,
    month: 7,
    status: "closed" as const,
    snapshot_date: "2031-07-31",
    allocation: zero
      ? allocation().map((item) => ({ ...item, amount: money("0.00") }))
      : allocation(),
    liquid_assets_total: money(zero ? "0.00" : "3203900.00"),
    included_debts: money(zero ? "0.00" : "400000.00"),
    liquid_capital_net: money(zero ? "0.00" : "2803900.00"),
    linked_pair_assets: money("0.00"),
    linked_pair_debts: money("0.00"),
    linked_pair_net_contribution: money("0.00"),
  };
  const previous = {
    ...current,
    reporting_month_id: 90,
    year: 2031,
    month: 5,
    snapshot_date: "2031-05-31",
    allocation: allocation(-52600),
    liquid_assets_total: money("3151300.00"),
    included_debts: money("390000.00"),
    liquid_capital_net: money("2761300.00"),
  };
  return {
    comparison_basis: "latest_closed_to_previous_closed",
    availability: firstClosed ? "previous_closed_report_unavailable" : "available",
    asset_classes: ["cash", "deposits", "stocks", "bonds", "gold_other"],
    current,
    previous: firstClosed ? null : previous,
    asset_class_deltas: firstClosed
      ? null
      : zero
        ? [
            { asset_class: "cash", amount: money("-751300.00") },
            { asset_class: "deposits", amount: money("-1000000.00") },
            { asset_class: "stocks", amount: money("-610000.00") },
            { asset_class: "bonds", amount: money("-790000.00") },
            { asset_class: "gold_other", amount: money("0.00") },
          ]
        : [
            { asset_class: "cash", amount: money("52600.00") },
            { asset_class: "deposits", amount: money("0.00") },
            { asset_class: "stocks", amount: money("0.00") },
            { asset_class: "bonds", amount: money("0.00") },
            { asset_class: "gold_other", amount: money("0.00") },
          ],
    liquid_assets_total_delta: firstClosed ? null : money(zero ? "-3151300.00" : "52600.00"),
    included_debts_delta: firstClosed ? null : money(zero ? "-390000.00" : "10000.00"),
    liquid_capital_net_delta: firstClosed ? null : money(zero ? "-2761300.00" : "42600.00"),
    linked_pair_assets_delta: firstClosed ? null : money("0.00"),
    linked_pair_debts_delta: firstClosed ? null : money("0.00"),
    linked_pair_net_contribution_delta: firstClosed ? null : money("0.00"),
    net_liquid_capital_reconciles: firstClosed ? null : true,
  };
}

export function makeUiV2CapitalHistory({
  firstClosed = false,
  zero = false,
}: {
  firstClosed?: boolean;
  zero?: boolean;
} = {}): CapitalCompositionHistory {
  const allPoints = [
    {
      id: 88,
      year: 2031,
      month: 2,
      snapshotDate: "2031-02-28",
      cash: "600000.00",
      assets: "3000000.00",
      debts: "400000.00",
      net: "2600000.00",
    },
    {
      id: 89,
      year: 2031,
      month: 4,
      snapshotDate: "2031-04-30",
      cash: "710000.00",
      assets: "3110000.00",
      debts: "400000.00",
      net: "2710000.00",
    },
    {
      id: 90,
      year: 2031,
      month: 5,
      snapshotDate: "2031-05-31",
      cash: "751300.00",
      assets: "3151300.00",
      debts: "390000.00",
      net: "2761300.00",
    },
    {
      id: 91,
      year: 2031,
      month: 7,
      snapshotDate: "2031-07-31",
      cash: "803900.00",
      assets: "3203900.00",
      debts: "400000.00",
      net: "2803900.00",
    },
  ].map((point) => {
    const zeroLatest = zero && point.id === 91;
    return {
      reporting_month_id: point.id,
      year: point.year,
      month: point.month,
      snapshot_date: point.snapshotDate,
      allocation: zeroLatest
        ? allocation().map((item) => ({ ...item, amount: money("0.00") }))
        : allocation(Number(point.cash.slice(0, -3)) - 803900),
      liquid_assets_total: money(zeroLatest ? "0.00" : point.assets),
      included_debts: money(zeroLatest ? "0.00" : point.debts),
      liquid_capital_net: money(zeroLatest ? "0.00" : point.net),
    };
  });
  const points = firstClosed ? allPoints.slice(-1) : allPoints;
  return {
    asset_classes: ["cash", "deposits", "stocks", "bonds", "gold_other"],
    points,
  };
}

export function makeUiV2PassiveHistory({
  firstClosed = false,
  zero = false,
}: {
  firstClosed?: boolean;
  zero?: boolean;
} = {}): PassiveIncomeHistory {
  const actual = zero ? "0.00" : "17500.00";
  const allPoints = [
    {
      reporting_month_id: 88,
      year: 2031,
      month: 2,
      snapshot_date: "2031-02-28",
      passive_income_actual: money("12800.00"),
      included_in_average_window: true,
    },
    {
      reporting_month_id: 89,
      year: 2031,
      month: 4,
      snapshot_date: "2031-04-30",
      passive_income_actual: money("15300.00"),
      included_in_average_window: true,
    },
    {
      reporting_month_id: 90,
      year: 2031,
      month: 5,
      snapshot_date: "2031-05-31",
      passive_income_actual: money("15600.00"),
      included_in_average_window: true,
    },
    {
      reporting_month_id: 91,
      year: 2031,
      month: 7,
      snapshot_date: "2031-07-31",
      passive_income_actual: money(actual),
      included_in_average_window: true,
    },
  ];
  const points = firstClosed ? allPoints.slice(-1) : allPoints;
  const monthsUsed = firstClosed ? ["2031-07"] : ["2031-02", "2031-04", "2031-05", "2031-07"];
  return {
    points,
    average: {
      average: money(firstClosed ? actual : zero ? "10925.00" : "15300.00"),
      count_months: firstClosed ? 1 : 4,
      target_window_months: 12,
      is_complete_12m: false,
      configured_start_month: null,
      months_used: monthsUsed,
    },
    latest_closed_report_id: 91,
    selected_report: {
      reporting_month_id: 91,
      year: 2031,
      month: 7,
      snapshot_date: "2031-07-31",
      passive_income_actual: money(actual),
      breakdown: {
        deposit_interest: money(zero ? "0.00" : "8500.00"),
        bond_coupons: money(zero ? "0.00" : "5000.00"),
        dividends: money(zero ? "0.00" : "4000.00"),
        other_capital_income: money("0.00"),
        total_net_passive_income: money(actual),
      },
    },
  };
}

export function makeUiV2Goals({
  firstClosed = false,
  zero = false,
}: {
  firstClosed?: boolean;
  zero?: boolean;
} = {}): GoalSummary[] {
  const passiveCurrent = firstClosed
    ? zero
      ? "0.00"
      : "17500.00"
    : zero
      ? "10925.00"
      : "15300.00";
  const passiveProgress = firstClosed ? (zero ? "0.00" : "35.00") : zero ? "21.85" : "30.60";
  const passiveRemaining = firstClosed
    ? zero
      ? "50000.00"
      : "32500.00"
    : zero
      ? "39075.00"
      : "34700.00";
  const passiveMonths = firstClosed ? ["2031-07"] : ["2031-02", "2031-04", "2031-05", "2031-07"];
  const baseForecast = {
    reporting_month_id: 91,
    as_of_date: "2031-07-31",
    method_version: "goal_achievement_v1" as const,
    source_forecast_version: null,
    status: "not_projectable" as const,
    reason_code: null,
    remaining_amount: money("2196100.00"),
    estimated_achievement_date: null,
    is_approximate: false,
    warnings: [],
    passive_income_history_start_month: null,
    passive_income_months_used: [],
    passive_income_months_count: 0,
    passive_income_months_complete: false,
  };
  return [
    {
      id: 1,
      name: "Резервный капитал",
      goal_type: "capital",
      target_value: money("5000000.00"),
      target_date: null,
      is_active: true,
      is_main: false,
      calculation_mode: "liquid_capital_net",
      notes: null,
      achievement_forecast: {
        ...baseForecast,
        goal_id: 1,
        current_value: money(zero ? "0.00" : "2803900.00"),
        target_value: money("5000000.00"),
        remaining_amount: money(zero ? "5000000.00" : "2196100.00"),
        progress_pct: zero ? "0.00" : "56.08",
      },
    },
    {
      id: 2,
      name: "Пассивный доход",
      goal_type: "passive_income",
      target_value: money("50000.00"),
      target_date: null,
      is_active: true,
      is_main: true,
      calculation_mode: "monthly_net_passive_income",
      notes: null,
      achievement_forecast: {
        ...baseForecast,
        goal_id: 2,
        current_value: money(passiveCurrent),
        target_value: money("50000.00"),
        remaining_amount: money(passiveRemaining),
        progress_pct: passiveProgress,
        passive_income_months_used: passiveMonths,
        passive_income_months_count: firstClosed ? 1 : 4,
      },
    },
  ];
}

export function makeUiV2Workflow({
  monthId = 12,
  blocked = false,
  unavailable = false,
  zeroIncome = false,
}: {
  monthId?: number;
  blocked?: boolean;
  unavailable?: boolean;
  zeroIncome?: boolean;
} = {}): MonthCloseWorkflow {
  const month = uiV2Months.find((candidate) => candidate.id === monthId);
  if (!month) throw new Error("Unknown synthetic month");
  const closed = month.status === "closed";
  const freshness = {
    available: true,
    evaluated_on: "2031-09-01",
    quote_valuation_target_date: month.snapshot_date,
    families: [],
    reason_codes: [],
  };
  const kpis: DashboardKpis = {
    liquid_capital_net: money(monthId === 12 ? "2846500.00" : "2803900.00"),
    liquid_capital_delta: money("42600.00"),
    passive_income_actual: money(zeroIncome ? "0.00" : "17500.00"),
    passive_income_delta: money("1100.00"),
    forecast_monthly_passive_income: money("21000.00"),
    forecast_annual_passive_income: money("252000.00"),
    passive_income_average: money("16400.00"),
    passive_income_average_months: 7,
    passive_income_average_complete: false,
    goal_progress_pct: "42.00",
    goal_target: money("50000.00"),
    mandatory_expenses: money("60000.00"),
    mandatory_expense_coverage_pct: "35.00",
    actual_mandatory_expense_coverage_pct: zeroIncome ? "0.00" : "29.16",
    mortgage_balance: money("1700000.00"),
    mortgage_coverage_pct: "167.44",
  };
  const definitions: Array<{
    id: GuidedCloseStep["id"];
    title: string;
    action: NonNullable<GuidedCloseStep["primary_action"]>["id"];
    label: string;
    why: string;
  }> = [
    {
      id: "month_setup",
      title: "Проверить дату снимка",
      action: "set_snapshot_date",
      label: "Изменить дату снимка",
      why: "Дата снимка сохранена. Она может отличаться от конца отчётного месяца.",
    },
    {
      id: "alfa_baseline",
      title: "Сверить состав портфеля",
      action: "open_alfa_preview",
      label: "Открыть предпросмотр Alfa",
      why: "Проверь, что позиции и остатки соответствуют выбранной дате. Загрузка и применение данных требуют отдельных подтверждений.",
    },
    {
      id: "market_quotes",
      title: "Проверить оценку активов",
      action: "open_quote_preview",
      label: "Открыть проверку котировок",
      why: "Котировки не обновляются при открытии этой страницы.",
    },
    {
      id: "actual_payouts",
      title: "Проверить полученные выплаты",
      action: "choose_statement_file",
      label: "Выбрать выписку с выплатами",
      why: "Отдели доход от пополнений и возврата номинала.",
    },
    {
      id: "future_payouts",
      title: "Посмотреть будущие выплаты",
      action: "open_payout_batch_preview",
      label: "Открыть календарь выплат",
      why: "Будущие выплаты — ожидания, а не полученный доход.",
    },
    {
      id: "broker_reconciliation",
      title: "Проверить расхождения портфеля",
      action: "open_reconciliation_preview",
      label: "Открыть сверку",
      why: "Сравнение не меняет сохранённые данные.",
    },
    {
      id: "readiness",
      title: "Проверить готовность месяца",
      action: "open_freshness",
      label: "Открыть проверки данных",
      why: "Обязательные исправления и предупреждения имеют разный смысл.",
    },
    {
      id: "final_review_close",
      title: "Проверить итоги и закрыть месяц",
      action: "open_final_review",
      label: "Открыть итоговую проверку",
      why: "Закрытие выполняется только после явного подтверждения.",
    },
    {
      id: "next_month_outlook",
      title: "Посмотреть следующий месяц",
      action: "open_cash_flow_ladder",
      label: "Открыть будущие события",
      why: "Сохранённый месяц остаётся закрытым.",
    },
  ];
  const steps: GuidedCloseStep[] = definitions.map((definition, index) => ({
    id: definition.id,
    order: index + 1,
    title: definition.title,
    state: closed || index === 0 ? "completed" : index === 1 ? "warning" : "ready",
    applicability: index === 8 && !closed ? "not_applicable" : "mandatory",
    gate: "advisory",
    affects_close: false,
    why: definition.why,
    reason_codes: [],
    primary_action: { id: definition.action, label: definition.label, target: "internal_route" },
    secondary_actions: [],
    completion_basis: null,
    evidence_scope: "none",
    evidence_version: null,
    evidence_summary: {},
    stale: { is_stale: false, reason_codes: [] },
    diagnostics: {},
  }));
  if (blocked) {
    steps[6] = { ...steps[6], state: "blocked", gate: "must_resolve", affects_close: true };
  }
  if (closed) steps[8] = { ...steps[8], state: "ready" };
  const items = [
    {
      severity: "warning" as const,
      code: "synthetic_budget_review",
      message: "Проверь обязательные расходы за месяц.",
      context: {},
    },
    {
      severity: "warning" as const,
      code: "synthetic_manual_prices",
      message: "Часть оценок активов задана вручную.",
      context: {},
    },
    ...(blocked
      ? [
          {
            severity: "hard_blocker" as const,
            code: "synthetic_missing_evidence",
            message: "Добавь недостающее подтверждение данных.",
            context: {},
          },
        ]
      : []),
  ];
  return {
    contract_version: "monthly_close_workflow_v1",
    generated_at: "2031-09-01T09:00:00Z",
    month: { ...month },
    recommended_step_id: closed ? "next_month_outlook" : blocked ? "readiness" : "alfa_baseline",
    progress: { completed_or_skipped: closed ? 8 : 1, total_applicable: closed ? 9 : 8 },
    steps,
    readiness: {
      can_close: !blocked,
      hard_blocker_count: blocked ? 1 : 0,
      warning_count: 2,
      reason_codes: [],
    },
    freshness,
    final_review: unavailable
      ? { available: false, reason_code: "synthetic_unavailable" }
      : {
          available: true,
          reason_code: null,
          month_header: { ...month },
          kpis,
          assets_and_cash: {
            available: true,
            reason_code: null,
            liquid_capital: {
              total_assets: money(monthId === 12 ? "3246500.00" : "3203900.00"),
              total_debts_included: money("400000.00"),
              liquid_capital_net: kpis.liquid_capital_net,
              breakdown: {
                cash: money(monthId === 12 ? "1246500.00" : "1203900.00"),
                deposits: money("1000000.00"),
                securities: money("1000000.00"),
                other_liquid_assets: money("0.00"),
              },
              accounts: [],
            },
            current_cash: money(monthId === 12 ? "1246500.00" : "1203900.00"),
            cash_row_count: 1,
          },
          debts_and_property: {
            available: true,
            reason_code: null,
            debt_total: money("400000.00"),
            property_value: money("3500000.00"),
            mortgage_balance: money("1700000.00"),
            debt_row_count: 1,
            property_row_count: 1,
          },
          investments: {
            available: true,
            reason_code: null,
            position_count: 2,
            market_value: money("1000000.00"),
            manual_price_count: 1,
            actual_flow_count: 1,
            future_flow_count: 0,
            by_instrument_class: [],
          },
          actual_passive_income: kpis.passive_income_actual,
          important_future_events: {
            available: false,
            reason_code: "no_known_dated_events",
            upcoming_14_days: null,
            upcoming_30_days: null,
            next_month: null,
            known_event_count: 0,
          },
          provider_summary: [],
          reconciliation_availability: {},
          freshness_summary: freshness,
          close_readiness: {
            year: month.year,
            month: month.month,
            status: month.status,
            snapshot_date: month.snapshot_date,
            source: "manual",
            can_close: !blocked,
            items,
          },
          manual_review_cards: [],
          manual_attention: [],
          evidence_version: "ui-v2-synthetic-v1",
        },
    outlook: null,
    links: {
      month: `/months/${monthId}`,
      close_readiness: `/api/months/${monthId}/close-readiness`,
      freshness: `/api/months/${monthId}/freshness-provenance`,
    },
  };
}
