import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { getPassiveIncomeHistory } from "../api/analytics";
import { getCashFlowLadder } from "../api/cashFlowLadder";
import { listMonths } from "../api/months";
import { plannedVsActual } from "../api/plannedBudget";
import { listSavings } from "../api/savings";
import { getIncomePlanSummary } from "../api/summary";
import type {
  CashFlowLadder,
  CashFlowLadderEvent,
  CashFlowLadderMonth,
  IncomePlanCoverage,
  IncomePlanSummary,
  MoneyValue,
  PassiveIncomeAverage,
  PassiveIncomeHistory,
  PassiveIncomeSelectedReport,
  PlanVsActualRow,
  ReportingMonth,
  SavingAllocation,
  UpcomingEventsWindow,
} from "../api/types";
import { HelpTip } from "../components/ui";
import { formatDate, formatMonth, formatPercent } from "../lib/format";
import { queryKeys } from "../queryClient";
import { ClosedReportTitle } from "./ClosedReportTitle";
import { IncomeFactBars } from "./IncomeFactBars";
import { sortReportingMonths } from "./monthSelection";
import sheet from "./ReportSheet.module.css";
import { uiV2TaxIisPath } from "./taxIisRoute";
import incomeStyles from "./UiV2Income.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import {
  accountingStartLabel,
  eventLabel as ownerEventLabel,
  sourceLabel as ownerSourceLabel,
  PRINCIPAL_REPAYMENT_LABEL,
} from "./uiV2Copy";
import { moneyText as money } from "./valueFormat";

type FactSelection = {
  month: ReportingMonth | null;
  valid: boolean;
};

type LadderWindow = 14 | 30 | 12;

/** Passive sources in display order, each with its asset-class colour. */
const PASSIVE_SOURCE_META = [
  ["deposit_interest", "Проценты по депозитам", "var(--c-dep)"],
  ["bond_coupons", "Купоны", "var(--c-bond)"],
  ["dividends", "Дивиденды", "var(--c-stock)"],
  ["other_capital_income", "Прочий доход от капитала", "var(--c-cash)"],
] as const;

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** Chart window in closed reports; older reports stay one click away. */
const CHART_WINDOW = 12;

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

/** Geometry only: widths never feed a shown amount. */
function coordinate(value: MoneyValue | null | undefined): number | null {
  if (!value) return null;
  const number = Number(value.amount);
  return Number.isFinite(number) ? number : null;
}

function isZeroMoney(value: MoneyValue | null | undefined): boolean {
  return value != null && /^-?0(?:\.0+)?$/.test(value.amount.trim());
}

function averageDetail(average: PassiveIncomeAverage): ReactNode {
  const boundary = accountingStartLabel(average.configured_start_month);
  return (
    <HelpTip label="Период среднего дохода">
      {average.count_months} из {average.target_window_months} закрытых отчётов
      {boundary ? ` · учёт ${boundary}` : " · вся доступная история"}
    </HelpTip>
  );
}

function shortDate(value: string): { day: string; weekday: string } {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return { day: formatDate(value), weekday: "" };
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return { day: `${match[3]}.${match[2]}`, weekday: WEEKDAYS[date.getUTCDay()] };
}

function Section({
  children,
  eyebrow,
  title,
  titleId,
  actions,
  testId,
  help,
}: {
  children: ReactNode;
  eyebrow: string;
  title: string;
  titleId: string;
  actions?: ReactNode;
  testId: string;
  help?: ReactNode;
}) {
  return (
    <section aria-labelledby={titleId} className={sheet.section} data-testid={testId}>
      <div className={sheet.sectionHead}>
        <div>
          <p className={sheet.eyebrow}>{eyebrow}</p>
          <h2 id={titleId}>
            {title}
            {help}
          </h2>
        </div>
        {actions ? <div className={sheet.sectionActions}>{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

function Headlines({
  history,
  historyReady,
  ladder,
  ladderReady,
  selected,
  retryHistory,
  retryLadder,
}: {
  history: PassiveIncomeHistory | undefined;
  historyReady: boolean;
  ladder: CashFlowLadder | undefined;
  ladderReady: boolean;
  selected: PassiveIncomeSelectedReport | null;
  retryHistory: () => void;
  retryLadder: () => void;
}) {
  const averageMeasured = historyReady && history !== undefined && history.average.count_months > 0;
  const upcoming = ladderReady ? ladder?.upcoming_30_days : undefined;
  return (
    <section aria-label="Главные показатели дохода" className={sheet.figures}>
      {selected ? (
        <div className={sheet.figure}>
          <span className={sheet.figureValue} data-testid="income-selected-actual">
            {money(selected.passive_income_actual)}
          </span>
          <span className={sheet.figureLabel}>{formatMonth(selected.year, selected.month)}</span>
        </div>
      ) : null}
      <div className={sheet.figure}>
        {historyReady && history ? (
          <>
            <span className={sheet.figureValue} data-testid="income-average">
              {averageMeasured ? money(history.average.average) : "Недоступно"}
            </span>
            <span className={sheet.figureLabel}>
              {history.average.count_months === 0 ? "Пока нет данных · " : null}
              среднее за {history.average.target_window_months} мес
              {averageDetail(history.average)}
            </span>
          </>
        ) : (
          <>
            <span className={sheet.figureLabel}>Среднее за 12 мес</span>
            <UiV2WidgetState retry={retryHistory} />
          </>
        )}
      </div>
      <div className={sheet.figure} data-kind="forecast">
        {ladderReady && upcoming ? (
          <>
            <span className={sheet.figureValue} data-testid="income-upcoming-passive">
              {money(upcoming.forecast_passive_income ?? upcoming.passive_income)}
            </span>
            <span className={sheet.figureLabel}>ожидается за 30 дней</span>
            <span className={sheet.figureDetail}>
              {PRINCIPAL_REPAYMENT_LABEL}: {money(upcoming.redemption_principal)} · не доход
              {Boolean(upcoming.deposit_estimates?.some((row) => row.included_in_forecast)) && (
                <>
                  <br />
                  Включая расчётные проценты по вкладам: {money(upcoming.deposit_interest_estimate)}
                </>
              )}
            </span>
          </>
        ) : (
          <>
            <span className={sheet.figureLabel}>Ожидается за 30 дней</span>
            <UiV2WidgetState retry={retryLadder} />
          </>
        )}
      </div>
    </section>
  );
}

function SourceBreakdown({ report }: { report: PassiveIncomeSelectedReport }) {
  const parts = PASSIVE_SOURCE_META.map(([key, label, color]) => ({
    key,
    label,
    color,
    amount: report.breakdown[key],
    value: coordinate(report.breakdown[key]),
  }));
  const total = parts.reduce((sum, part) => sum + (part.value ?? 0), 0);
  // The strip only shows a split of a positive whole; otherwise the legend alone is honest.
  const drawStrip = total > 0 && parts.every((part) => part.value !== null && part.value >= 0);
  return (
    <div className={incomeStyles.breakdown}>
      <p className={incomeStyles.breakdownTitle}>
        <span>Источники · {formatMonth(report.year, report.month)}</span>
        <HelpTip label="Что входит в пассивный доход">
          Только фактический доход от капитала. Зарплата, бонусы, вознаграждения за покупки и
          возврат основной суммы сюда не входят.
        </HelpTip>
      </p>
      {drawStrip ? (
        <div aria-hidden="true" className={sheet.strip}>
          {parts
            .filter((part) => (part.value ?? 0) > 0)
            .map((part) => (
              <span
                key={part.key}
                style={{ background: part.color, flexGrow: part.value ?? 0, flexBasis: 0 }}
              />
            ))}
        </div>
      ) : null}
      <ul className={incomeStyles.sourceList}>
        {parts.map((part) => (
          <li data-zero={isZeroMoney(part.amount) || undefined} key={part.key}>
            <i aria-hidden="true" className={sheet.dot} style={{ background: part.color }} />
            <span>{part.label}</span>
            <strong className={sheet.amount}>{money(part.amount)}</strong>
          </li>
        ))}
        <li className={incomeStyles.sourceTotal}>
          <i aria-hidden="true" />
          <span>Всего чистого пассивного дохода</span>
          <strong className={sheet.amount}>{money(report.passive_income_actual)}</strong>
        </li>
      </ul>
    </div>
  );
}

function PassiveSection({
  history,
  historyReady,
  factHistory,
  factReady,
  ladder,
  ladderReady,
  goal,
  selectedMonth,
  closedMonths,
  selectionValid,
  onSelect,
  retryHistory,
  retryFact,
  retryLadder,
}: {
  history: PassiveIncomeHistory | undefined;
  historyReady: boolean;
  factHistory: PassiveIncomeHistory | undefined;
  factReady: boolean;
  ladder: CashFlowLadder | undefined;
  ladderReady: boolean;
  goal: MoneyValue | null;
  selectedMonth: ReportingMonth | null;
  closedMonths: ReportingMonth[];
  selectionValid: boolean;
  onSelect: (monthId: number) => void;
  retryHistory: () => void;
  retryFact: () => void;
  retryLadder: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const points = history?.points ?? [];
  const selectedIndex = points.findIndex((point) => point.reporting_month_id === selectedMonth?.id);
  // A selected month older than the window keeps the whole history in view.
  const selectedOlder = selectedIndex !== -1 && selectedIndex < points.length - CHART_WINDOW;
  const windowed = points.length > CHART_WINDOW && !showAll && !selectedOlder;
  const visible = windowed ? points.slice(-CHART_WINDOW) : points;
  const selected = factReady ? (factHistory?.selected_report ?? null) : null;
  const averageMeasured = historyReady && history !== undefined && history.average.count_months > 0;
  return (
    <Section
      actions={
        <>
          {points.length > CHART_WINDOW ? (
            <fieldset aria-label="Период графика" className={sheet.segmented}>
              <button
                aria-pressed={windowed}
                disabled={selectedOlder}
                onClick={() => setShowAll(false)}
                type="button"
              >
                12 мес
              </button>
              <button aria-pressed={!windowed} onClick={() => setShowAll(true)} type="button">
                Всё
              </button>
            </fieldset>
          ) : null}
          <label className={sheet.select}>
            <span>Месяц</span>
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
        </>
      }
      eyebrow="Получено · факт закрытых отчётов"
      testId="income-history-panel"
      title="Пассивный доход"
      titleId="income-history-title"
    >
      <Headlines
        history={history}
        historyReady={historyReady}
        ladder={ladder}
        ladderReady={ladderReady}
        retryHistory={retryHistory}
        retryLadder={retryLadder}
        selected={selected}
      />
      {!historyReady ? null : points.length === 0 ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <div className={incomeStyles.factLayout}>
          <IncomeFactBars
            average={averageMeasured ? (history?.average.average ?? null) : null}
            goal={goal}
            onSelect={onSelect}
            points={visible}
            selectedId={selectionValid ? (selectedMonth?.id ?? null) : null}
          />
          {!selectionValid ? (
            <UiV2WidgetState title="Выберите только закрытый отчёт для фактической разбивки" />
          ) : !factReady ? (
            <UiV2WidgetState retry={retryFact} />
          ) : selected ? (
            <SourceBreakdown report={selected} />
          ) : (
            <UiV2WidgetState title="История появится после закрытия первого отчёта" />
          )}
        </div>
      )}
    </Section>
  );
}

function EventRow({ event }: { event: CashFlowLadderEvent }) {
  const principal = event.component === "redemption_principal";
  const date = shortDate(event.expected_date);
  return (
    <li
      className={incomeStyles.event}
      data-component={event.component}
      data-testid={`income-event-${event.source_kind}-${event.source_id}`}
    >
      <span className={incomeStyles.eventWhen}>
        <time dateTime={event.expected_date}>
          {date.day}
          <small>{date.weekday}</small>
        </time>
        <span className={incomeStyles.tag} data-component={event.component}>
          {principal ? (
            <abbr title={PRINCIPAL_REPAYMENT_LABEL}>Погашение</abbr>
          ) : (
            ownerEventLabel(event.component)
          )}
        </span>
      </span>
      <span className={incomeStyles.eventWhat}>
        <strong>{event.instrument_name ?? "Без инструмента"}</strong>
        <small className={incomeStyles.eventAccount}>{event.account_name}</small>
      </span>
      <strong className={incomeStyles.eventAmount} data-principal={principal || undefined}>
        {event.is_approximate ? (
          <abbr className={incomeStyles.approx} title="оценка">
            ≈{" "}
          </abbr>
        ) : null}
        {money(event.expected_net_amount)}
        {principal ? " · не доход" : ""}
      </strong>
    </li>
  );
}

/** Where the dated events come from and whether any is an estimate, said once. */
function EventSources({ events }: { events: CashFlowLadderEvent[] }) {
  if (events.length === 0) return null;
  const sources = Array.from(new Set(events.map((event) => ownerSourceLabel(event.source_kind))));
  const approximate = events.some((event) => event.is_approximate);
  return (
    <p className={sheet.gapNote}>
      Источник: {sources.join(", ")}
      {approximate ? " · ≈ — оценка" : ""}
    </p>
  );
}

function EventList({ events }: { events: CashFlowLadderEvent[] }) {
  if (events.length === 0) {
    return <p className={sheet.muted}>Нет известных событий в этом окне.</p>;
  }
  return (
    <ul className={incomeStyles.timeline}>
      {events.map((event) => (
        <EventRow
          event={event}
          key={`${event.source_kind}-${event.source_id}-${event.expected_date}`}
        />
      ))}
    </ul>
  );
}

function WindowSummary({ window: selected }: { window: UpcomingEventsWindow }) {
  return (
    <div className={incomeStyles.windowSummary} data-testid={`income-window-${selected.days}`}>
      <p className={incomeStyles.windowTotals}>
        <span>
          <strong className={sheet.amount}>{money(selected.passive_income)}</strong> пассивно
        </span>
        {isZeroMoney(selected.redemption_principal) ? null : (
          <span>
            {PRINCIPAL_REPAYMENT_LABEL}{" "}
            <strong className={sheet.amount} data-principal>
              {money(selected.redemption_principal)}
            </strong>{" "}
            · не доход
          </span>
        )}
        <span>
          Всего поступлений{" "}
          <strong className={sheet.amount}>{money(selected.total_cash_flow)}</strong>
        </span>
        <span className={sheet.muted}>
          {formatDate(selected.from_date)}–{formatDate(selected.to_date)}
        </span>
      </p>
      <EventList events={selected.items} />
      <EventSources events={selected.items} />
    </div>
  );
}

function LadderMonth({ month, max }: { month: CashFlowLadderMonth; max: number }) {
  const value = coordinate(month.passive_income) ?? 0;
  const width = max > 0 ? `${(Math.max(0, value) / max) * 100}%` : "0%";
  const row = (
    <>
      <span className={incomeStyles.monthName}>{formatMonth(month.year, month.month)}</span>
      <span aria-hidden="true" className={incomeStyles.monthTrack}>
        <span style={{ width }} />
      </span>
      <strong className={`${sheet.amount} ${incomeStyles.monthAmount}`}>
        {month.is_approximate ? (
          <abbr className={incomeStyles.approx} title="оценка">
            ≈{" "}
          </abbr>
        ) : null}
        {money(month.passive_income)}
      </strong>
      <span className={incomeStyles.monthPrincipal}>
        {isZeroMoney(month.redemption_principal)
          ? null
          : `+ ${money(month.redemption_principal)} возврат`}
      </span>
    </>
  );
  if (month.items.length === 0) {
    return <li className={incomeStyles.monthRow}>{row}</li>;
  }
  return (
    <li>
      <details className={incomeStyles.monthDetails}>
        <summary className={incomeStyles.monthRow}>{row}</summary>
        <div className={incomeStyles.monthBody}>
          <p className={sheet.muted}>
            Всего поступлений {money(month.total_cash_flow)}
            {isZeroMoney(month.redemption_principal)
              ? ""
              : ` · ${PRINCIPAL_REPAYMENT_LABEL.toLowerCase()} ${money(month.redemption_principal)} не доход`}
          </p>
          <EventList events={month.items} />
          <EventSources events={month.items} />
        </div>
      </details>
    </li>
  );
}

function DepositEstimates({ upcoming }: { upcoming: UpcomingEventsWindow }) {
  if (!upcoming.deposit_estimates?.length) return null;
  return (
    <section aria-label="Ожидаемые проценты по вкладам" className={incomeStyles.depositForecast}>
      <h3>
        Проценты по вкладам · 30 дней
        <HelpTip label="Как рассчитаны проценты по вкладам">
          Период до конечной даты, не включая её. Остаток × годовая ставка × дни / число дней в
          году, при неизменных остатке и ставке, без капитализации и вычета налога. Для счетов с
          датированными процентами за этот период учитываются только эти выплаты.
        </HelpTip>
      </h3>
      <p className={sheet.muted}>
        Расчётная сумма за {formatDate(upcoming.from_date)}–{formatDate(upcoming.to_date)}; дата
        выплаты неизвестна. Включённые оценки уже учтены в общем прогнозе.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Вклад</th>
            <th scope="col">Оценка процентов</th>
          </tr>
        </thead>
        <tbody>
          {upcoming.deposit_estimates.map((row) => (
            <tr key={row.deposit_id}>
              <td>
                {row.name} · {row.account_name}
                {!row.included_in_forecast && (
                  <small>
                    {" "}
                    · В общий прогноз не добавлено: на счёте есть датированные проценты
                  </small>
                )}
              </td>
              <td className={sheet.amount}>{money(row.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function LadderSection({
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
  const monthMax = Math.max(
    0,
    ...(ladder?.months.map((month) => coordinate(month.passive_income) ?? 0) ?? []),
  );
  return (
    <Section
      actions={
        ready && ladder ? (
          <fieldset
            aria-controls="income-ladder-content"
            aria-label="Окно ожидаемых выплат"
            className={sheet.segmented}
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
        ) : null
      }
      eyebrow="Прогноз · датированные события"
      testId="income-ladder-panel"
      title="Ожидаемые выплаты"
      titleId="income-ladder-title"
    >
      {!ready || !ladder ? (
        <UiV2WidgetState retry={retry} />
      ) : (
        <>
          <div id="income-ladder-content">
            {window !== 12 && selectedWindow ? (
              <WindowSummary window={selectedWindow} />
            ) : (
              <ul aria-label="Выплаты по месяцам" className={incomeStyles.monthList}>
                {ladder.months.map((month) => (
                  <LadderMonth key={`${month.year}-${month.month}`} max={monthMax} month={month} />
                ))}
              </ul>
            )}
          </div>
          <DepositEstimates upcoming={ladder.upcoming_30_days} />
          {ladder.warnings.length > 0 ? (
            <ul className={incomeStyles.warningList}>
              {ladder.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Section>
  );
}

function Coverage({ coverage }: { coverage: IncomePlanCoverage }) {
  const pct = coverage.coverage_pct === null ? null : Number(coverage.coverage_pct);
  const width = pct === null || !Number.isFinite(pct) ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div className={incomeStyles.coverage} data-testid="income-coverage">
      <span className={incomeStyles.coverageValue}>
        {formatPercent(coverage.coverage_pct, { digits: 1, empty: "Недоступно" })}
      </span>
      <span className={sheet.figureLabel}>
        По прогнозу пассивный доход покрывает обязательные расходы
      </span>
      {pct !== null ? (
        <span aria-hidden="true" className={incomeStyles.coverageTrack}>
          <span style={{ width: `${width}%` }} />
        </span>
      ) : null}
      <span className={sheet.figureDetail}>
        Обязательные расходы {money(coverage.mandatory_expenses)} · прогнозный остаток{" "}
        {money(coverage.passive_income_minus_mandatory_expenses)}
      </span>
      <span className={sheet.figureDetail}>
        По среднему фактическому доходу:{" "}
        {formatPercent(coverage.actual_mandatory_expense_coverage_pct, {
          digits: 1,
          empty: "Недоступно",
        })}
      </span>
    </div>
  );
}

function PlanTable({ rows }: { rows: PlanVsActualRow[] }) {
  const visible = rows.filter((row) => row.planned !== null || row.actual !== null);
  const max = Math.max(
    0,
    ...visible.flatMap((row) => [coordinate(row.planned) ?? 0, coordinate(row.actual) ?? 0]),
  );
  const groups = [
    { title: "Обязательные", rows: visible.filter((row) => row.expense_type === "mandatory") },
    { title: "Остальные", rows: visible.filter((row) => row.expense_type !== "mandatory") },
  ].filter((group) => group.rows.length > 0);
  const share = (value: MoneyValue | null) => {
    const number = coordinate(value);
    return number === null || max <= 0 ? null : `${(Math.max(0, number) / max) * 100}%`;
  };
  return (
    <table className={incomeStyles.planTable}>
      <caption className={sheet.visuallyHidden}>План и факт расходов</caption>
      <thead>
        <tr>
          <th scope="col">Статья</th>
          <td />
          <th scope="col">Факт</th>
          <th scope="col">План</th>
        </tr>
      </thead>
      {groups.map((group) => (
        <tbody key={group.title}>
          {groups.length > 1 ? (
            <tr className={incomeStyles.planGroup}>
              <th colSpan={4} scope="colgroup">
                {group.title}
              </th>
            </tr>
          ) : null}
          {group.rows.map((row) => {
            const actual = share(row.actual);
            const planned = share(row.planned);
            return (
              <tr key={`${row.expense_type}-${row.category}`}>
                <th scope="row">{row.category}</th>
                <td aria-hidden="true" className={incomeStyles.planBarCell}>
                  <span className={incomeStyles.planBar}>
                    {actual ? (
                      <span className={incomeStyles.planFact} style={{ width: actual }} />
                    ) : null}
                    {planned ? (
                      <span className={incomeStyles.planMark} style={{ left: planned }} />
                    ) : null}
                  </span>
                </td>
                <td className={sheet.amount}>{row.actual ? money(row.actual) : "—"}</td>
                <td className={`${sheet.amount} ${incomeStyles.planCell}`}>
                  {row.planned ? money(row.planned) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}

function PlanSection({
  coverage,
  coverageReady,
  budget,
  budgetReady,
  savings,
  savingsReady,
  savingTotal,
  retryCoverage,
  retryBudget,
  retrySavings,
}: {
  coverage: IncomePlanCoverage | undefined;
  coverageReady: boolean;
  budget: PlanVsActualRow[];
  budgetReady: boolean;
  savings: SavingAllocation[];
  savingsReady: boolean;
  savingTotal: IncomePlanSummary["cash_balance"] | undefined;
  retryCoverage: () => void;
  retryBudget: () => void;
  retrySavings: () => void;
}) {
  return (
    <Section
      eyebrow="План · последний закрытый отчёт"
      testId="income-plan-panel"
      title="Расходы и накопления"
      titleId="income-plan-title"
    >
      {!coverageReady ? (
        <UiV2WidgetState retry={retryCoverage} />
      ) : !coverage ? (
        <UiV2WidgetState title="Покрытие расходов недоступно" retry={retryCoverage} />
      ) : (
        <Coverage coverage={coverage} />
      )}
      <div className={incomeStyles.planBlock}>
        <h3>План и факт расходов</h3>
        {!budgetReady ? (
          <UiV2WidgetState retry={retryBudget} />
        ) : budget.length === 0 ? (
          <p className={sheet.muted}>План расходов не задан.</p>
        ) : (
          <PlanTable rows={budget} />
        )}
      </div>
      <div className={incomeStyles.planBlock}>
        <h3>Накопления</h3>
        {!savingsReady ? (
          <UiV2WidgetState retry={retrySavings} />
        ) : savings.length === 0 ? (
          <p className={sheet.muted}>Накопления не заданы.</p>
        ) : (
          <ul className={incomeStyles.savingList}>
            {savings.map((saving) => (
              <li key={saving.id}>
                <span>{saving.destination}</span>
                <strong className={sheet.amount}>{money(saving.amount)}</strong>
              </li>
            ))}
            {savingTotal?.breakdown.saving_allocations ? (
              <li className={incomeStyles.savingTotal}>
                <span>Всего за месяц</span>
                <strong className={sheet.amount}>
                  {money(savingTotal.breakdown.saving_allocations)}
                </strong>
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </Section>
  );
}

function Handoffs({ taxIisPath }: { taxIisPath: string }) {
  return (
    <nav
      aria-label="Дополнительные разделы"
      className={sheet.footerLinks}
      data-testid="income-handoffs-panel"
    >
      <span className={sheet.muted}>Ещё по доходу:</span>
      <span>
        <Link to={taxIisPath}>Налоги и ИИС →</Link>{" "}
        <span className={sheet.muted}>НДФЛ и ИИС по выбранному отчётному срезу.</span>
      </span>
      <Link to="/v2/income/scenario-lab">Сценарии →</Link>
    </nav>
  );
}

export default function UiV2IncomePage() {
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
  const taxIisPath = uiV2TaxIisPath(params, planningId);

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

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2WidgetState title="Не удалось загрузить" retry={() => void monthsQuery.refetch()} />
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем последний закрытый отчёт…" />;
  } else if (!latestClosed) {
    content = (
      <UiV2Notice title="Закрой первый отчёт">
        <Link to="/v2/close">Закрой первый месяц →</Link>
      </UiV2Notice>
    );
  } else {
    const summary = summaryReady ? summaryQuery.data : undefined;
    const goal = summary?.coverage.goal_target ?? null;
    content = (
      <div className={sheet.sheet}>
        <PassiveSection
          closedMonths={closedMonths}
          factHistory={factHistoryReady ? factHistoryQuery.data : undefined}
          factReady={factHistoryReady}
          goal={goal && !isZeroMoney(goal) ? goal : null}
          history={headlineHistoryReady ? headlineHistoryQuery.data : undefined}
          historyReady={headlineHistoryReady}
          ladder={ladderReady ? ladderQuery.data : undefined}
          ladderReady={ladderReady}
          onSelect={selectFactMonth}
          retryFact={() => void factHistoryQuery.refetch()}
          retryHistory={() => void headlineHistoryQuery.refetch()}
          retryLadder={() => void ladderQuery.refetch()}
          selectedMonth={factSelection.month}
          selectionValid={factSelection.valid}
        />
        <div className={sheet.columns}>
          <LadderSection
            ladder={ladderReady ? ladderQuery.data : undefined}
            ready={ladderReady}
            retry={() => void ladderQuery.refetch()}
          />
          <PlanSection
            budget={budgetReady ? (budgetQuery.data ?? []) : []}
            budgetReady={budgetReady}
            coverage={summary?.coverage}
            coverageReady={coverageReady}
            retryBudget={() => void budgetQuery.refetch()}
            retryCoverage={() => void summaryQuery.refetch()}
            retrySavings={() => void savingsQuery.refetch()}
            savingTotal={summary?.cash_balance}
            savings={savingsReady ? (savingsQuery.data ?? []) : []}
            savingsReady={savingsReady}
          />
        </div>
        <Handoffs taxIisPath={taxIisPath} />
      </div>
    );
  }

  return (
    <UiV2Shell
      active="income"
      busy={!monthsReady}
      header={
        <>
          <ClosedReportTitle
            links={
              latestClosed ? (
                <Link to={`/v2/data/months/${latestClosed.id}`}>Данные отчётного месяца →</Link>
              ) : null
            }
            month={latestClosed}
            title="Доход и планы"
          />
          {newerDraft ? (
            <p className={sheet.draftNote} data-testid="income-draft-note">
              {formatMonth(newerDraft.year, newerDraft.month)} ещё не закрыт — показан последний
              закрытый отчёт.
            </p>
          ) : null}
        </>
      }
    >
      {content}
    </UiV2Shell>
  );
}
