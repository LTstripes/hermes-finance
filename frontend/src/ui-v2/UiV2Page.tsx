import { useQuery } from "@tanstack/react-query";
import { type CSSProperties, type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";

import {
  getCapitalComposition,
  getClosedReportComparison,
  getPassiveIncomeHistory,
} from "../api/analytics";
import { type GoalSummary, listGoalSummary } from "../api/goals";
import { useMonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { listMonths } from "../api/months";
import type {
  CapitalCompositionPoint,
  ClosedReportComparison,
  MoneyValue,
  PassiveIncomeAverage,
  PassiveIncomeHistory,
  ReportingMonth,
} from "../api/types";
import { isGuidedCloseStepId } from "../components/month-close/navigation";
import { PortfolioCoverageNote } from "../components/PortfolioCoverageNote";
import { HelpTip } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { moneySharePercent, moneyToChartNumber, toKopecks } from "../lib/money";
import { queryKeys } from "../queryClient";
import { classMeta } from "./assetClasses";
import { uiV2GoalsPath } from "./goalRoute";
import {
  monthWorkspacePath,
  reportIndex,
  selectNewestDraftAfterLatestClosed,
  sortReportingMonths,
} from "./monthSelection";
import styles from "./UiV2Home.module.css";
import {
  CapitalAreaChart,
  type CapitalChartPoint,
  CapitalWaterfallChart,
  PassiveBarsChart,
  type PassiveChartPoint,
  shortRub,
  type WaterfallStep,
} from "./UiV2HomeCharts";
import pageStyles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { accountingStartLabel, comparedToLabel } from "./uiV2Copy";
import {
  moneyText as money,
  percentText,
  moneyTone as tone,
  moneyWholeText as whole,
  moneyWholeDeltaText as wholeDelta,
} from "./valueFormat";

type HistoryWindow = 3 | 12 | "all";

/** Each asset class keeps its token colour (tokens.css) on this page. */
const CLASS_COLOR: Record<string, string> = {
  cash: "var(--c-cash)",
  deposits: "var(--c-dep)",
  stocks: "var(--c-stock)",
  bonds: "var(--c-bond)",
  gold_other: "var(--c-gold)",
};

const PASSIVE_SOURCE_META = [
  ["bond_coupons", "Купоны", "var(--c-bond)"],
  ["deposit_interest", "Проценты по депозитам", "var(--c-dep)"],
  ["dividends", "Дивиденды", "var(--c-stock)"],
  ["other_capital_income", "Прочий доход от капитала", "var(--c-cash)"],
] as const;

const SHORT_MONTHS = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];

function shortMonthLabel(year: number, month: number, first: boolean): string {
  const name = SHORT_MONTHS[month - 1] ?? String(month);
  return first || month === 1 ? `${name} ${year}` : name;
}

function isPositive(value: MoneyValue | null | undefined): boolean {
  return value != null && toKopecks(value.amount) > 0n;
}

/** The goal of this type the backend computes from the same figure as the page. */
function pageGoal(goals: GoalSummary[], type: string, mode: string): GoalSummary | null {
  const candidates = goals.filter(
    (goal) => goal.goal_type === type && goal.calculation_mode === mode,
  );
  return candidates.find((goal) => goal.is_main) ?? candidates[0] ?? null;
}

function goalReached(goal: GoalSummary): boolean {
  const forecast = goal.achievement_forecast;
  return (
    forecast.status === "achieved" ||
    (forecast.remaining_amount != null && toKopecks(forecast.remaining_amount.amount) <= 0n)
  );
}

function AverageHelp({ average }: { average: PassiveIncomeAverage }) {
  const boundary = accountingStartLabel(average.configured_start_month);
  return (
    <HelpTip label="Период среднего дохода">
      {average.count_months} из {average.target_window_months} закрытых отчётов
      {boundary ? ` · учёт ${boundary}` : ""}
    </HelpTip>
  );
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
      <div className={pageStyles.draftAction} data-state="unavailable">
        <span>{formatMonth(draft.year, draft.month)} ещё не закрыт</span>
        <button onClick={() => void workflowQuery.refetch()} type="button">
          Проверить снова
        </button>
      </div>
    );
  }
  if (!ready) {
    return (
      <div className={pageStyles.draftAction} data-state="loading" role="status">
        Проверяем незакрытый {formatMonth(draft.year, draft.month).toLocaleLowerCase("ru-RU")}…
      </div>
    );
  }
  if (!recommended) return null;

  return (
    <Link
      className={pageStyles.draftAction}
      data-testid="v2-draft-action"
      to={monthWorkspacePath(draft.id, recommended)}
    >
      <span>{formatMonth(draft.year, draft.month)} ещё не закрыт</span>
      <strong>Продолжить →</strong>
    </Link>
  );
}

function BlockHead({
  id,
  kicker,
  title,
  aside,
}: {
  id: string;
  kicker?: string;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className={styles.blockHead}>
      <div>
        {kicker ? <p className={styles.kicker}>{kicker}</p> : null}
        <h2 id={id}>{title}</h2>
      </div>
      {aside}
    </div>
  );
}

function capitalChartData(points: CapitalCompositionPoint[]): {
  data: CapitalChartPoint[];
  gapCount: number;
} {
  const data: CapitalChartPoint[] = [];
  let previous: CapitalCompositionPoint | undefined;
  for (const point of points) {
    if (previous && reportIndex(point) - reportIndex(previous) > 1) {
      const gapIndex = reportIndex(previous) + 1;
      const gapYear = Math.floor((gapIndex - 1) / 12);
      const gapMonth = ((gapIndex - 1) % 12) + 1;
      data.push({
        key: `gap-${gapYear}-${gapMonth}`,
        label: shortMonthLabel(gapYear, gapMonth, false),
        fullLabel: formatMonth(gapYear, gapMonth),
        amount: null,
        value: null,
      });
    }
    const unavailable = point.portfolio_source_coverage?.status === "unavailable";
    data.push({
      key: `${point.year}-${point.month}`,
      label: shortMonthLabel(point.year, point.month, data.length === 0),
      fullLabel: formatMonth(point.year, point.month),
      amount: unavailable ? null : point.liquid_capital_net.amount,
      value: unavailable ? null : moneyToChartNumber(point.liquid_capital_net.amount),
    });
    previous = point;
  }
  return { data, gapCount: data.filter((item) => item.key.startsWith("gap-")).length };
}

function CapitalHero({
  comparison,
  comparisonReady,
  retryComparison,
  points,
  historyReady,
  retryHistory,
  capitalGoal,
}: {
  comparison: ClosedReportComparison | undefined;
  comparisonReady: boolean;
  retryComparison: () => void;
  points: CapitalCompositionPoint[];
  historyReady: boolean;
  retryHistory: () => void;
  capitalGoal: GoalSummary | null;
}) {
  const [window, setWindow] = useState<HistoryWindow>(12);
  const visible = window === "all" ? points : points.slice(-window);
  const { data, gapCount } = capitalChartData(visible);
  const current = comparison?.current ?? null;
  const unavailable = current?.portfolio_source_coverage?.status === "unavailable";
  const deltaUnavailable = comparison?.liquid_capital_net_delta_coverage?.status === "unavailable";
  const deltaTone = tone(comparison?.liquid_capital_net_delta);
  const goalTarget = capitalGoal ? moneyToChartNumber(capitalGoal.target_value.amount) : null;
  const goalShort = goalTarget !== null ? shortRub(goalTarget) : "";

  return (
    <section aria-label="Главные показатели" className={styles.hero}>
      <div className={styles.heroFacts}>
        <p className={styles.kicker}>Ликвидный капитал</p>
        {comparisonReady && current ? (
          <>
            <p className={styles.heroValue} data-testid="v2-capital">
              {unavailable ? "—" : whole(current.liquid_capital_net)}
            </p>
            <PortfolioCoverageNote coverage={current.portfolio_source_coverage} month={current} />
            {comparison?.availability === "available" && comparison.previous ? (
              <p className={styles.deltaRow}>
                <span
                  className={styles.deltaChip}
                  data-tone={deltaUnavailable ? "neutral" : deltaTone}
                >
                  {!deltaUnavailable && deltaTone !== "neutral" ? (
                    <span aria-hidden="true">{deltaTone === "negative" ? "▼" : "▲"}</span>
                  ) : null}
                  <span aria-describedby="v2-change-definition" data-testid="v2-capital-change">
                    {deltaUnavailable ? "—" : wholeDelta(comparison.liquid_capital_net_delta)}
                  </span>
                  {!deltaUnavailable && comparison.liquid_capital_net_delta_pct ? (
                    // Backend rounds once to 0.1; the page only formats it.
                    <span data-testid="v2-capital-change-pct">
                      · {percentText(comparison.liquid_capital_net_delta_pct, 1, { signed: true })}
                    </span>
                  ) : null}
                </span>
                <span className={styles.note} id="v2-change-definition">
                  {comparedToLabel(comparison.previous, current)}
                </span>
              </p>
            ) : comparison?.availability === "previous_closed_report_unavailable" ? (
              <p className={styles.note}>
                <span>Пока нет базы сравнения</span> · появится после следующего закрытого отчёта
              </p>
            ) : null}
            <dl className={styles.heroMeta}>
              {/* Without capital snapshots the totals are unknown, not zero. */}
              <dt>Активы</dt>
              <dd>{unavailable ? "—" : whole(current.liquid_assets_total)}</dd>
              <dt>Обязательства</dt>
              <dd>
                {unavailable
                  ? "—"
                  : `${isPositive(current.included_debts) ? "−" : ""}${whole(current.included_debts)}`}
              </dd>
              {capitalGoal && !unavailable ? (
                goalReached(capitalGoal) ? (
                  <>
                    <dt>Цель {goalShort}</dt>
                    <dd>достигнута</dd>
                  </>
                ) : (
                  <>
                    <dt>До цели {goalShort}</dt>
                    <dd>
                      {whole(capitalGoal.achievement_forecast.remaining_amount)} ·{" "}
                      {goalPercent(capitalGoal)}
                    </dd>
                  </>
                )
              ) : null}
            </dl>
          </>
        ) : (
          <UiV2WidgetState retry={comparisonReady ? undefined : retryComparison} />
        )}
      </div>

      <div className={styles.heroChart}>
        <div className={styles.chartHead}>
          <span className={styles.legend}>
            <span>
              <i style={{ background: "var(--accent)" }} />
              Капитал, факт
            </span>
            {capitalGoal ? (
              <span>
                <i className={styles.legendDash} />
                Цель
              </span>
            ) : null}
          </span>
          <fieldset className={styles.segmented} aria-label="Период динамики капитала">
            {([3, 12, "all"] as const).map((value) => (
              <button
                aria-label={value === 3 ? "3 месяца" : value === 12 ? "12 месяцев" : "Всё время"}
                aria-pressed={window === value}
                key={value}
                onClick={() => setWindow(value)}
                type="button"
              >
                {value === 3 ? "3 мес" : value === 12 ? "12 мес" : "Всё"}
              </button>
            ))}
          </fieldset>
        </div>
        {!historyReady ? (
          <UiV2WidgetState retry={retryHistory} />
        ) : visible.length === 0 ? (
          <UiV2WidgetState title="История появится после закрытия первого отчёта" />
        ) : (
          <div
            className={styles.chart}
            data-gap-count={gapCount}
            data-point-count={visible.length}
            data-testid="v2-capital-history"
          >
            <CapitalAreaChart
              data={data}
              goal={goalTarget !== null ? { value: goalTarget, label: `цель ${goalShort}` } : null}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function PassiveBlock({
  history,
  ready,
  retry,
  passiveGoal,
}: {
  history: PassiveIncomeHistory | undefined;
  ready: boolean;
  retry: () => void;
  passiveGoal: GoalSummary | null;
}) {
  const selected = history?.selected_report ?? null;
  const average = history?.average;
  const eligible = history?.points.filter((point) => point.included_in_average_window) ?? [];
  const data: PassiveChartPoint[] = eligible.map((point) => ({
    key: `${point.year}-${point.month}`,
    label: shortMonthLabel(point.year, point.month, false),
    fullLabel: formatMonth(point.year, point.month),
    amount: point.passive_income_actual.amount,
    value: moneyToChartNumber(point.passive_income_actual.amount),
  }));
  const averageValue =
    average && average.count_months > 0 ? moneyToChartNumber(average.average.amount) : null;
  const goalValue = passiveGoal ? moneyToChartNumber(passiveGoal.target_value.amount) : null;
  const maxValue = Math.max(0, ...data.map((point) => point.value));
  // A goal far above the facts would flatten every bar; it stays in Goals.
  const showGoal = goalValue !== null && goalValue > 0 && goalValue <= Math.max(maxValue, 1) * 2.5;

  return (
    <section className={`${styles.block} ${styles.s7}`} aria-labelledby="passive-title">
      <BlockHead
        aside={
          <Link className={styles.link} to="/v2/income">
            Выплаты и прогноз →
          </Link>
        }
        id="passive-title"
        kicker="Получено · факт"
        title="Пассивный доход"
      />
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !selected || !average ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <>
          <div className={styles.figures}>
            <div>
              <p className={styles.midValue} data-testid="v2-passive-actual">
                {whole(selected.passive_income_actual)}
              </p>
              <p className={styles.note}>
                {formatMonth(selected.year, selected.month).toLocaleLowerCase("ru-RU")}
              </p>
            </div>
            <div>
              {average.count_months === 0 ? (
                <p className={`${styles.midValue} ${styles.secondary}`}>—</p>
              ) : (
                <p
                  className={`${styles.midValue} ${styles.secondary}`}
                  data-testid="v2-passive-average"
                >
                  {whole(average.average)}
                </p>
              )}
              <p className={styles.note}>
                {average.count_months === 0
                  ? "Пока нет данных"
                  : `среднее за ${average.target_window_months} мес`}{" "}
                <AverageHelp average={average} />
              </p>
            </div>
          </div>
          {data.length > 0 ? (
            <>
              <div
                className={styles.chart}
                data-point-count={data.length}
                data-testid="v2-passive-history"
              >
                <PassiveBarsChart
                  average={averageValue}
                  data={data}
                  goal={showGoal ? goalValue : null}
                />
              </div>
              <p className={styles.legend}>
                <span>
                  <i style={{ background: "var(--accent)" }} />
                  Факт
                </span>
                {averageValue !== null ? (
                  <span>
                    <i className={styles.legendLine} />
                    Среднее
                  </span>
                ) : null}
                {showGoal && goalValue !== null ? (
                  <span>
                    <i className={styles.legendDash} />
                    Цель {shortRub(goalValue)}
                  </span>
                ) : null}
              </p>
            </>
          ) : (
            <UiV2WidgetState title="Нет закрытой истории в выбранном периоде" />
          )}
          <PassiveSources history={history} />
        </>
      )}
    </section>
  );
}

function PassiveSources({ history }: { history: PassiveIncomeHistory | undefined }) {
  const selected = history?.selected_report;
  if (!selected) return null;
  const total = selected.breakdown.total_net_passive_income;
  const rows = PASSIVE_SOURCE_META.map(([key, label, color]) => ({
    key,
    label,
    color,
    amount: selected.breakdown[key],
  }));
  const shown = rows.filter((row) => toKopecks(row.amount.amount) !== 0n);
  if (shown.length === 0) return null;
  // Shares are meaningful only for a positive total of non-negative parts.
  const shareable = isPositive(total) && shown.every((row) => toKopecks(row.amount.amount) >= 0n);
  const share = (amount: MoneyValue) => moneySharePercent(amount.amount, total.amount, 1);
  return (
    <div className={styles.sources}>
      <p className={styles.note}>
        Из чего сложился {formatMonth(selected.year, selected.month).toLocaleLowerCase("ru-RU")}
      </p>
      {shareable ? (
        <div aria-hidden="true" className={styles.segBar}>
          {shown.map((row) => (
            <i key={row.key} style={{ flex: share(row.amount), background: row.color }} />
          ))}
        </div>
      ) : null}
      <ul className={styles.segLegend}>
        {shown.map((row) => (
          <li key={row.key}>
            <i aria-hidden="true" style={{ background: row.color }} />
            {row.label} <strong className="money">{whole(row.amount)}</strong>
            {shareable ? <span> · {percentText(share(row.amount), 0)}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AllocationBlock({
  comparison,
  ready,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const current = comparison?.current;
  const total = current?.liquid_assets_total;
  const slices = current?.allocation.filter((item) => toKopecks(item.amount.amount) > 0n) ?? [];
  const shareable = isPositive(total);
  const sorted = [...slices].sort((a, b) => {
    const diff = toKopecks(b.amount.amount) - toKopecks(a.amount.amount);
    return diff > 0n ? 1 : diff < 0n ? -1 : 0;
  });
  const rows = sorted.map((item) => ({
    key: item.asset_class,
    label: classMeta(item.asset_class).label,
    color: CLASS_COLOR[item.asset_class] ?? "var(--c-cash)",
    amount: item.amount,
    share: shareable && total ? moneySharePercent(item.amount.amount, total.amount, 1) : null,
  }));
  return (
    <section className={`${styles.block} ${styles.s5}`} aria-labelledby="composition-title">
      <BlockHead
        aside={
          <Link className={styles.link} to="/v2/capital">
            Капитал →
          </Link>
        }
        id="composition-title"
        kicker="Структура"
        title="Где лежат деньги"
      />
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !current ? (
        <UiV2WidgetState title="Нет закрытого снимка" />
      ) : current.portfolio_source_coverage?.status === "unavailable" ? (
        <UiV2WidgetState title="Нет снимков капитала" />
      ) : rows.length === 0 ? (
        <UiV2WidgetState title="В закрытом снимке нет положительных ликвидных активов" />
      ) : (
        <>
          {rows.every((row) => row.share !== null) ? (
            <div aria-hidden="true" className={styles.allocBar}>
              {rows.map((row) => (
                <i
                  key={row.key}
                  style={{ flex: Math.max(Number(row.share), 0.4), background: row.color }}
                  title={row.label}
                />
              ))}
            </div>
          ) : null}
          <ul className={styles.allocRows}>
            {rows.map((row) => (
              <li key={row.key}>
                <i aria-hidden="true" style={{ background: row.color }} />
                <span>{row.label}</span>
                <strong className="money">{whole(row.amount)}</strong>
                <span className={styles.share}>
                  {row.share === null
                    ? ""
                    : Number(row.share) < 0.1
                      ? "<0,1%"
                      : percentText(row.share, 1)}
                </span>
              </li>
            ))}
          </ul>
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
  const explanation = comparison?.explanation;
  const previous = comparison?.previous;
  const current = comparison?.current;
  const kicker =
    previous && current
      ? `${formatMonth(current.year, current.month).split(/\s/)[0]} ${comparedToLabel(previous, current)}`
      : "Изменение состояния";
  const steps: WaterfallStep[] = [];
  const rows: Array<{ key: string; label: string; amount: MoneyValue }> = [];
  if (explanation?.reconciles && previous && current) {
    steps.push({
      key: "start",
      label: formatMonth(previous.year, previous.month).split(/\s/)[0],
      kind: "start",
      value: moneyToChartNumber(previous.liquid_capital_net.amount),
      text: shortRub(moneyToChartNumber(previous.liquid_capital_net.amount)),
    });
    const push = (key: string, label: string, chartLabel: string, amount: MoneyValue) => {
      const value = moneyToChartNumber(amount.amount);
      rows.push({ key, label, amount });
      steps.push({
        key,
        label: chartLabel,
        kind: "step",
        value,
        text: `${value > 0 ? "+" : value < 0 ? "−" : ""}${shortRub(Math.abs(value))}`,
      });
    };
    for (const item of explanation.residual_asset_class_deltas) {
      const label = classMeta(item.asset_class).label;
      push(item.asset_class, label, label, item.amount);
    }
    push("debts", "Вклад обязательств", "Долги", explanation.residual_debt_contribution_delta);
    for (const pair of explanation.pairs) {
      const value = moneyToChartNumber(pair.net_contribution_delta.amount);
      steps.push({
        key: `pair-${pair.account_id}`,
        label: pair.account_name,
        kind: "step",
        value,
        text: `${value > 0 ? "+" : value < 0 ? "−" : ""}${shortRub(Math.abs(value))}`,
      });
    }
    steps.push({
      key: "end",
      label: formatMonth(current.year, current.month).split(/\s/)[0],
      kind: "end",
      value: moneyToChartNumber(current.liquid_capital_net.amount),
      text: shortRub(moneyToChartNumber(current.liquid_capital_net.amount)),
    });
  }
  return (
    <section className={`${styles.block} ${styles.s7}`} aria-labelledby="change-title">
      <BlockHead
        aside={<span className={styles.note}>по классам активов</span>}
        id="change-title"
        kicker={kicker}
        title="Что изменило капитал"
      />
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : comparison?.availability !== "available" ? (
        <UiV2WidgetState title="Нужны два закрытых отчёта для сравнения" />
      ) : !explanation?.reconciles || !previous || !current ? (
        <UiV2WidgetState title="Разложение изменения недоступно" retry={retry} />
      ) : (
        <>
          <div
            aria-hidden="true"
            className={styles.chart}
            data-step-count={steps.length}
            data-testid="v2-capital-waterfall"
          >
            <CapitalWaterfallChart steps={steps} />
          </div>
          <ul className={styles.visuallyHidden}>
            {rows.map((row) => (
              <li key={row.key}>
                <span>{row.label}</span>
                <strong data-tone={tone(row.amount)}>{wholeDelta(row.amount)}</strong>
              </li>
            ))}
          </ul>
          {explanation.pairs.length > 0 ? (
            <ul className={styles.pairs}>
              {explanation.pairs.map((pair) => (
                <li key={pair.account_id}>
                  <details>
                    <summary>{pair.account_name}</summary>
                    <p>Связанный счёт и кредитка — изменение чистого вклада.</p>
                    <p>
                      {formatMonth(previous.year, previous.month)}: счёт{" "}
                      {money(pair.previous.account_balance)}, {pair.previous.debt_name}{" "}
                      {money(pair.previous.debt_balance)}, чистый вклад{" "}
                      {money(pair.previous.net_contribution)}
                    </p>
                    <p>
                      {formatMonth(current.year, current.month)}: счёт{" "}
                      {money(pair.current.account_balance)}, {pair.current.debt_name}{" "}
                      {money(pair.current.debt_balance)}, чистый вклад{" "}
                      {money(pair.current.net_contribution)}
                    </p>
                  </details>
                  <strong className="money" data-tone={tone(pair.net_contribution_delta)}>
                    {wholeDelta(pair.net_contribution_delta)}
                  </strong>
                </li>
              ))}
            </ul>
          ) : null}
          <div className={styles.changeTotal}>
            <span>Изменение ликвидного капитала</span>
            <strong className="money" data-tone={tone(comparison.liquid_capital_net_delta)}>
              {comparison.liquid_capital_net_delta_coverage?.status === "unavailable"
                ? "—"
                : wholeDelta(comparison.liquid_capital_net_delta)}
            </strong>
            <PortfolioCoverageNote
              coverage={comparison.liquid_capital_net_delta_coverage}
              relatedCoverages={[
                previous.portfolio_source_coverage,
                current.portfolio_source_coverage,
              ]}
            />
            {explanation.noncomparable_account_ids.length > 0 ? (
              <HelpTip label="Почему часть счетов не объединена">
                Для части счетов нет явной связи на обоих отчётах: изменение пары недоступно, суммы
                сохранены в остальных строках.
              </HelpTip>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function ringStyle(pct: string | null): CSSProperties {
  const match = /^(\d+)(?:\.\d+)?$/.exec(pct ?? "");
  const value = match ? Math.min(100, Number(match[1])) : 0;
  return { "--goal-progress": String(value) } as CSSProperties;
}

/** Rounded percent that never reads as 100 % before the goal is reached. */
function goalPercent(goal: GoalSummary): string {
  const text = percentText(goal.achievement_forecast.progress_pct, 0);
  return text === "100%" && !goalReached(goal) ? "99%" : text;
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
  return (
    <section className={`${styles.block} ${styles.s5}`} aria-labelledby="goals-title">
      <BlockHead
        aside={
          <Link className={styles.link} to={uiV2GoalsPath(monthId)}>
            Все цели →
          </Link>
        }
        id="goals-title"
        kicker="Текущий прогресс"
        title="Цели"
      />
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : goals.length === 0 ? (
        <UiV2WidgetState title="Нет активных целей" />
      ) : (
        <ul className={styles.goals}>
          {goals.map((goal) => {
            const forecast = goal.achievement_forecast;
            return (
              <li key={goal.id}>
                <span
                  aria-hidden="true"
                  className={styles.ring}
                  style={ringStyle(forecast.progress_pct)}
                >
                  <span>{goalPercent(goal)}</span>
                </span>
                <div>
                  <h3>{goal.name}</h3>
                  <p className={styles.note}>
                    <span className="money">{whole(forecast.current_value)}</span> сейчас
                    {goalReached(goal) ? (
                      " · цель достигнута"
                    ) : forecast.remaining_amount ? (
                      <>
                        {" "}
                        · осталось <span className="money">{whole(forecast.remaining_amount)}</span>
                      </>
                    ) : null}
                  </p>
                  <p className={styles.visuallyHidden}>Прогресс {goalPercent(goal)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default function UiV2Page() {
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const { latestClosed, newestDraft: newerDraft } = selectNewestDraftAfterLatestClosed(months);
  const closedId = latestClosed?.id ?? null;

  const comparisonQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.closedReportComparisonBasic,
    queryFn: ({ signal }) => getClosedReportComparison(signal, false),
  });
  const compositionQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
  });
  const passiveQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.passiveIncomeHistory(closedId),
    queryFn: ({ signal }) => getPassiveIncomeHistory(closedId as number, signal),
  });
  const goalsQuery = useQuery({
    enabled: closedId !== null,
    queryKey: queryKeys.goalSummary(closedId),
    queryFn: ({ signal }) => listGoalSummary(closedId as number, {}, signal),
  });

  const monthsReady = isQueryReady(monthsQuery);
  const comparisonIdentityMatches =
    comparisonQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
    comparisonQuery.data.current?.reporting_month_id === closedId &&
    (comparisonQuery.data.previous?.reporting_month_id ?? null) ===
      (months.filter((month) => month.status === "closed")[1]?.id ?? null);
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
  const supportedGoals = goalsReady
    ? (goalsQuery.data ?? []).filter(
        (goal) =>
          goal.is_active &&
          goal.achievement_forecast.current_value !== null &&
          goal.achievement_forecast.progress_pct !== null &&
          (goal.goal_type !== "passive_income" ||
            (goal.achievement_forecast.passive_income_months_count ?? 0) > 0),
      )
    : [];
  const capitalGoal = pageGoal(supportedGoals, "capital", "liquid_capital_net");
  const passiveGoal = pageGoal(supportedGoals, "passive_income", "monthly_net_passive_income");
  const loading = !monthsReady;

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2WidgetState title="Не удалось загрузить" retry={() => void monthsQuery.refetch()} />
    );
  } else if (!monthsReady) {
    content = (
      <p className={pageStyles.loading} role="status">
        Проверяем последние закрытые отчёты…
      </p>
    );
  } else if (!latestClosed) {
    content = (
      <>
        {newerDraft ? <DraftAction draft={newerDraft} /> : null}
        <UiV2Notice title="Закрой первый отчёт">
          <Link to="/v2/close">Закрой первый месяц →</Link>
        </UiV2Notice>
      </>
    );
  } else {
    content = (
      <>
        {newerDraft ? <DraftAction draft={newerDraft} /> : null}
        <CapitalHero
          capitalGoal={capitalGoal}
          comparison={comparisonReady ? comparisonQuery.data : undefined}
          comparisonReady={comparisonReady}
          historyReady={compositionReady}
          points={compositionReady ? (compositionQuery.data?.points ?? []) : []}
          retryComparison={() => void comparisonQuery.refetch()}
          retryHistory={() => void compositionQuery.refetch()}
        />
        <div className={styles.grid}>
          <PassiveBlock
            history={passiveReady ? passiveQuery.data : undefined}
            passiveGoal={passiveGoal}
            ready={passiveReady}
            retry={() => void passiveQuery.refetch()}
          />
          <AllocationBlock
            comparison={comparisonReady ? comparisonQuery.data : undefined}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <ChangeBlock
            comparison={comparisonReady ? comparisonQuery.data : undefined}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <GoalsBlock
            goals={supportedGoals}
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
        <div className={styles.head}>
          <h1>Мои финансы</h1>
          {latestClosed ? (
            <span className={styles.chip} data-testid="v2-report-context">
              {formatMonth(latestClosed.year, latestClosed.month)} · закрыт · снимок{" "}
              {formatDate(latestClosed.snapshot_date)}
            </span>
          ) : null}
          {latestClosed ? (
            <Link className={styles.link} to="/v2/reports">
              История отчётов →
            </Link>
          ) : null}
        </div>
      }
    >
      {content}
    </UiV2Shell>
  );
}
