import type { GuidedCloseStep, MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { GoalSummary } from "../api/goals";
import type { RiskAllocationResponse } from "../api/riskAllocation";
import type {
  Account,
  CapitalCompositionHistory,
  CashBalance,
  ClosedReportComparison,
  DashboardKpis,
  DebtEntry,
  DepositSnapshot,
  Instrument,
  PassiveIncomeHistory,
  PerformanceAttribution,
  PortfolioTwrr,
  PortfolioXirr,
  PositionSnapshot,
  PropertySnapshot,
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
      linked_pair_assets: money("0.00"),
      linked_pair_debts: money("0.00"),
      linked_pair_net_contribution: money("0.00"),
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
          reconciliation_availability: {
            available: false,
            reason_code: "reconciliation_not_run",
          },
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

/* ------------------------------------------------------------------ *
 * UI v2 Capital fixtures.
 *
 * Entirely fictional 2031 data. Rows are deliberately not a substitute for
 * the backend totals: Capital shows row amounts as they are stored, and the
 * headline numbers come from the comparison read model.
 * ------------------------------------------------------------------ */

export const uiV2CapitalMonthId = 91;
export const uiV2CapitalPreviousMonthId = 90;
export const uiV2PriorYearClosedMonthId = 87;
export const uiV2LongHistoryFirstMonthId = 100;

/**
 * Sixteen consecutive CLOSED months (2030-01 … 2031-04) so a selected report can
 * be older than the latest twelve CLOSED reports. Fictional data.
 */
export function makeUiV2LongHistory({ count = 16 }: { count?: number } = {}): {
  history: CapitalCompositionHistory;
  months: ReportingMonth[];
} {
  const months: ReportingMonth[] = [];
  const points: CapitalCompositionHistory["points"] = [];
  for (let index = 0; index < count; index += 1) {
    const year = 2030 + Math.floor(index / 12);
    const month = (index % 12) + 1;
    const snapshotDate = `${year}-${String(month).padStart(2, "0")}-28`;
    const assets = 3203900 + index * 10000;
    months.push({
      id: uiV2LongHistoryFirstMonthId + index,
      year,
      month,
      status: "closed",
      snapshot_date: snapshotDate,
      source: "manual",
    });
    points.push({
      reporting_month_id: uiV2LongHistoryFirstMonthId + index,
      year,
      month,
      snapshot_date: snapshotDate,
      allocation: allocation(index * 10000),
      liquid_assets_total: money(`${assets}.00`),
      included_debts: money("400000.00"),
      liquid_capital_net: money(`${assets - 400000}.00`),
      linked_pair_assets: money("0.00"),
      linked_pair_debts: money("0.00"),
      linked_pair_net_contribution: money("0.00"),
    });
  }
  return {
    history: {
      asset_classes: ["cash", "deposits", "stocks", "bonds", "gold_other"],
      points,
    },
    months,
  };
}

/**
 * Archive fixtures: the accepted set plus one prior-year CLOSED month, so year
 * grouping and the inter-year gap bounds are exercised without touching the
 * Home/Capital fixtures.
 */
export const uiV2ArchiveMonths: ReportingMonth[] = [
  ...uiV2Months,
  {
    id: uiV2PriorYearClosedMonthId,
    year: 2030,
    month: 11,
    status: "closed",
    snapshot_date: "2030-11-30",
    source: "manual",
  },
];

export function makeUiV2ArchiveHistory(): CapitalCompositionHistory {
  const base = makeUiV2CapitalHistory();
  const prior = {
    reporting_month_id: uiV2PriorYearClosedMonthId,
    year: 2030,
    month: 11,
    snapshot_date: "2030-11-30",
    allocation: allocation(-303900),
    liquid_assets_total: money("2900000.00"),
    included_debts: money("300000.00"),
    liquid_capital_net: money("2600000.00"),
    linked_pair_assets: money("0.00"),
    linked_pair_debts: money("0.00"),
    linked_pair_net_contribution: money("0.00"),
  };
  return {
    asset_classes: base.asset_classes,
    points: [prior, ...base.points],
  };
}

export const uiV2Accounts: Account[] = [
  {
    id: 1,
    name: "Синтетический депозитный счёт",
    account_type: "deposit",
    status: "active",
    external_code: null,
    include_in_capital: true,
    include_in_returns: true,
    notes: null,
  },
  {
    id: 2,
    name: "Синтетический старый вклад",
    account_type: "deposit",
    status: "active",
    external_code: null,
    include_in_capital: false,
    include_in_returns: false,
    notes: null,
  },
  {
    id: 3,
    name: "Синтетический брокерский счёт",
    account_type: "brokerage",
    status: "active",
    external_code: null,
    include_in_capital: true,
    include_in_returns: true,
    notes: null,
  },
  {
    id: 4,
    name: "Синтетический брокерский счёт вне капитала",
    account_type: "brokerage",
    status: "active",
    external_code: null,
    include_in_capital: false,
    include_in_returns: false,
    notes: null,
  },
];

export const uiV2Instruments: Instrument[] = [
  {
    id: 10,
    name: "Синтетическая акция",
    instrument_type: "stock",
    isin: null,
    ticker: "SYN1",
    moex_secid: null,
    currency: "RUB",
    nominal_value: null,
    is_active: true,
    manual_price_allowed: true,
    notes: null,
  },
  {
    id: 11,
    name: "Синтетическая облигация",
    instrument_type: "bond",
    isin: null,
    ticker: "SYN2",
    moex_secid: null,
    currency: "RUB",
    nominal_value: null,
    is_active: true,
    manual_price_allowed: true,
    notes: null,
  },
  {
    id: 13,
    name: "Синтетический фонд",
    instrument_type: "fund",
    isin: null,
    ticker: "SYN3",
    moex_secid: null,
    currency: "RUB",
    nominal_value: null,
    is_active: true,
    manual_price_allowed: true,
    notes: null,
  },
];

export function makeUiV2Cash({
  excluded = false,
  monthId = uiV2CapitalMonthId,
}: {
  excluded?: boolean;
  monthId?: number;
} = {}): CashBalance[] {
  return [
    {
      id: 701,
      reporting_month_id: monthId,
      account_id: null,
      name: "Синтетический кошелёк",
      amount: money(excluded ? "0.00" : "803900.00"),
      currency: "RUB",
      include_in_capital: true,
      notes: null,
    },
    {
      id: 702,
      reporting_month_id: monthId,
      account_id: 2,
      name: "Синтетическая касса",
      amount: money("20000.00"),
      currency: "RUB",
      include_in_capital: false,
      notes: null,
    },
  ];
}

export function makeUiV2Deposits({
  monthId = uiV2CapitalMonthId,
}: {
  monthId?: number;
} = {}): DepositSnapshot[] {
  return [
    {
      id: 601,
      reporting_month_id: monthId,
      account_id: 1,
      name: "Синтетический вклад",
      deposit_type: "deposit",
      balance: money("1000000.00"),
      annual_rate: "8.10",
      expected_monthly_interest: money("6750.00"),
      actual_interest_received: money("6750.00"),
      notes: null,
      updated_at: "2031-07-31T12:00:00",
    },
    {
      id: 602,
      reporting_month_id: monthId,
      account_id: 2,
      name: "Синтетический старый вклад",
      deposit_type: "savings",
      balance: money("150000.00"),
      annual_rate: "4.00",
      expected_monthly_interest: money("500.00"),
      actual_interest_received: money("0.00"),
      notes: null,
      updated_at: "2031-07-31T12:00:00",
    },
  ];
}

export function makeUiV2Positions({
  monthId = uiV2CapitalMonthId,
}: {
  monthId?: number;
} = {}): PositionSnapshot[] {
  return [
    {
      id: 501,
      reporting_month_id: monthId,
      account_id: 3,
      instrument_id: 10,
      quantity: "1000.000000",
      average_cost_per_unit: money("500.00"),
      market_price_per_unit: money("610.00"),
      market_value: money("610000.00"),
      cost_basis: money("500000.00"),
      unrealized_result: money("110000.00"),
      accrued_interest: null,
      price_source: "manual",
      price_date: "2031-07-31",
      notes: null,
      updated_at: "2031-07-31T12:00:00",
    },
    {
      id: 502,
      reporting_month_id: monthId,
      account_id: 3,
      instrument_id: 11,
      quantity: "790.000000",
      average_cost_per_unit: money("1000.00"),
      market_price_per_unit: money("1000.00"),
      market_value: money("790000.00"),
      cost_basis: money("790000.00"),
      unrealized_result: money("0.00"),
      accrued_interest: null,
      price_source: "manual",
      price_date: "2031-07-31",
      notes: null,
      updated_at: "2031-07-31T12:00:00",
    },
    {
      id: 503,
      reporting_month_id: monthId,
      account_id: 4,
      instrument_id: 13,
      quantity: "250.000000",
      average_cost_per_unit: money("1000.00"),
      market_price_per_unit: money("1000.00"),
      market_value: money("250000.00"),
      cost_basis: money("250000.00"),
      unrealized_result: money("0.00"),
      accrued_interest: null,
      price_source: "manual",
      price_date: "2031-07-31",
      notes: null,
      updated_at: "2031-07-31T12:00:00",
    },
  ];
}

export function makeUiV2Debts({ linkedOnly = false }: { linkedOnly?: boolean } = {}): DebtEntry[] {
  const debts: DebtEntry[] = [
    {
      id: 21,
      reporting_month_id: uiV2CapitalMonthId,
      debt_type: "credit_card",
      name: "Синтетическая кредитная карта",
      current_balance: money("400000.00"),
      include_in_liquid_capital: true,
      linked_account_id: 3,
      annual_rate: null,
      next_due_date: null,
      contract_end_date: null,
      notes: null,
    },
    {
      id: 22,
      reporting_month_id: uiV2CapitalMonthId,
      debt_type: "other",
      name: "Синтетический кредит без факта актива",
      current_balance: money("120000.00"),
      include_in_liquid_capital: false,
      linked_account_id: 2,
      annual_rate: null,
      next_due_date: null,
      contract_end_date: null,
      notes: null,
    },
  ];
  return linkedOnly ? debts.slice(0, 1) : debts;
}

export function makeUiV2Properties({
  empty = false,
}: {
  empty?: boolean;
} = {}): PropertySnapshot[] {
  if (empty) return [];
  return [
    {
      id: 301,
      reporting_month_id: uiV2CapitalMonthId,
      name: "Синтетическая квартира",
      estimated_value: money("3500000.00"),
      mortgage_balance: money("1700000.00"),
      monthly_payment: money("45000.00"),
      mortgage_annual_rate: null,
      notes: null,
    },
  ];
}

export function makeUiV2Dashboard({
  coveragePct = "164.9",
  gapAmount = "1103900.00",
  mortgageClosed = false,
  noPairs = false,
}: {
  coveragePct?: string | null;
  gapAmount?: string;
  mortgageClosed?: boolean;
  noPairs?: boolean;
} = {}) {
  const month = uiV2Months.find((candidate) => candidate.id === uiV2CapitalMonthId);
  if (!month) throw new Error("Synthetic closed month is missing");
  return {
    month,
    mortgage: {
      mortgage_balance: money(mortgageClosed ? "0.00" : "1700000.00"),
      coverage_pct: mortgageClosed ? null : coveragePct,
      gap: money(mortgageClosed ? "0.00" : gapAmount),
    },
    summary: {
      forecast: {
        breakdown: {
          expected_deposit_interest: money("6750.00"),
          expected_coupon_net: money("5000.00"),
          expected_dividend_component: money("4000.00"),
          other_expected_capital_income: money("0.00"),
        },
        is_approximate: false,
        warnings: [],
      },
      liquid_capital: {
        linked_pairs: noPairs
          ? []
          : [
              {
                debt_id: 21,
                debt_name: "Синтетическая кредитная карта",
                debt_type: "credit_card",
                debt_balance: money("400000.00"),
                account_id: 3,
                account_name: "Синтетический брокерский счёт",
                account_type: "brokerage",
                account_balance: money("1400000.00"),
                net_contribution: money("1000000.00"),
              },
            ],
      },
    },
  };
}

export function makeUiV2RiskAllocation({
  accountSupport = "supported",
  unsupportedPositions = false,
  monthId = uiV2CapitalMonthId,
}: {
  accountSupport?: "supported" | "unavailable" | "unknown";
  unsupportedPositions?: boolean;
  monthId?: number;
} = {}): RiskAllocationResponse {
  const support = unsupportedPositions
    ? { status: "unavailable" as const, reason_codes: ["unsupported_position_valuation"] }
    : { status: "supported" as const, reason_codes: [] };
  return {
    reporting_month_id: monthId,
    as_of_date: "2031-07-31",
    base_currency: "RUB",
    liquid_assets_total: money("3203900.00"),
    allocation_by_asset_class: {
      support: { status: "supported", reason_codes: [] },
      denominator: money("3203900.00"),
      covered_amount: money("3203900.00"),
      unallocated_amount: money("0.00"),
      coverage_pct: "100.00",
      items: [],
      excluded: [],
    },
    allocation_by_account: {
      support:
        accountSupport === "supported"
          ? { status: "supported" as const, reason_codes: ["cash_not_account_linked"] }
          : { status: accountSupport, reason_codes: ["bank_identity_not_persisted"] },
      denominator: money("3203900.00"),
      covered_amount: money("2400000.00"),
      unallocated_amount: money("803900.00"),
      coverage_pct: "74.91",
      items: [
        {
          key: "account:1",
          label: "Синтетический депозитный счёт",
          amount: money("1000000.00"),
          share_pct: "31.21",
          account_id: 1,
          instrument_id: null,
          instrument_type: null,
        },
        {
          key: "account:3",
          label: "Синтетический брокерский счёт",
          amount: money("1400000.00"),
          share_pct: "43.70",
          account_id: 3,
          instrument_id: null,
          instrument_type: null,
        },
        {
          key: "unassigned_cash",
          label: "Unassigned cash",
          amount: money("803900.00"),
          share_pct: "25.09",
          account_id: null,
          instrument_id: null,
          instrument_type: null,
        },
      ],
      excluded: [],
    },
    top_positions: {
      support,
      denominator: money("3203900.00"),
      top_n: 5,
      top_amount: money("1400000.00"),
      top_share_pct: "43.70",
      items: unsupportedPositions
        ? []
        : [
            {
              key: "position:502",
              label: "Синтетическая облигация",
              amount: money("790000.00"),
              share_pct: "24.66",
              account_id: 3,
              account_name: "Синтетический брокерский счёт",
              instrument_id: 11,
              instrument_name: "Синтетическая облигация",
              instrument_type: "bond",
              position_id: 502,
              event_count: null,
              is_approximate: false,
            },
            {
              key: "position:501",
              label: "Синтетическая акция",
              amount: money("610000.00"),
              share_pct: "19.04",
              account_id: 3,
              account_name: "Синтетический брокерский счёт",
              instrument_id: 10,
              instrument_name: "Синтетическая акция",
              instrument_type: "stock",
              position_id: 501,
              event_count: null,
              is_approximate: false,
            },
          ],
      excluded: [],
      is_approximate: false,
    },
    payout_concentration: {
      support: { status: "unavailable", reason_codes: ["no_dated_payouts"] },
      denominator: money("0.00"),
      top_n: 5,
      top_amount: money("0.00"),
      top_share_pct: null,
      items: [],
      excluded: [],
      is_approximate: false,
    },
    redemption_concentration: {
      support: { status: "unavailable", reason_codes: ["no_dated_payouts"] },
      denominator: money("0.00"),
      top_n: 5,
      top_amount: money("0.00"),
      top_share_pct: null,
      items: [],
      excluded: [],
      is_approximate: false,
    },
    support: {},
  };
}

export function makeUiV2Performance({
  attributionScope = "portfolio",
  notComputable = false,
}: {
  attributionScope?: "portfolio" | "account";
  notComputable?: boolean;
} = {}): {
  attribution: PerformanceAttribution;
  twrr: PortfolioTwrr;
  xirr: PortfolioXirr;
} {
  const period = { start_date: "2031-05-31", end_date: "2031-07-31" };
  return {
    attribution: {
      contract: "PERF04A",
      contract_version: 1,
      metric: "value_change_after_external_flows",
      grain: "selected_scope",
      scope: attributionScope,
      account_id: attributionScope === "account" ? 3 : null,
      period,
      performance_currency: "RUB",
      availability: notComputable ? "not_computable" : "available",
      quality: notComputable ? "unavailable" : "exact",
      opening_value: notComputable ? null : money("3151300.00"),
      closing_value: notComputable ? null : money("3203900.00"),
      value: notComputable ? null : money("42600.00"),
      external_flow_summary: {
        contributions: money("0.00"),
        withdrawals: money("0.00"),
        signed_total: money("0.00"),
      },
      evidence: {
        opening_valuation: { availability: "available", reason_codes: [] },
        closing_valuation: { availability: "available", reason_codes: [] },
        scope_membership: { status: "complete", reason_codes: [] },
        cash_boundary_coverage: { status: "complete", reason_codes: [] },
        in_kind_boundary_coverage: { status: "complete", reason_codes: [] },
        external_flows: { status: "complete", reason_codes: [] },
      },
      reason_codes: notComputable ? ["valuation_boundary_unavailable"] : [],
    },
    xirr: {
      metric: "xirr",
      scope: "portfolio",
      performance_currency: "RUB",
      value: notComputable ? null : "7.42",
      value_unit: "percentage_points",
      annualized: true,
      period,
      availability: notComputable ? "not_computable" : "available",
      quality: notComputable ? "unavailable" : "exact",
      reason_codes: notComputable ? ["not_computable_xirr_root_ambiguity"] : [],
    },
    twrr: {
      metric: "twrr",
      scope: "portfolio",
      account_id: null,
      performance_currency: "RUB",
      value: notComputable ? null : "6.10",
      value_unit: "percentage_points",
      annualized: false,
      period,
      availability: notComputable ? "not_computable" : "available",
      quality: notComputable ? "unavailable" : "exact",
      reason_codes: notComputable ? ["valuation_boundary_unavailable"] : [],
    },
  };
}
