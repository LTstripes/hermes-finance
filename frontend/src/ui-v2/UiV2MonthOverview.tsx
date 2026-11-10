import type { ReactNode } from "react";
import { Link } from "react-router";

import type {
  MonthChecklist,
  MonthChecklistStep,
  MonthChecklistStepId,
  MonthCloseWorkflow,
} from "../api/monthCloseWorkflow";
import type { MoneyValue } from "../api/types";
import { closeOwnerActionFindings } from "../components/month-close/ownerCopy";
import { PortfolioCoverageNote } from "../components/PortfolioCoverageNote";
import { formatDate, formatPercent } from "../lib/format";
import styles from "./UiV2MonthOverview.module.css";
import {
  moneyText,
  moneyDeltaText,
  moneyTone,
  moneyWholeText,
  moneyWholeDeltaText,
} from "./valueFormat";

type StepCopy = { label: string; hint: string };

/** Section names stay the same as the month editor panels they open. */
export const MONTH_STEP_COPY: Record<MonthChecklistStepId, StepCopy> = {
  general: { label: "Снимок и общие данные", hint: "Дата снимка и источник" },
  income: { label: "Зарплата и другие доходы", hint: "Ручные поступления" },
  assets: { label: "Депозиты, накопления и деньги", hint: "Остатки и проценты" },
  liabilities: { label: "Долги, кредитка и недвижимость", hint: "Долг, ипотека и платежи" },
  positions: { label: "Счета и позиции", hint: "Количество и оценка" },
  brokers: { label: "Брокерские выписки", hint: "Загрузка и разбор источников" },
  payouts: { label: "Выплаты", hint: "Полученные и прогноз T-Invest" },
  budget: { label: "Расходы и план", hint: "Обязательные расходы и откладывание" },
  note: { label: "Комментарии", hint: "Пояснения к месяцу" },
  close: { label: "Закрыть месяц", hint: "Итоговая проверка" },
};

/** P order: personal data, statements before dependent positions and payouts, then notes. */
const STEP_ORDER: MonthChecklistStepId[] = [
  "general",
  "income",
  "assets",
  "liabilities",
  "budget",
  "brokers",
  "positions",
  "payouts",
  "note",
  "close",
];

const GROUPS = [
  { id: "data", title: "Данные месяца" },
  { id: "sources", title: "Выписки и портфель" },
  { id: "plan", title: "Итог" },
] as const;

const STATE_TEXT: Record<MonthChecklistStep["state"], string> = {
  done: "заполнено",
  attention: "требует решения",
  empty: "не заполнено",
  optional: "необязательно",
};

function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100;
  const units = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}

function countText(count: number, forms: [string, string, string]): string {
  return `${count} ${plural(count, ...forms)}`;
}

const COUNT_FORMS: Partial<Record<MonthChecklistStepId, [string, string, string]>> = {
  brokers: ["выписка", "выписки", "выписок"],
  payouts: ["выплата", "выплаты", "выплат"],
  note: ["комментарий", "комментария", "комментариев"],
};

export function figureText(step: MonthChecklistStep): string {
  const figure = step.figure;
  if (!figure) return "—";
  if (figure.kind === "date") return formatDate(figure.day);
  if (figure.kind === "money") return moneyText(figure.amount, "—");
  const forms = COUNT_FORMS[step.id];
  return figure.count == null ? "—" : forms ? countText(figure.count, forms) : String(figure.count);
}

function hintText(
  step: MonthChecklistStep | undefined,
  id: MonthChecklistStepId,
  closed: boolean,
): string {
  const base = MONTH_STEP_COPY[id].hint;
  if (!step || closed) return base;
  if (step.state === "attention") {
    const count = step.attention_count;
    return `${countText(count, ["замечание", "замечания", "замечаний"])} ${count === 1 ? "требует" : "требуют"} решения`;
  }
  if (step.state === "empty") return "Не заполнено";
  if (step.state === "optional") return "Необязательно";
  const secondary = step.secondary_count;
  if (secondary == null) return base;
  if (id === "positions") return countText(secondary, ["позиция", "позиции", "позиций"]);
  if (id === "budget") return countText(secondary, ["статья", "статьи", "статей"]);
  if (id === "payouts")
    return secondary
      ? `Ожидается ещё ${countText(secondary, ["выплата", "выплаты", "выплат"])}`
      : base;
  return base;
}

function presentationState(state: MonthChecklistStep["state"] | undefined, closed: boolean) {
  return closed && state === "attention" ? "noted" : state;
}

function stateText(state: MonthChecklistStep["state"], closed: boolean) {
  return closed && state === "attention" ? "есть замечания" : STATE_TEXT[state];
}

function StateMark({
  state,
  closed = false,
}: {
  state: MonthChecklistStep["state"] | undefined;
  closed?: boolean;
}) {
  const symbol = state === "done" ? "✓" : state === "attention" ? (closed ? "·" : "!") : "";
  return (
    <span
      aria-hidden="true"
      className={styles.mark}
      data-state={presentationState(state, closed) ?? "unknown"}
    >
      {symbol}
    </span>
  );
}

function stepsById(checklist: MonthChecklist | undefined) {
  return new Map(checklist?.steps.map((step) => [step.id, step]) ?? []);
}

/** Compact section strip while one section is open. */
export function MonthStepStrip({
  checklist,
  current,
  pathFor,
  closed = false,
}: {
  checklist: MonthChecklist | undefined;
  current: string | null;
  pathFor: (panel: string) => string;
  closed?: boolean;
}) {
  const steps = stepsById(checklist);
  return (
    <nav aria-label="Разделы месяца" className={styles.strip}>
      {STEP_ORDER.map((id) => {
        const step = steps.get(id);
        return (
          <Link
            aria-current={current === id ? "page" : undefined}
            className={styles.stripItem}
            data-state={presentationState(step?.state, closed) ?? "unknown"}
            key={id}
            to={pathFor(id)}
          >
            {id === "close" ? null : <StateMark state={step?.state} closed={closed} />}
            {id === "close" && closed ? "Итоги" : MONTH_STEP_COPY[id].label}
            {!closed && step && id !== "close" ? (
              <span className={styles.visuallyHidden}>, {stateText(step.state, closed)}</span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

function Kpi({
  label,
  value,
  note,
  tone,
  extra,
  title,
}: {
  title?: string;
  label: string;
  value: string;
  note?: ReactNode;
  tone?: "positive" | "negative" | "neutral";
  /** A backend coverage marker shown once, under the value it qualifies. */
  extra?: ReactNode;
}) {
  return (
    <div className={styles.kpi}>
      <dt>{label}</dt>
      <dd className={styles.kpiValue} title={title}>
        {value}
      </dd>
      {note ? (
        <dd className={styles.kpiNote} data-tone={tone ?? "neutral"}>
          {note}
        </dd>
      ) : null}
      {extra ? <dd className={styles.kpiNote}>{extra}</dd> : null}
    </div>
  );
}

function deltaNote(value: MoneyValue | null | undefined, suffix: string, whole = false) {
  if (!value) return { note: undefined, tone: undefined };
  return {
    note: `${(whole ? moneyWholeDeltaText : moneyDeltaText)(value)} ${suffix}`,
    tone: moneyTone(value),
  };
}

export function MonthKpis({
  workflow,
  variant = "overview",
}: {
  workflow: MonthCloseWorkflow;
  variant?: "overview" | "close";
}) {
  const review = workflow.final_review;
  if (!review.available) return null;
  const { kpis } = review;
  const display = variant === "overview" ? moneyWholeText : moneyText;
  // Without capital snapshots the backend sum is 0.00 by construction, not a measured zero.
  const coverage = kpis.portfolio_source_coverage;
  const capitalUnknown = coverage?.status === "unavailable";
  const capital =
    capitalUnknown || kpis.liquid_capital_delta_coverage?.status === "unavailable"
      ? deltaNote(null, "")
      : deltaNote(kpis.liquid_capital_delta, "за месяц", variant === "overview");
  const passive = deltaNote(kpis.passive_income_delta, "к прошлому месяцу", variant === "overview");
  const budget = workflow.checklist?.steps.find((step) => step.id === "budget");
  const noExpenseRows = workflow.checklist?.expenses.mandatory_items.length === 0;
  const articles =
    budget?.secondary_count != null
      ? countText(budget.secondary_count, ["статья", "статьи", "статей"])
      : undefined;
  return (
    <dl aria-label={variant === "close" ? "Итоги месяца" : "Итог месяца"} className={styles.kpis}>
      <Kpi
        label="Ликвидный капитал"
        title={capitalUnknown ? undefined : moneyText(kpis.liquid_capital_net)}
        value={capitalUnknown ? "—" : display(kpis.liquid_capital_net)}
        {...capital}
        extra={
          coverage &&
          (coverage.status !== "complete" ||
            coverage.source_account_financial_coverage?.status === "partial") ? (
            <PortfolioCoverageNote
              coverage={coverage}
              month={{ year: workflow.month.year, month: workflow.month.month }}
            />
          ) : undefined
        }
      />
      <Kpi
        label="Пассивный доход"
        title={moneyText(kpis.passive_income_actual)}
        value={display(kpis.passive_income_actual)}
        {...passive}
      />
      {variant === "close" ? (
        <Kpi label="Инвестиции" value={moneyText(review.investments.market_value)} />
      ) : null}
      {variant === "overview" || (kpis.mandatory_expenses != null && !noExpenseRows) ? (
        <Kpi
          label="Обязательные расходы"
          title={noExpenseRows ? undefined : moneyText(kpis.mandatory_expenses)}
          // No mandatory rows at all is "not entered", not a measured zero.
          value={noExpenseRows ? "—" : display(kpis.mandatory_expenses)}
          note={noExpenseRows ? "не заполнено" : articles}
        />
      ) : null}
      {variant === "overview" ? (
        <Kpi
          label="Покрытие расходов"
          value={formatPercent(kpis.mandatory_expense_coverage_pct)}
          note="пассивным доходом, по прогнозу"
        />
      ) : null}
    </dl>
  );
}

function ExpenseBars({ checklist }: { checklist: MonthChecklist }) {
  const { mandatory_items: items, mandatory_total: total, other_total: other } = checklist.expenses;
  if (items.length === 0) return null;
  // Bar length only: the amounts themselves stay backend strings.
  const max = Math.max(...items.map((item) => Math.abs(Number(item.amount.amount)) || 0), 0);
  const hasOther = moneyTone(other) !== "neutral";
  return (
    <section aria-labelledby="month-expenses-title" className={styles.expenses}>
      <p className={styles.eyebrow}>Расходы</p>
      <h2 id="month-expenses-title">Обязательные расходы</h2>
      <ul className={styles.bars}>
        {items.map((item) => {
          const share = max > 0 ? Math.abs(Number(item.amount.amount)) / max : 0;
          return (
            <li key={item.category}>
              <span className={styles.barLabel}>{item.category}</span>
              <span aria-hidden="true" className={styles.barTrack}>
                <span
                  className={styles.barFill}
                  style={{ width: `${Math.max(share * 100, share > 0 ? 2 : 0)}%` }}
                />
              </span>
              <span className={styles.barValue}>{moneyText(item.amount)}</span>
            </li>
          );
        })}
        <li className={styles.barTotal}>
          <span className={styles.barLabel}>Итого</span>
          <span aria-hidden="true" />
          <span className={styles.barValue}>{moneyText(total)}</span>
        </li>
      </ul>
      {hasOther ? (
        <p className={styles.otherExpenses}>
          Прочие расходы {moneyText(other)} в покрытие не входят.
        </p>
      ) : null}
    </section>
  );
}

function CloseBanner({
  workflow,
  pathFor,
}: {
  workflow: MonthCloseWorkflow;
  pathFor: (panel: string) => string;
}) {
  const checklist = workflow.checklist;
  const closed = workflow.month.status === "closed";
  if (closed) {
    const count = workflow.final_review.available
      ? closeOwnerActionFindings(workflow.final_review.close_readiness.items).filter(
          (item) => item.severity === "hard_blocker" || item.severity === "warning",
        ).length
      : workflow.readiness.hard_blocker_count + workflow.readiness.warning_count;
    return (
      <div className={styles.banner} data-state="closed">
        <StateMark state="done" />
        <div>
          <strong>Месяц закрыт</strong>
          {count ? <p>Закрыт с замечаниями: {count}</p> : null}
        </div>
        <Link className={styles.secondaryAction} to={pathFor("close")}>
          Итоги и замечания
        </Link>
      </div>
    );
  }
  const readiness = workflow.readiness;
  const done = checklist?.completed_count;
  const total = checklist?.total_count;
  const reason = !readiness.can_close
    ? `Закрытие заблокировано: ${countText(readiness.hard_blocker_count, ["замечание", "замечания", "замечаний"])}`
    : checklist?.attention_count
      ? `Требуют решения: ${countText(checklist.attention_count, ["замечание", "замечания", "замечаний"])}. Закрыть можно, замечания сохранятся.`
      : "Закрытие не подтверждает полноту данных.";
  return (
    <div className={styles.banner} data-state="open">
      <div className={styles.bannerBody}>
        {done != null && total ? (
          <>
            <strong>
              Готово {done} из {total}
            </strong>
            <span
              aria-hidden="true"
              className={styles.progress}
              style={{ ["--progress" as string]: `${(done / total) * 100}%` }}
            />
          </>
        ) : (
          <strong>Итоговая проверка</strong>
        )}
        <p>{reason}</p>
      </div>
      <Link
        className={styles.primaryAction}
        data-blocked={readiness.can_close ? undefined : "true"}
        to={pathFor("close")}
      >
        Закрыть месяц
      </Link>
    </div>
  );
}

/** Month as a report: the month result first, then the sections checklist. */
export function MonthOverview({
  workflow,
  pathFor,
}: {
  workflow: MonthCloseWorkflow;
  pathFor: (panel: string) => string;
}) {
  const checklist = workflow.checklist;
  const steps = stepsById(checklist);
  const closed = workflow.month.status === "closed";
  const hasExpenses = Boolean(checklist?.expenses.mandatory_items.length);
  const allDone =
    checklist != null &&
    checklist.completed_count === checklist.total_count &&
    checklist.attention_count === 0;
  const title = closed
    ? allDone
      ? "Все шаги выполнены"
      : "Разделы месяца"
    : checklist?.attention_count
      ? "Что требует решения"
      : "Что осталось сделать";
  return (
    <div className={styles.overview} data-testid="v2-close-workspace">
      <MonthKpis workflow={workflow} />
      <div className={styles.columns} data-side={hasExpenses ? "true" : undefined}>
        <nav aria-label="Разделы месяца" className={styles.checklist}>
          {!closed ? (
            <div className={styles.checklistHead}>
              <p className={styles.eyebrow}>Закрытие месяца</p>
              {checklist ? (
                <span className={styles.counter}>
                  {checklist.completed_count} из {checklist.total_count}
                </span>
              ) : null}
              <h2 id="month-checklist-title">{title}</h2>
            </div>
          ) : null}
          {GROUPS.map((group) => (
            <section aria-label={group.title} className={styles.group} key={group.id}>
              <h3 className={styles.eyebrow}>{group.title}</h3>
              <ul>
                {STEP_ORDER.filter((id) =>
                  steps.size ? steps.get(id)?.group === group.id : DEFAULT_GROUP[id] === group.id,
                ).map((id) => {
                  const step = steps.get(id);
                  return (
                    <li key={id}>
                      <Link
                        className={styles.row}
                        data-state={presentationState(step?.state, closed) ?? "unknown"}
                        to={pathFor(id)}
                      >
                        <StateMark state={step?.state} closed={closed} />
                        <span className={styles.rowText}>
                          <span className={styles.rowTitle}>
                            {id === "close" && closed ? "Итоги" : MONTH_STEP_COPY[id].label}
                          </span>
                          <span className={styles.rowHint}>{hintText(step, id, closed)}</span>
                        </span>
                        {step ? (
                          <span
                            className={styles.rowFigure}
                            title={
                              step.figure?.kind === "money"
                                ? moneyText(step.figure.amount)
                                : undefined
                            }
                          >
                            {step.figure?.kind === "money"
                              ? moneyWholeText(step.figure.amount, "—")
                              : figureText(step)}
                          </span>
                        ) : null}
                        {!closed && step ? (
                          <span className={styles.visuallyHidden}>
                            , {stateText(step.state, closed)}
                          </span>
                        ) : null}
                        <span aria-hidden="true" className={styles.chevron}>
                          ›
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
          <CloseBanner pathFor={pathFor} workflow={workflow} />
        </nav>
        {checklist && hasExpenses ? (
          <aside className={styles.side}>
            <ExpenseBars checklist={checklist} />
          </aside>
        ) : null}
      </div>
    </div>
  );
}

const DEFAULT_GROUP: Record<MonthChecklistStepId, MonthChecklistStep["group"]> = {
  general: "data",
  income: "data",
  assets: "data",
  liabilities: "data",
  budget: "data",
  brokers: "sources",
  positions: "sources",
  payouts: "sources",
  note: "plan",
  close: "close",
};
