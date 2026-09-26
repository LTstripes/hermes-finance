import { useQuery } from "@tanstack/react-query";
import { type CSSProperties, type ReactNode, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link, useSearchParams } from "react-router";

import {
  getCapitalComposition,
  getClosedReportComparison,
  getPassiveIncomeHistory,
} from "../api/analytics";
import { listGoalSummary, type GoalSummary } from "../api/goals";
import { useMonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { listMonths } from "../api/months";
import type {
  CapitalCompositionPoint,
  ClosedReportComparison,
  PassiveIncomeAverage,
  PassiveIncomeHistory,
  ReportingMonth,
} from "../api/types";
import { isGuidedCloseStepId, monthlyCloseReturnPath } from "../components/month-close/navigation";
import { formatMoney, formatMonth } from "../lib/format";
import { moneyToChartNumber, toKopecks } from "../lib/money";
import { queryKeys } from "../queryClient";
import { uiV2GoalsPath } from "./goalRoute";
import {
  reportIndex,
  monthWorkspacePath,
  resolveMonthSelection,
  selectNewestDraftAfterLatestClosed,
  sortReportingMonths,
} from "./monthSelection";
import { isQueryReady, UiV2Notice, UiV2ReportContext, UiV2WidgetState } from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import styles from "./UiV2Page.module.css";
import {
  liabilityTone,
  moneyDeltaText as moneyDelta,
  moneyText as money,
  moneyTone as tone,
} from "./valueFormat";

type HistoryWindow = 3 | 12 | "all";

const ASSET_CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Деньги", color: "#5f7e9e" },
  deposits: { label: "Депозиты", color: "#8e73a6" },
  stocks: { label: "Акции", color: "#c68b51" },
  bonds: { label: "Облигации", color: "#5f9b82" },
  gold_other: { label: "Золото и прочее", color: "#a4a8ad" },
};

const PASSIVE_SOURCE_META = [
  ["deposit_interest", "Проценты по депозитам"],
  ["bond_coupons", "Купоны"],
  ["dividends", "Дивиденды"],
  ["other_capital_income", "Прочий доход от капитала"],
] as const;

function configuredBoundary(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return value;
  const year = Number(match[1]);
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? formatMonth(year, month) : value;
}

function passiveAverageDetail(average: PassiveIncomeAverage): string {
  const boundary = configuredBoundary(average.configured_start_month);
  const suffix = boundary ? ` · учёт с ${boundary}` : "";
  if (average.count_months === 0) {
    return `Среднее пока недоступно · 0 из ${average.target_window_months} закрытых отчётов${suffix}`;
  }
  return `Среднее ${money(average.average)} · ${average.count_months} из ${average.target_window_months} закрытых отчётов${suffix}`;
}

function DraftAction({ draft }: { draft: ReportingMonth }) {
  const workflowQuery = useMonthCloseWorkflow(draft.id);
  const ready = isQueryReady(workflowQuery);
  const workflow = ready ? workflowQuery.data : undefined;
  const valid =
    workflow?.contract_version === "monthly_close_workflow_v1" &&
    workflow.month.id === draft.id &&
    workflow.month.status === "draft";
  const recommended =
    valid && isGuidedCloseStepId(workflow.recommended_step_id)
      ? workflow.recommended_step_id
      : null;

  if (workflowQuery.isError) {
    return (
      <div className={styles.draftAction} data-state="unavailable">
        <span>{formatMonth(draft.year, draft.month)} ещё не закрыт</span>
        <button onClick={() => void workflowQuery.refetch()} type="button">
          Проверить снова
        </button>
      </div>
    );
  }
  if (!ready) {
    return (
      <div className={styles.draftAction} data-state="loading" role="status">
        Проверяем незакрытый {formatMonth(draft.year, draft.month).toLocaleLowerCase("ru-RU")}…
      </div>
    );
  }
  if (!recommended) return null;

  return (
    <Link
      className={styles.draftAction}
      data-testid="v2-draft-action"
      to={monthWorkspacePath(draft.id, recommended)}
    >
      <span>{formatMonth(draft.year, draft.month)} ещё не закрыт</span>
      <strong>Продолжить →</strong>
    </Link>
  );
}

function KpiGrid({
  comparison,
  comparisonReady,
  passive,
  passiveReady,
  retryComparison,
  retryPassive,
}: {
  comparison: ClosedReportComparison | undefined;
  comparisonReady: boolean;
  passive: PassiveIncomeHistory | undefined;
  passiveReady: boolean;
  retryComparison: () => void;
  retryPassive: () => void;
}) {
  const comparisonAvailable = comparison?.availability === "available";
  return (
    <section aria-label="Главные показатели" className={styles.metrics}>
      <article className={`${styles.metric} ${styles.metricPrimary}`}>
        <p className={styles.eyebrow}>Ликвидный капитал</p>
        {comparisonReady && comparison?.current ? (
          <>
            <p className={styles.metricValue} data-testid="v2-capital">
              {money(comparison.current.liquid_capital_net)}
            </p>
            <p className={styles.metricDetail}>Активы за вычетом включённых обязательств</p>
          </>
        ) : (
          <UiV2WidgetState retry={comparisonReady ? undefined : retryComparison} />
        )}
      </article>

      <article className={styles.metric}>
        <p className={styles.eyebrow}>Изменение</p>
        {comparisonReady && comparisonAvailable ? (
          <>
            <p
              aria-describedby="v2-change-definition"
              className={styles.metricValue}
              data-testid="v2-capital-change"
              data-tone={tone(comparison?.liquid_capital_net_delta)}
            >
              {moneyDelta(comparison?.liquid_capital_net_delta)}
            </p>
            <p className={styles.metricDetail} id="v2-change-definition">
              к {formatMonth(comparison?.previous?.year ?? 0, comparison?.previous?.month ?? 0)} ·
              изменение состояния, не инвестиционная доходность
            </p>
          </>
        ) : comparisonReady && comparison?.availability === "previous_closed_report_unavailable" ? (
          <>
            <p className={styles.metricEmpty}>Пока нет базы сравнения</p>
            <p className={styles.metricDetail}>Появится после следующего закрытого отчёта</p>
          </>
        ) : (
          <UiV2WidgetState retry={comparisonReady ? undefined : retryComparison} />
        )}
      </article>

      <article className={styles.metric}>
        <p className={styles.eyebrow}>Пассивный доход</p>
        {passiveReady && passive?.selected_report ? (
          <>
            <p className={styles.metricValue} data-testid="v2-passive-actual">
              {money(passive.selected_report.passive_income_actual)}
            </p>
            <p className={styles.metricDetail}>{passiveAverageDetail(passive.average)}</p>
          </>
        ) : (
          <UiV2WidgetState retry={passiveReady ? undefined : retryPassive} />
        )}
      </article>
    </section>
  );
}

function CapitalHistoryChart({ points }: { points: CapitalCompositionPoint[] }) {
  const data: Array<{
    key: string;
    label: string;
    amount: string | null;
    rubles: number | null;
  }> = [];
  let previous: CapitalCompositionPoint | undefined;
  for (const point of points) {
    if (previous && reportIndex(point) - reportIndex(previous) > 1) {
      const gapIndex = reportIndex(previous) + 1;
      const gapYear = Math.floor((gapIndex - 1) / 12);
      const gapMonth = ((gapIndex - 1) % 12) + 1;
      data.push({
        key: `gap-${gapYear}-${gapMonth}`,
        label: `${String(gapMonth).padStart(2, "0")}.${gapYear}`,
        amount: null,
        rubles: null,
      });
    }
    data.push({
      key: `${point.year}-${point.month}`,
      label: `${String(point.month).padStart(2, "0")}.${point.year}`,
      amount: point.liquid_capital_net.amount,
      rubles: moneyToChartNumber(point.liquid_capital_net.amount),
    });
    previous = point;
  }
  const gapCount = data.filter((item) => item.amount === null).length;
  return (
    <div className={styles.chart} data-gap-count={gapCount} data-testid="v2-capital-history">
      <ResponsiveContainer height={245} width="100%">
        <LineChart data={data} margin={{ bottom: 2, left: 4, right: 12, top: 12 }}>
          <CartesianGrid stroke="#e8edf1" strokeDasharray="3 4" vertical={false} />
          <XAxis axisLine={false} dataKey="label" interval="preserveStartEnd" tickLine={false} />
          <YAxis axisLine={false} hide tickLine={false} />
          <Tooltip
            formatter={(_value, _name, item) => [formatMoney(item.payload.amount), "Капитал"]}
            labelFormatter={(label) => `Отчёт ${label}`}
          />
          <Line
            activeDot={{ r: 5 }}
            connectNulls={false}
            dataKey="rubles"
            dot={{ fill: "#244f83", r: 3, strokeWidth: 0 }}
            isAnimationActive={false}
            stroke="#244f83"
            strokeWidth={3}
            type="linear"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function CapitalHistoryBlock({
  points,
  ready,
  retry,
}: {
  points: CapitalCompositionPoint[];
  ready: boolean;
  retry: () => void;
}) {
  const [window, setWindow] = useState<HistoryWindow>(12);
  const visible = window === "all" ? points : points.slice(-window);
  return (
    <section
      className={`${styles.panel} ${styles.widePanel}`}
      aria-labelledby="capital-history-title"
    >
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Закрытые отчёты</p>
          <h2 id="capital-history-title">Динамика капитала</h2>
        </div>
        <fieldset className={styles.segmented} aria-label="Период динамики капитала">
          {([3, 12, "all"] as const).map((value) => (
            <button
              aria-pressed={window === value}
              key={value}
              onClick={() => setWindow(value)}
              type="button"
            >
              {value === 3 ? "3 месяца" : value === 12 ? "12 месяцев" : "Всё время"}
            </button>
          ))}
        </fieldset>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : visible.length === 0 ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <>
          <CapitalHistoryChart points={visible} />
          <p className={styles.panelFootnote}>
            Показаны последние {visible.length} закрытых отчёта. Пропуски показаны разрывами;
            значения не интерполируются.
          </p>
        </>
      )}
    </section>
  );
}

function CompositionBlock({
  comparison,
  ready,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const allocation =
    comparison?.current?.allocation.filter((item) => toKopecks(item.amount.amount) > 0n) ?? [];
  const slices = allocation.map((item) => ({
    ...item,
    name: ASSET_CLASS_META[item.asset_class]?.label ?? item.asset_class,
    color: ASSET_CLASS_META[item.asset_class]?.color ?? "#a4a8ad",
    value: moneyToChartNumber(item.amount.amount),
  }));
  return (
    <section className={styles.panel} aria-labelledby="composition-title">
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Текущий снимок</p>
          <h2 id="composition-title">Структура активов</h2>
        </div>
        <p className={styles.panelHint}>Только положительные ликвидные активы</p>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !comparison?.current ? (
        <UiV2WidgetState title="Нет закрытого снимка" />
      ) : (
        <>
          {slices.length === 0 ? (
            <UiV2WidgetState title="В закрытом снимке нет положительных ликвидных активов" />
          ) : (
            <div className={styles.compositionBody}>
              <div className={styles.donut}>
                <ResponsiveContainer height={185} width="100%">
                  <PieChart>
                    <Pie
                      data={slices}
                      dataKey="value"
                      innerRadius="58%"
                      isAnimationActive={false}
                      nameKey="name"
                      outerRadius="88%"
                      paddingAngle={2}
                      strokeWidth={0}
                    >
                      {slices.map((slice) => (
                        <Cell fill={slice.color} key={slice.asset_class} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(_value, _name, item) => money(item.payload.amount)} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className={styles.legend}>
                {slices.map((slice) => (
                  <li key={slice.asset_class}>
                    <span aria-hidden="true" style={{ background: slice.color }} />
                    <span>{slice.name}</span>
                    <strong>{money(slice.amount)}</strong>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <dl className={styles.netSummary}>
            <div>
              <dt>Ликвидные активы</dt>
              <dd>{money(comparison.current.liquid_assets_total)}</dd>
            </div>
            <div className={styles.deduction}>
              <dt>Включённые обязательства</dt>
              <dd>− {money(comparison.current.included_debts)}</dd>
            </div>
            <div>
              <dt>Ликвидный капитал</dt>
              <dd>{money(comparison.current.liquid_capital_net)}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}

function ChangeBlock({
  comparison,
  ready,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  retry: () => void;
}) {
  return (
    <section className={styles.panel} aria-labelledby="change-title">
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Изменение состояния</p>
          <h2 id="change-title">Где изменились суммы</h2>
        </div>
        <p className={styles.panelHint}>Изменение состояния, не инвестиционная доходность</p>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : comparison?.availability !== "available" || !comparison.asset_class_deltas ? (
        <UiV2WidgetState title="Нужны два закрытых отчёта для сравнения" />
      ) : (
        <>
          <ul className={styles.changeList}>
            {comparison.asset_class_deltas.map((item) => (
              <li key={item.asset_class}>
                <span>{ASSET_CLASS_META[item.asset_class]?.label ?? item.asset_class}</span>
                <strong data-tone={tone(item.amount)}>{moneyDelta(item.amount)}</strong>
              </li>
            ))}
            <li className={styles.liabilityChange}>
              <span>Включённые обязательства</span>
              <strong data-tone={liabilityTone(comparison.included_debts_delta)}>
                {moneyDelta(comparison.included_debts_delta)}
              </strong>
            </li>
          </ul>
          <div className={styles.changeTotal}>
            <span>Изменение ликвидного капитала</span>
            <strong data-tone={tone(comparison.liquid_capital_net_delta)}>
              {moneyDelta(comparison.liquid_capital_net_delta)}
            </strong>
          </div>
          <p className={styles.panelFootnote}>
            Перемещение между классами может менять строки без роста капитала. Рост обязательств
            уменьшает чистый капитал.
          </p>
        </>
      )}
    </section>
  );
}

function PassiveChart({ data }: { data: PassiveIncomeHistory["points"] }) {
  const points = data.map((point) => ({
    key: `${point.year}-${point.month}`,
    label: `${String(point.month).padStart(2, "0")}.${point.year}`,
    amount: point.passive_income_actual.amount,
    rubles: moneyToChartNumber(point.passive_income_actual.amount),
  }));
  return (
    <div className={styles.chart} data-point-count={points.length} data-testid="v2-passive-history">
      <ResponsiveContainer height={220} width="100%">
        <BarChart data={points} margin={{ bottom: 2, left: 4, right: 12, top: 12 }}>
          <CartesianGrid stroke="#e8edf1" strokeDasharray="3 4" vertical={false} />
          <XAxis axisLine={false} dataKey="label" interval="preserveStartEnd" tickLine={false} />
          <YAxis axisLine={false} hide tickLine={false} />
          <Tooltip
            formatter={(_value, _name, item) => [formatMoney(item.payload.amount), "Факт"]}
            labelFormatter={(label) => `Отчёт ${label}`}
          />
          <Bar
            dataKey="rubles"
            fill="#244f83"
            isAnimationActive={false}
            maxBarSize={34}
            radius={[5, 5, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function PassiveBlock({
  history,
  ready,
  retry,
}: {
  history: PassiveIncomeHistory | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const eligiblePoints = history?.points.filter((point) => point.included_in_average_window) ?? [];
  return (
    <section className={`${styles.panel} ${styles.widePanel}`} aria-labelledby="passive-title">
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Получено · факт</p>
          <h2 id="passive-title">Пассивный доход</h2>
        </div>
        <Link className={styles.contextLink} to="/payouts">
          Выплаты и прогноз →
        </Link>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !history?.selected_report ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <div className={styles.passiveLayout}>
          <div>
            {eligiblePoints.length > 0 ? (
              <PassiveChart data={eligiblePoints} />
            ) : (
              <UiV2WidgetState title="Нет закрытой истории в выбранном периоде" />
            )}
            <p className={styles.panelFootnote}>{passiveAverageDetail(history.average)}</p>
            {eligiblePoints.length > 0 ? (
              <p className={styles.panelFootnote}>
                На графике только отчёты, вошедшие в среднее: {eligiblePoints.length}.
              </p>
            ) : null}
          </div>
          <div className={styles.sourceBreakdown}>
            <p className={styles.eyebrow}>
              Источники · {formatMonth(history.selected_report.year, history.selected_report.month)}
            </p>
            <ul>
              {PASSIVE_SOURCE_META.map(([key, label]) => (
                <li key={key}>
                  <span>{label}</span>
                  <strong>{money(history.selected_report?.breakdown[key])}</strong>
                </li>
              ))}
            </ul>
            <p className={styles.factNote}>Только фактически полученный доход от капитала.</p>
          </div>
        </div>
      )}
    </section>
  );
}

function goalProgressStyle(value: string): CSSProperties {
  const safe = /^\d+(?:\.\d+)?$/.test(value) ? value : "0";
  return { "--goal-progress": `${safe}%` } as CSSProperties;
}

function GoalsBlock({
  goals,
  monthId,
  ready,
  retry,
}: {
  goals: GoalSummary[];
  monthId: number | null;
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
    <section className={`${styles.panel} ${styles.widePanel}`} aria-labelledby="goals-title">
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>Текущий прогресс</p>
          <h2 id="goals-title">Ключевые цели</h2>
        </div>
        <Link className={styles.contextLink} to={uiV2GoalsPath(monthId)}>
          Все цели →
        </Link>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : supported.length === 0 ? (
        <UiV2WidgetState title="Нет активных целей с поддерживаемым прогрессом" />
      ) : (
        <div className={styles.goalsGrid}>
          {supported.map((goal) => {
            const forecast = goal.achievement_forecast;
            return (
              <article key={goal.id}>
                <div className={styles.goalHeader}>
                  <h3>{goal.name}</h3>
                  <strong>{forecast.progress_pct?.replace(".", ",")}%</strong>
                </div>
                <div className={styles.goalTrack} aria-hidden="true">
                  <span style={goalProgressStyle(forecast.progress_pct ?? "0")} />
                </div>
                <p>
                  {money(forecast.current_value)} из {money(forecast.target_value)}
                </p>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function UiV2Page() {
  const [params] = useSearchParams();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const { latestClosed, newestDraft: newerDraft } = selectNewestDraftAfterLatestClosed(months);
  const closedId = latestClosed?.id ?? null;

  const comparisonQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.closedReportComparison,
    queryFn: ({ signal }) => getClosedReportComparison(signal),
    refetchOnWindowFocus: true,
  });
  const compositionQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
    refetchOnWindowFocus: true,
  });
  const passiveQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.passiveIncomeHistory(closedId),
    queryFn: ({ signal }) => getPassiveIncomeHistory(closedId as number, signal),
    refetchOnWindowFocus: true,
  });
  const goalsQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.goalSummary(closedId),
    queryFn: ({ signal }) => listGoalSummary(closedId as number, {}, signal),
    refetchOnWindowFocus: true,
  });

  const monthsReady = isQueryReady(monthsQuery);
  const comparisonIdentityMatches =
    comparisonQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
    comparisonQuery.data.current?.reporting_month_id === closedId;
  const comparisonReady = isQueryReady(comparisonQuery) && comparisonIdentityMatches;
  const compositionIdentityMatches =
    compositionQuery.data?.points.at(-1)?.reporting_month_id === closedId;
  const compositionReady = isQueryReady(compositionQuery) && compositionIdentityMatches;
  const passiveIdentityMatches =
    passiveQuery.data?.latest_closed_report_id === closedId &&
    passiveQuery.data.selected_report?.reporting_month_id === closedId;
  const passiveReady = isQueryReady(passiveQuery) && passiveIdentityMatches;
  const goalsIdentityMatches =
    goalsQuery.data?.every(
      (goal) =>
        goal.achievement_forecast.goal_id === goal.id &&
        goal.achievement_forecast.reporting_month_id === closedId &&
        goal.achievement_forecast.method_version === "goal_achievement_v1" &&
        goal.achievement_forecast.source_forecast_version === null,
    ) ?? false;
  const goalsReady = isQueryReady(goalsQuery) && goalsIdentityMatches;
  const loading = !monthsReady;

  const requestedMonth = resolveMonthSelection(params.getAll("month"), months);
  const requestedStepValues = params.getAll("step");
  const requestedStep =
    requestedStepValues.length === 1 && isGuidedCloseStepId(requestedStepValues[0])
      ? requestedStepValues[0]
      : null;
  const v1ReturnPath =
    requestedMonth.kind === "selected"
      ? requestedStep
        ? monthlyCloseReturnPath({
            monthId: requestedMonth.month.id,
            origin: "monthly-close",
            step: requestedStep,
          })
        : `/months/${requestedMonth.month.id}`
      : latestClosed
        ? `/months/${latestClosed.id}`
        : "/v1";

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Финансовые показатели скрыты, пока актуальный закрытый отчёт не подтверждён.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = (
      <p className={styles.loading} role="status">
        Проверяем последние закрытые отчёты…
      </p>
    );
  } else if (!latestClosed) {
    content = (
      <>
        {newerDraft ? <DraftAction draft={newerDraft} /> : null}
        <UiV2Notice title="Закрой первый отчёт">
          «Мои финансы» строится только по закрытым данным. Черновик не выдаётся за подтверждённую
          финансовую картину. <Link to="/monthly-close">Перейти к закрытию месяца →</Link>
        </UiV2Notice>
      </>
    );
  } else {
    content = (
      <>
        <UiV2ReportContext month={latestClosed}>
          <Link to="/v2/reports">История отчётов →</Link>
        </UiV2ReportContext>
        {newerDraft ? <DraftAction draft={newerDraft} /> : null}
        <KpiGrid
          comparison={comparisonReady ? comparisonQuery.data : undefined}
          comparisonReady={comparisonReady}
          passive={passiveReady ? passiveQuery.data : undefined}
          passiveReady={passiveReady}
          retryComparison={() => void comparisonQuery.refetch()}
          retryPassive={() => void passiveQuery.refetch()}
        />
        <div className={styles.homeGrid}>
          <CapitalHistoryBlock
            points={compositionReady ? (compositionQuery.data?.points ?? []) : []}
            ready={compositionReady}
            retry={() => void compositionQuery.refetch()}
          />
          <CompositionBlock
            comparison={comparisonReady ? comparisonQuery.data : undefined}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <ChangeBlock
            comparison={comparisonReady ? comparisonQuery.data : undefined}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <PassiveBlock
            history={passiveReady ? passiveQuery.data : undefined}
            ready={passiveReady}
            retry={() => void passiveQuery.refetch()}
          />
          <GoalsBlock
            goals={goalsReady ? (goalsQuery.data ?? []) : []}
            monthId={closedId}
            ready={goalsReady}
            retry={() => void goalsQuery.refetch()}
          />
        </div>
      </>
    );
  }

  return (
    <UiV2Shell
      active="home"
      busy={loading}
      header={
        <>
          <p className={styles.eyebrow}>Обзор подтверждённых данных</p>
          <h1>Мои финансы</h1>
          <p className={styles.subtitle}>Спокойная картина капитала, дохода и целей.</p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2Shell>
  );
}
