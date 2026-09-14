import type { GuidedCloseStep, MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { DashboardKpis, ReportingMonth } from "../api/types";

// Entirely fictional data; shared by component and intercepted-browser tests only.
export const uiV2Months: ReportingMonth[] = [
  { id: 91, year: 2031, month: 7, status: "closed", snapshot_date: "2031-07-31", source: "manual" },
  { id: 12, year: 2031, month: 8, status: "draft", snapshot_date: "2031-08-30", source: "manual" },
];

function money(amount: string) {
  return { amount, currency: "RUB" };
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
