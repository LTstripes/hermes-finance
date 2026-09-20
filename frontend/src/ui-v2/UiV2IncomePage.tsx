import { useQuery } from "@tanstack/react-query";
import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { getPassiveIncomeHistory } from "../api/analytics";
import { getCashFlowLadder } from "../api/cashFlowLadder";
import { listGoalSummary, type GoalSummary } from "../api/goals";
import { listMonths } from "../api/months";
import { plannedVsActual } from "../api/plannedBudget";
import { getIncomePlanSummary } from "../api/summary";
import { listSavings } from "../api/savings";
import type {
  CashFlowLadder,
  CashFlowLadderEvent,
  CashFlowLadderMonth,
  IncomePlanCoverage,
  IncomePlanForecast,
  IncomePlanSummary,
  PassiveIncomeAverage,
  PassiveIncomeHistory,
  PlanVsActualRow,
  ReportingMonth,
  SavingAllocation,
} from "../api/types";
import { isGuidedCloseStepId, monthlyCloseReturnPath } from "../components/month-close/navigation";
import { formatDate, formatMonth, formatMonthKey, formatPercent } from "../lib/format";
import { queryKeys } from "../queryClient";
import { sortReportingMonths } from "./monthSelection";
import {
  eventLabel as ownerEventLabel,
  PRINCIPAL_REPAYMENT_LABEL,
  sourceLabel as ownerSourceLabel,
} from "./uiV2Copy";
import {
  isQueryReady,
  UiV2Loading,
  UiV2Notice,
  UiV2ReportContext,
  UiV2WidgetState,
} from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import sharedStyles from "./UiV2Page.module.css";
import incomeStyles from "./UiV2Income.module.css";
import { moneyText as money } from "./valueFormat";

type FactSelection = {
  month: ReportingMonth | null;
  valid: boolean;
};

type LadderWindow = 14 | 30 | 12;

const PASSIVE_SOURCE_META = [
  ["deposit_interest", "Проценты по депозитам"],
  ["bond_coupons", "Купоны"],
  ["dividends", "Дивиденды"],
  ["other_capital_income", "Прочий доход от капитала"],
] as const;

function reportIndex(month: Pick<ReportingMonth, "year" | "month">): number {
  return month.year * 12 + month.month;
}

function resolveFactSelection(values: string[], closedMonths: ReportingMonth[]): FactSelection {
  if (values.length === 0) return { month: closedMonths[0] ?? null, valid: true };
  if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) {
    return { month: null, valid: false };
  }
  const id = Number(values[0]);
  if (!Number.isSafeInteger(id)) return { month: null, valid: false };
  const month = closedMonths.find((candidate) => candidate.id === id) ?? null;
  return { month, valid: month !== null };
}

function averageDetail(average: PassiveIncomeAverage): string {
  const boundary = formatMonthKey(average.configured_start_month, { empty: "" });
  const suffix = boundary ? ` · учёт с ${boundary}` : " · вся доступная история";
  if (average.count_months === 0) {
    return `Нет закрытых месяцев в выбранном периоде · 0 из ${average.target_window_months}${suffix}`;
  }
  return `${average.count_months} из ${average.target_window_months} закрытых отчётов${suffix}`;
}

function progressStyle(value: string): CSSProperties {
  const safe = /^\d+(?:\.\d+)?$/.test(value) ? value : "0";
  return { "--goal-progress": `${safe}%` } as CSSProperties;
}

function useNarrowViewport(maxWidthPx = 800): boolean {
  const query = `(max-width: ${maxWidthPx}px)`;
  const [narrow, setNarrow] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const handle = (event: MediaQueryListEvent) => setNarrow(event.matches);
    setNarrow(list.matches);
    list.addEventListener("change", handle);
    return () => list.removeEventListener("change", handle);
  }, [query]);
  return narrow;
}

function Panel({
  children,
  id,
  title,
  eyebrow,
  action,
  wide = false,
  testId,
}: {
  children: ReactNode;
  id: string;
  title: string;
  eyebrow: string;
  action?: ReactNode;
  wide?: boolean;
  testId: string;
}) {
  return (
    <section
      aria-labelledby={id}
      className={`${sharedStyles.panel} ${wide ? sharedStyles.widePanel : ""} ${incomeStyles.panel}`}
      data-testid={testId}
    >
      <div className={sharedStyles.panelHeader}>
        <div>
          <p className={sharedStyles.eyebrow}>{eyebrow}</p>
          <h2 id={id}>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Headlines({
  history,
  historyReady,
  forecast,
  forecastReady,
  ladder,
  ladderReady,
  retryHistory,
  retrySummary,
  retryLadder,
}: {
  history: PassiveIncomeHistory | undefined;
  historyReady: boolean;
  forecast: IncomePlanForecast | undefined;
  forecastReady: boolean;
  ladder: CashFlowLadder | undefined;
  ladderReady: boolean;
  retryHistory: () => void;
  retrySummary: () => void;
  retryLadder: () => void;
}) {
  const averageMeasured = historyReady && history !== undefined && history.average.count_months > 0;
  const upcoming = ladderReady ? ladder?.upcoming_30_days : undefined;
  return (
    <section aria-label="Главные показатели дохода" className={incomeStyles.metrics}>
      <article className={`${incomeStyles.metric} ${incomeStyles.metricPrimary}`}>
        <p className={sharedStyles.eyebrow}>Историческое среднее</p>
        {historyReady && history ? (
          <>
            <p className={incomeStyles.metricValue} data-testid="income-average">
              {averageMeasured ? money(history.average.average) : "Недоступно"}
            </p>
            <p className={incomeStyles.metricDetail}>{averageDetail(history.average)}</p>
          </>
        ) : (
          <UiV2WidgetState retry={retryHistory} />
        )}
      </article>

      <article className={incomeStyles.metric}>
        <p className={sharedStyles.eyebrow}>Прогноз на 12 месяцев</p>
        {forecastReady && forecast ? (
          <>
            <p className={incomeStyles.metricValue} data-testid="income-forecast">
              {money(forecast.monthly_total)} <span>/ мес</span>
            </p>
            <p className={incomeStyles.metricDetail}>
              {money(forecast.annual_total)} / 12 мес ·{" "}
              {forecast.is_approximate ? "оценка" : "расчёт"}
            </p>
          </>
        ) : (
          <UiV2WidgetState retry={retrySummary} />
        )}
      </article>

      <article className={incomeStyles.metric}>
        <p className={sharedStyles.eyebrow}>Впереди 30 дней</p>
        {ladderReady && upcoming ? (
          <>
            <p className={incomeStyles.metricValue} data-testid="income-upcoming-passive">
              {money(upcoming.passive_income)}
            </p>
            <p className={incomeStyles.metricDetail}>
              <strong>
                {PRINCIPAL_REPAYMENT_LABEL}: {money(upcoming.redemption_principal)}
              </strong>{" "}
              · не доход
              <br />
              Всего поступлений: {money(upcoming.total_cash_flow)}
            </p>
          </>
        ) : (
          <UiV2WidgetState retry={retryLadder} />
        )}
      </article>
    </section>
  );
}

function FactHistoryBlock({
  history,
  ready,
  selectedMonth,
  closedMonths,
  selectionValid,
  onSelect,
  retry,
}: {
  history: PassiveIncomeHistory | undefined;
  ready: boolean;
  selectedMonth: ReportingMonth | null;
  closedMonths: ReportingMonth[];
  selectionValid: boolean;
  onSelect: (monthId: number) => void;
  retry: () => void;
}) {
  return (
    <Panel
      action={
        <label className={incomeStyles.reportSelect}>
          <span>Отчёт для разбивки</span>
          <select
            aria-label="Отчёт для разбивки фактического дохода"
            onChange={(event) => onSelect(Number(event.target.value))}
            value={selectedMonth ? String(selectedMonth.id) : ""}
          >
            {!selectionValid ? <option value="">Выберите закрытый отчёт</option> : null}
            {closedMonths.map((month) => (
              <option key={month.id} value={month.id}>
                {formatMonth(month.year, month.month)}
              </option>
            ))}
          </select>
        </label>
      }
      eyebrow="История закрытых отчётов"
      id="income-history-title"
      testId="income-history-panel"
      title="Получено фактически"
      wide
    >
      {!selectionValid ? (
        <UiV2WidgetState title="Выберите только закрытый отчёт для фактической разбивки" />
      ) : !ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !history?.selected_report ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <div className={incomeStyles.factLayout}>
          <div>
            <section
              aria-label="История фактического пассивного дохода"
              className={incomeStyles.historyList}
            >
              {history.points.map((point) => {
                const selected =
                  point.reporting_month_id === history.selected_report?.reporting_month_id;
                return (
                  <button
                    aria-pressed={selected}
                    className={incomeStyles.historyItem}
                    data-selected={selected}
                    data-testid={`income-history-${point.reporting_month_id}`}
                    key={point.reporting_month_id}
                    onClick={() => onSelect(point.reporting_month_id)}
                    type="button"
                  >
                    <span>
                      <strong>{formatMonth(point.year, point.month)}</strong>
                      <small>{formatDate(point.snapshot_date)}</small>
                    </span>
                    <strong>{money(point.passive_income_actual)}</strong>
                    <small>
                      {point.included_in_average_window
                        ? "входит в среднее"
                        : "не входит в окно среднего"}
                    </small>
                  </button>
                );
              })}
            </section>
            <p className={sharedStyles.panelFootnote}>
              {averageDetail(history.average)}. История не заполняет отсутствующие месяцы нулями.
            </p>
          </div>
          <div className={incomeStyles.breakdown}>
            <p className={sharedStyles.eyebrow}>
              Источники · {formatMonth(history.selected_report.year, history.selected_report.month)}
            </p>
            <ul className={incomeStyles.valueList}>
              {PASSIVE_SOURCE_META.map(([key, label]) => (
                <li key={key}>
                  <span>{label}</span>
                  <strong>{money(history.selected_report?.breakdown[key])}</strong>
                </li>
              ))}
              <li className={incomeStyles.totalRow}>
                <span>Всего чистого пассивного дохода</span>
                <strong>{money(history.selected_report.passive_income_actual)}</strong>
              </li>
            </ul>
            <p className={sharedStyles.panelFootnote}>
              Только фактический доход от капитала. Зарплата, бонусы, вознаграждения за покупки и
              возврат основной суммы сюда не входят.
            </p>
          </div>
        </div>
      )}
    </Panel>
  );
}

function ForecastBlock({
  forecast,
  ready,
  retry,
}: {
  forecast: IncomePlanForecast | undefined;
  ready: boolean;
  retry: () => void;
}) {
  return (
    <Panel
      eyebrow="Качество и состав оценки"
      id="income-forecast-title"
      testId="income-forecast-panel"
      title="Прогноз на 12 месяцев"
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !forecast ? (
        <UiV2WidgetState retry={retry} />
      ) : (
        <>
          <div className={incomeStyles.forecastSummary}>
            <div>
              <span>В месяц</span>
              <strong>{money(forecast.monthly_total)}</strong>
            </div>
            <div>
              <span>За 12 месяцев</span>
              <strong>{money(forecast.annual_total)}</strong>
            </div>
            <span
              className={incomeStyles.qualityBadge}
              data-quality={forecast.is_approximate ? "approximate" : "exact"}
            >
              {forecast.is_approximate ? "Оценка" : "Расчёт"}
            </span>
          </div>
          <ul className={incomeStyles.valueList}>
            <li>
              <span>Проценты по депозитам</span>
              <strong>{money(forecast.breakdown.expected_deposit_interest)}</strong>
            </li>
            <li>
              <span>Купоны после удержаний</span>
              <strong>{money(forecast.breakdown.expected_coupon_net)}</strong>
            </li>
            <li>
              <span>Дивидендная компонента</span>
              <strong>{money(forecast.breakdown.expected_dividend_component)}</strong>
            </li>
            <li>
              <span>Прочий доход от капитала</span>
              <strong>{money(forecast.breakdown.other_expected_capital_income)}</strong>
            </li>
          </ul>
          {forecast.warnings.length > 0 ? (
            <ul className={incomeStyles.warningList}>
              {forecast.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : (
            <p className={sharedStyles.panelFootnote}>Предупреждений нет.</p>
          )}
        </>
      )}
    </Panel>
  );
}

function eventLabel(event: CashFlowLadderEvent): string {
  return ownerEventLabel(event.component);
}

function eventSourceLabel(event: CashFlowLadderEvent): string {
  return ownerSourceLabel(event.source_kind);
}

function EventList({ events }: { events: CashFlowLadderEvent[] }) {
  if (events.length === 0) {
    return <p className={incomeStyles.emptyEvents}>Нет известных событий в этом окне.</p>;
  }
  return (
    <ul className={incomeStyles.eventList}>
      {events.map((event) => (
        <li
          data-testid={`income-event-${event.source_kind}-${event.source_id}`}
          key={`${event.source_kind}-${event.source_id}-${event.expected_date}`}
        >
          <span className={incomeStyles.eventTitle}>
            <time dateTime={event.expected_date}>{formatDate(event.expected_date)}</time>
            <strong>{eventLabel(event)}</strong>
          </span>
          <span className={incomeStyles.eventContext}>
            <span>{event.instrument_name ?? "Без инструмента"}</span>
            <small>
              {event.account_name} · {eventSourceLabel(event)}
              {event.is_approximate ? " · оценка" : ""}
            </small>
          </span>
          <strong className={incomeStyles.eventAmount}>
            {money(event.expected_net_amount)}
            {event.component === "redemption_principal" ? " · не доход" : ""}
          </strong>
        </li>
      ))}
    </ul>
  );
}

function LadderMonth({ month }: { month: CashFlowLadderMonth }) {
  return (
    <details className={incomeStyles.ladderMonth}>
      <summary>
        <span>{formatMonth(month.year, month.month)}</span>
        <span>{money(month.passive_income)} пассивно</span>
        <span>
          {PRINCIPAL_REPAYMENT_LABEL} {money(month.redemption_principal)}
        </span>
        <span>{month.is_approximate ? "оценка" : ""}</span>
      </summary>
      <dl className={incomeStyles.ladderFacts}>
        <div>
          <dt>Пассивный доход</dt>
          <dd>{money(month.passive_income)}</dd>
        </div>
        <div>
          <dt>{PRINCIPAL_REPAYMENT_LABEL} · не доход</dt>
          <dd>{money(month.redemption_principal)}</dd>
        </div>
        <div>
          <dt>Всего поступлений</dt>
          <dd>{money(month.total_cash_flow)}</dd>
        </div>
      </dl>
      <EventList events={month.items} />
    </details>
  );
}

function LadderBlock({
  ladder,
  ready,
  retry,
}: {
  ladder: CashFlowLadder | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const [window, setWindow] = useState<LadderWindow>(30);
  const selectedWindow = window === 14 ? ladder?.upcoming_14_days : ladder?.upcoming_30_days;
  return (
    <Panel
      eyebrow="Датированные события"
      id="income-ladder-title"
      testId="income-ladder-panel"
      title="Ожидаемые выплаты"
      wide
    >
      {!ready || !ladder ? (
        <UiV2WidgetState retry={retry} />
      ) : (
        <>
          <div className={incomeStyles.ladderControls}>
            <span className={incomeStyles.ladderControlsLabel}>Период выплат ниже</span>
            <fieldset
              aria-controls="income-ladder-content"
              aria-label="Окно ожидаемых выплат"
              className={`${sharedStyles.segmented} ${incomeStyles.ladderWindow}`}
            >
              {([14, 30, 12] as const).map((value) => (
                <button
                  aria-pressed={window === value}
                  key={value}
                  onClick={() => setWindow(value)}
                  type="button"
                >
                  {value === 12 ? "12 месяцев" : `${value} дней`}
                </button>
              ))}
            </fieldset>
          </div>
          <div id="income-ladder-content">
            {window === 12 ? (
              <p className={sharedStyles.panelFootnote}>
                12 месяцев от даты снимка. Возврат основной суммы всегда показан отдельно и не
                входит в пассивный доход.
              </p>
            ) : selectedWindow ? (
              <div className={incomeStyles.windowSummary} data-testid={`income-window-${window}`}>
                <div>
                  <span>
                    {selectedWindow.days} дней · {formatDate(selectedWindow.from_date)}–
                    {formatDate(selectedWindow.to_date)}
                  </span>
                  <strong>{money(selectedWindow.passive_income)} пассивно</strong>
                </div>
                <div>
                  <span>{PRINCIPAL_REPAYMENT_LABEL}</span>
                  <strong>{money(selectedWindow.redemption_principal)} · не доход</strong>
                </div>
                <div>
                  <span>Всего поступлений</span>
                  <strong>{money(selectedWindow.total_cash_flow)}</strong>
                </div>
                <EventList events={selectedWindow.items} />
              </div>
            ) : null}
            <section aria-label="Выплаты по месяцам" className={incomeStyles.ladderList}>
              {ladder.months.map((month) => (
                <LadderMonth key={`${month.year}-${month.month}`} month={month} />
              ))}
            </section>
          </div>
          {ladder.warnings.length > 0 ? (
            <ul className={incomeStyles.warningList}>
              {ladder.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function GoalsBlock({
  goals,
  ready,
  retry,
}: {
  goals: GoalSummary[];
  ready: boolean;
  retry: () => void;
}) {
  const supported = goals.filter(
    (goal) =>
      goal.is_active &&
      goal.achievement_forecast.current_value !== null &&
      goal.achievement_forecast.progress_pct !== null &&
      (goal.goal_type !== "passive_income" ||
        (goal.achievement_forecast.passive_income_months_count ?? 0) > 0),
  );
  return (
    <Panel
      action={
        <Link className={sharedStyles.contextLink} to="/goals">
          Все цели →
        </Link>
      }
      eyebrow="Цели с доступным прогрессом"
      id="income-goals-title"
      testId="income-goals-panel"
      title="Цели"
      wide
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : supported.length === 0 ? (
        <UiV2WidgetState title="Нет активных целей с поддерживаемым прогрессом" />
      ) : (
        <div className={incomeStyles.goalsGrid}>
          {supported.map((goal) => {
            const forecast = goal.achievement_forecast;
            return (
              <article data-testid={`income-goal-${goal.id}`} key={goal.id}>
                <div className={incomeStyles.goalHeader}>
                  <h3>{goal.name}</h3>
                  <strong>{forecast.progress_pct?.replace(".", ",")}%</strong>
                </div>
                <div aria-hidden="true" className={incomeStyles.goalTrack}>
                  <span style={progressStyle(forecast.progress_pct ?? "0")} />
                </div>
                <p>
                  {money(forecast.current_value)} из {money(forecast.target_value)}
                </p>
                <p>
                  {forecast.estimated_achievement_date
                    ? `Достигнуто ${formatDate(forecast.estimated_achievement_date)}`
                    : "Нет прогноза срока"}
                </p>
              </article>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function CoveragePlanBlock({
  coverage,
  coverageReady,
  budget,
  budgetReady,
  savings,
  savingsReady,
  savingTotal,
  monthId,
  retryCoverage,
  retryBudget,
  retrySavings,
  narrow,
}: {
  coverage: IncomePlanCoverage | undefined;
  coverageReady: boolean;
  budget: PlanVsActualRow[];
  budgetReady: boolean;
  savings: SavingAllocation[];
  savingsReady: boolean;
  savingTotal: IncomePlanSummary["cash_balance"] | undefined;
  monthId: number;
  retryCoverage: () => void;
  retryBudget: () => void;
  retrySavings: () => void;
  narrow: boolean;
}) {
  return (
    <Panel
      action={
        <Link className={sharedStyles.contextLink} to={`/months/${monthId}`}>
          Открыть месяц →
        </Link>
      }
      eyebrow="Последний закрытый отчёт"
      id="income-plan-title"
      testId="income-plan-panel"
      title="Покрытие расходов и план"
      wide
    >
      <details className={incomeStyles.collapsible} open={!narrow}>
        <summary>Показать покрытие расходов и план</summary>
        <div className={incomeStyles.collapsibleBody}>
          {!coverageReady ? (
            <UiV2WidgetState retry={retryCoverage} />
          ) : !coverage ? (
            <UiV2WidgetState title="Покрытие расходов недоступно" retry={retryCoverage} />
          ) : (
            <div className={incomeStyles.coverageGrid}>
              <div className={incomeStyles.coverageCard} data-testid="income-coverage">
                <span>Пассивно / обязательные расходы</span>
                <strong>
                  {formatPercent(coverage.coverage_pct, { digits: 1, empty: "Недоступно" })}
                </strong>
                <small>
                  расходы {money(coverage.mandatory_expenses)} · остаток{" "}
                  {money(coverage.passive_income_minus_mandatory_expenses)}
                </small>
                <small>
                  Фактическое покрытие:{" "}
                  {formatPercent(coverage.actual_mandatory_expense_coverage_pct, {
                    digits: 1,
                    empty: "Недоступно",
                  })}
                </small>
              </div>
              <div className={incomeStyles.coverageCard}>
                <span>Накопления месяца</span>
                <strong>
                  {savingTotal?.breakdown.saving_allocations
                    ? money(savingTotal.breakdown.saving_allocations)
                    : "Недоступно"}
                </strong>
                <small>
                  Сумма взята из сохранённого плана доходов; строки ниже приводятся без пересчёта.
                </small>
              </div>
            </div>
          )}
          <div className={incomeStyles.planGrid}>
            <div>
              <h3>План и факт расходов</h3>
              {!budgetReady ? (
                <UiV2WidgetState retry={retryBudget} />
              ) : budget.length === 0 ? (
                <p className={incomeStyles.emptyPlan}>План расходов не задан.</p>
              ) : (
                <ul className={incomeStyles.valueList}>
                  {budget.slice(0, 5).map((row) => (
                    <li key={`${row.expense_type}-${row.category}`}>
                      <span>{row.category}</span>
                      <strong>
                        {money(row.planned, "Не задано")} / {money(row.actual, "Нет факта")}
                      </strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3>Накопления</h3>
              {!savingsReady ? (
                <UiV2WidgetState retry={retrySavings} />
              ) : savings.length === 0 ? (
                <p className={incomeStyles.emptyPlan}>Накопления не заданы.</p>
              ) : (
                <ul className={incomeStyles.valueList}>
                  {savings.slice(0, 5).map((saving) => (
                    <li key={saving.id}>
                      <span>{saving.destination}</span>
                      <strong>{money(saving.amount)}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </details>
    </Panel>
  );
}

function Handoffs({ narrow }: { narrow: boolean }) {
  return (
    <Panel
      eyebrow="Дополнительные разделы"
      id="income-handoffs-title"
      testId="income-handoffs-panel"
      title="Налоги, ИИС и сценарии"
    >
      <details className={incomeStyles.collapsible} open={!narrow}>
        <summary>Показать разделы</summary>
        <div className={incomeStyles.collapsibleBody}>
          <div className={incomeStyles.handoffGrid}>
            <div>
              <h3>Налоги и ИИС</h3>
              <p>Подробная работа остаётся в текущем интерфейсе.</p>
              <Link to="/tax-iis-planner">Открыть Налоги и ИИС →</Link>
            </div>
            <div>
              <h3>Сценарии</h3>
              <p>Сценарии открываются в отдельном разделе; действий на этой странице нет.</p>
              <Link to="/scenario-lab">Открыть сценарии →</Link>
            </div>
          </div>
        </div>
      </details>
    </Panel>
  );
}

export default function UiV2IncomePage() {
  const narrow = useNarrowViewport();
  const [params, setParams] = useSearchParams();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const latestClosed = months.find((month) => month.status === "closed") ?? null;
  const closedMonths = useMemo(() => months.filter((month) => month.status === "closed"), [months]);
  const newerDraft = months.find(
    (month) =>
      month.status === "draft" &&
      (latestClosed === null || reportIndex(month) > reportIndex(latestClosed)),
  );
  const planningId = latestClosed?.id ?? null;
  const factSelection = resolveFactSelection(params.getAll("month"), closedMonths);
  const factId = factSelection.month?.id ?? null;

  const summaryQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.incomePlanSummary(planningId),
    queryFn: ({ signal }) => getIncomePlanSummary(planningId as number, signal),
    refetchOnWindowFocus: true,
  });
  const headlineHistoryQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.passiveIncomeHistory(planningId),
    queryFn: ({ signal }) => getPassiveIncomeHistory(planningId as number, signal),
    refetchOnWindowFocus: true,
  });
  const factHistoryQuery = useQuery({
    enabled: factId !== null,
    queryKey: queryKeys.passiveIncomeHistory(factId),
    queryFn: ({ signal }) => getPassiveIncomeHistory(factId as number, signal),
    refetchOnWindowFocus: true,
  });
  const ladderQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.cashFlowLadder(planningId),
    queryFn: ({ signal }) => getCashFlowLadder(planningId as number, signal),
    refetchOnWindowFocus: true,
  });
  const goalsQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.goalSummary(planningId),
    queryFn: ({ signal }) =>
      listGoalSummary(planningId as number, { forecastVersion: "v1" }, signal),
    refetchOnWindowFocus: true,
  });
  const budgetQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.planVsActual(planningId),
    queryFn: ({ signal }) => plannedVsActual(planningId as number, signal),
    refetchOnWindowFocus: true,
  });
  const savingsQuery = useQuery({
    enabled: planningId !== null,
    queryKey: queryKeys.savings(planningId),
    queryFn: ({ signal }) => listSavings(planningId as number, signal),
    refetchOnWindowFocus: true,
  });

  const monthsReady = isQueryReady(monthsQuery);
  const summaryReady =
    planningId !== null &&
    isQueryReady(summaryQuery) &&
    summaryQuery.data?.month.id === planningId &&
    summaryQuery.data.month.status === "closed" &&
    summaryQuery.data.forecast_version === "v1";
  const forecastReady = summaryReady && summaryQuery.data?.forecast !== undefined;
  const coverageReady = summaryReady && summaryQuery.data?.coverage !== undefined;
  const headlineHistoryReady =
    planningId !== null &&
    isQueryReady(headlineHistoryQuery) &&
    headlineHistoryQuery.data?.latest_closed_report_id === planningId;
  const factHistoryReady =
    factId !== null &&
    isQueryReady(factHistoryQuery) &&
    factHistoryQuery.data?.latest_closed_report_id === planningId &&
    factHistoryQuery.data.selected_report?.reporting_month_id === factId;
  const ladderReady =
    planningId !== null &&
    isQueryReady(ladderQuery) &&
    ladderQuery.data?.forecast_version === "v1" &&
    ladderQuery.data.as_of_date === latestClosed?.snapshot_date;
  const goalsReady =
    planningId !== null &&
    isQueryReady(goalsQuery) &&
    (goalsQuery.data?.every(
      (goal) =>
        goal.achievement_forecast.goal_id === goal.id &&
        goal.achievement_forecast.reporting_month_id === planningId &&
        goal.achievement_forecast.method_version === "goal_achievement_v1" &&
        goal.achievement_forecast.source_forecast_version === null,
    ) ??
      false);
  const budgetReady = isQueryReady(budgetQuery);
  const savingsReady =
    isQueryReady(savingsQuery) &&
    (savingsQuery.data?.every((row) => row.reporting_month_id === planningId) ?? false);

  const selectFactMonth = (monthId: number) => {
    const next = new URLSearchParams(params);
    if (latestClosed?.id === monthId) next.delete("month");
    else next.set("month", String(monthId));
    setParams(next, { replace: true });
  };

  const requestedStepValues = params.getAll("step");
  const requestedStep =
    requestedStepValues.length === 1 && isGuidedCloseStepId(requestedStepValues[0])
      ? requestedStepValues[0]
      : null;
  const v1ReturnPath = latestClosed
    ? requestedStep
      ? monthlyCloseReturnPath({
          monthId: latestClosed.id,
          origin: "monthly-close",
          step: requestedStep,
        })
      : `/months/${latestClosed.id}`
    : "/";

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Доход и планы скрыты, пока актуальный закрытый отчёт не подтверждён.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем последний закрытый отчёт…" />;
  } else if (!latestClosed) {
    content = (
      <UiV2Notice title="Закрой первый отчёт">
        «Доход и планы» строится только по данным закрытых отчётов. Черновик не выдаётся за
        подтверждённую картину. <Link to="/monthly-close">Перейти к закрытию месяца →</Link>
      </UiV2Notice>
    );
  } else {
    const summary = summaryReady ? summaryQuery.data : undefined;
    content = (
      <>
        <UiV2ReportContext month={latestClosed}>
          <Link to={`/months/${latestClosed.id}`}>Отчёт месяца в текущем интерфейсе →</Link>
        </UiV2ReportContext>
        {newerDraft ? (
          <p className={incomeStyles.draftNote} data-testid="income-draft-note">
            {formatMonth(newerDraft.year, newerDraft.month)} ещё не закрыт — плановый контекст
            остаётся по последнему закрытому отчёту.
          </p>
        ) : null}
        <Headlines
          forecast={summary?.forecast}
          forecastReady={forecastReady}
          history={headlineHistoryReady ? headlineHistoryQuery.data : undefined}
          historyReady={headlineHistoryReady}
          ladder={ladderReady ? ladderQuery.data : undefined}
          ladderReady={ladderReady}
          retryHistory={() => void headlineHistoryQuery.refetch()}
          retryLadder={() => void ladderQuery.refetch()}
          retrySummary={() => void summaryQuery.refetch()}
        />
        <div className={incomeStyles.layout}>
          <FactHistoryBlock
            closedMonths={closedMonths}
            history={factHistoryReady ? factHistoryQuery.data : undefined}
            onSelect={selectFactMonth}
            ready={factHistoryReady}
            retry={() => void factHistoryQuery.refetch()}
            selectedMonth={factSelection.month}
            selectionValid={factSelection.valid}
          />
          <ForecastBlock
            forecast={summary?.forecast}
            ready={forecastReady}
            retry={() => void summaryQuery.refetch()}
          />
          <GoalsBlock
            goals={goalsReady ? (goalsQuery.data ?? []) : []}
            ready={goalsReady}
            retry={() => void goalsQuery.refetch()}
          />
          <CoveragePlanBlock
            budget={budgetReady ? (budgetQuery.data ?? []) : []}
            budgetReady={budgetReady}
            coverage={summary?.coverage}
            coverageReady={coverageReady}
            monthId={latestClosed.id}
            retryBudget={() => void budgetQuery.refetch()}
            retryCoverage={() => void summaryQuery.refetch()}
            retrySavings={() => void savingsQuery.refetch()}
            savingTotal={summary?.cash_balance}
            savings={savingsReady ? (savingsQuery.data ?? []) : []}
            savingsReady={savingsReady}
            narrow={narrow}
          />
          <LadderBlock
            ladder={ladderReady ? ladderQuery.data : undefined}
            ready={ladderReady}
            retry={() => void ladderQuery.refetch()}
          />
          <Handoffs narrow={narrow} />
        </div>
      </>
    );
  }

  return (
    <UiV2Shell
      active="income"
      busy={!monthsReady}
      header={
        <>
          <p className={sharedStyles.eyebrow}>Планирование по подтверждённым данным</p>
          <h1>Доход и планы</h1>
          <p className={sharedStyles.subtitle}>
            Что уже получено, на что рассчитывать и что запланировано.
          </p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2Shell>
  );
}
