import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import { useMonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { GuidedCloseStep, MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { listMonths } from "../api/months";
import type { MoneyValue } from "../api/types";
import { monthlyCloseReturnPath } from "../components/month-close/navigation";
import { RuntimeStatusBanner } from "../components/RuntimeStatus";
import { formatDate, formatDateTime, formatMoney, formatMoneyDelta, formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import { monthWorkspacePath, resolveMonthSelection, sortReportingMonths } from "./monthSelection";
import styles from "./UiV2Page.module.css";

const STEP_LABELS: Record<GuidedCloseStep["state"], string> = {
  not_started: "Не начат",
  ready: "Можно выполнить",
  completed: "Подтверждён",
  skipped: "Пропущен",
  warning: "Нужно внимание",
  blocked: "Есть препятствие",
};

function money(value: MoneyValue | null | undefined): string {
  return formatMoney(value?.amount, {
    currency: value?.currency === "RUB" ? "₽" : value?.currency,
    empty: "Нет данных",
  });
}

function Notice({
  title,
  children,
  retry,
}: {
  title: string;
  children: ReactNode;
  retry?: () => void;
}) {
  return (
    <section className={styles.notice} role={retry ? "alert" : undefined}>
      <h2>{title}</h2>
      <p>{children}</p>
      {retry ? (
        <button className={styles.secondaryButton} onClick={retry} type="button">
          Повторить загрузку
        </button>
      ) : null}
    </section>
  );
}

function Results({ workflow }: { workflow: MonthCloseWorkflow }) {
  const review = workflow.final_review;
  if (!review.available) {
    return (
      <Notice title="Итоги пока недоступны">
        Нет данных для сводки. Это не нулевой капитал или доход. Порядок действий ниже остаётся
        доступным.
      </Notice>
    );
  }
  const kpis = review.kpis;
  return (
    <section aria-label="Результат месяца" className={styles.metrics}>
      <article className={`${styles.metric} ${styles.capital}`}>
        <p className={styles.eyebrow}>Ликвидный капитал · после долгов</p>
        <p className={styles.metricValue} data-testid="v2-capital">
          {money(kpis.liquid_capital_net)}
        </p>
        <p className={styles.metricDetail}>
          {kpis.liquid_capital_delta ? (
            <>
              <strong>
                {formatMoneyDelta(kpis.liquid_capital_delta.amount, {
                  currency: kpis.liquid_capital_delta.currency === "RUB" ? "₽" : kpis.liquid_capital_delta.currency,
                })}
              </strong>{" "}
              к предыдущему месяцу
            </>
          ) : (
            "Нет предыдущего месяца для сравнения"
          )}
        </p>
        <p className={styles.caption}>Изменение капитала — не инвестиционная доходность.</p>
      </article>
      <article className={styles.metric}>
        <p className={styles.eyebrow}>Пассивный доход · факт</p>
        <p className={styles.metricValue} data-testid="v2-passive-actual">
          {money(kpis.passive_income_actual)}
        </p>
        <p className={styles.metricDetail}>Получено за отчётный месяц.</p>
        <p className={styles.caption}>Без пополнений, зарплаты и возврата номинала.</p>
      </article>
      <article className={`${styles.metric} ${styles.forecast}`}>
        <p className={styles.eyebrow}>Пассивный доход · прогноз</p>
        <p className={styles.metricValue} data-testid="v2-passive-forecast">
          {money(kpis.forecast_monthly_passive_income)}
        </p>
        <p className={styles.metricDetail}>Среднемесячная оценка на 12 месяцев.</p>
        <p className={styles.caption}>Не обещание выплаты в следующем месяце.</p>
      </article>
    </section>
  );
}

function Readiness({ workflow }: { workflow: MonthCloseWorkflow }) {
  const { readiness, final_review: review } = workflow;
  const items = review.available
    ? review.close_readiness.items.filter((item) => item.severity !== "info")
    : [];
  return (
    <section className={styles.readiness} aria-labelledby="v2-readiness-title">
      <p className={styles.eyebrow}>Проверки данных</p>
      <h2 id="v2-readiness-title">
        {workflow.month.status === "closed"
          ? "Месяц зафиксирован"
          : readiness.can_close
            ? "Можно перейти к итоговой проверке"
            : "Сначала проверь данные"}
      </h2>
      <dl className={styles.counts}>
        <div>
          <dt>Обязательных исправлений</dt>
          <dd data-testid="v2-blockers">{readiness.hard_blocker_count}</dd>
        </div>
        <div>
          <dt>Предупреждений</dt>
          <dd data-testid="v2-warnings">{readiness.warning_count}</dd>
        </div>
      </dl>
      <p className={styles.caption}>
        {workflow.month.status === "closed"
          ? "Просмотр не открывает месяц заново и не меняет сохранённые данные."
          : "Предупреждения не равны запрету закрытия. Финальное решение — после проверки итогов."}
      </p>
      {items.length > 0 ? (
        <details className={styles.details}>
          <summary>Что требует внимания</summary>
          <ul className={styles.attentionList}>
            {items.map((item, index) => (
              <li key={`${item.code}-${index}`}>
                <strong>{item.severity === "hard_blocker" ? "Исправить: " : "Проверить: "}</strong>
                {item.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <Link
        className={styles.textLink}
        to={monthlyCloseReturnPath({ monthId: workflow.month.id, step: "final_review_close" })}
      >
        Все итоги и проверки в текущем интерфейсе →
      </Link>
    </section>
  );
}

export default function UiV2Page() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const monthsQuery = useQuery({ queryKey: queryKeys.months, queryFn: ({ signal }) => listMonths(signal) });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const selection = resolveMonthSelection(params.getAll("month"), months);
  const selectedMonth = selection.kind === "selected" ? selection.month : null;
  const selectedId = selectedMonth?.id ?? null;
  const workflowQuery = useMonthCloseWorkflow(monthsQuery.isError ? null : selectedId);

  // Pin the automatic entry choice once. Explicit invalid/deleted periods never fall back.
  useEffect(() => {
    if (monthsQuery.isSuccess && !params.has("month") && months[0]) {
      navigate(monthWorkspacePath(months[0].id), { replace: true });
    }
  }, [months, monthsQuery.isSuccess, navigate, params]);

  // Do not relabel another period's data, or expose stale cached results during revalidation.
  const loading = monthsQuery.isPending || workflowQuery.isFetching;
  const response = workflowQuery.data;
  const mismatch = response != null && (
    response.contract_version !== "monthly_close_workflow_v1" || response.month.id !== selectedId
  );
  const workflow = !loading && !monthsQuery.isError && !workflowQuery.isError && !mismatch
    ? response
    : undefined;
  const requestedStep = params.get("step");
  const explicitStep = workflow?.steps.find((step) => step.id === requestedStep);
  const activeStep = explicitStep ?? workflow?.steps.find((step) => step.id === workflow.recommended_step_id);
  const actionRef = useRef<HTMLElement>(null);
  const focusedLocation = useRef<string | null>(null);
  const explicitStepId = explicitStep?.id;

  useEffect(() => {
    if (!explicitStepId || focusedLocation.current === location.key) return;
    const panel = actionRef.current;
    if (!panel) return;
    focusedLocation.current = location.key;
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ block: "nearest" });
  }, [explicitStepId, location.key]);

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <Notice title="Не удалось загрузить месяцы" retry={() => void monthsQuery.refetch()}>
        Проверь, запущено ли локальное приложение. Сохранённые данные не изменены.
      </Notice>
    );
  } else if (monthsQuery.isPending) {
    content = <p className={styles.loading} role="status">Загружаем отчётные месяцы…</p>;
  } else if (selection.kind === "invalid" || selection.kind === "missing") {
    content = (
      <Notice title="Месяц по ссылке не найден">
        Выбери отчётный месяц в списке. Другой период не подставлен автоматически.
      </Notice>
    );
  } else if (months.length === 0) {
    content = (
      <Notice title="Начни с первого месяца">
        Создай отчётный период в текущем интерфейсе. После этого здесь появятся его итоги и порядок
        действий. <Link to="/months">Создать первый месяц →</Link>
      </Notice>
    );
  } else if (workflowQuery.isError || mismatch) {
    content = (
      <Notice title="Не удалось получить состояние месяца" retry={() => void workflowQuery.refetch()}>
        Показатели и действия скрыты, чтобы не выдать устаревшие или чужие этому периоду данные за
        актуальные. Повтори загрузку.
      </Notice>
    );
  } else if (!workflow || loading) {
    content = <p className={styles.loading} role="status">Обновляем состояние выбранного месяца…</p>;
  } else {
    content = (
      <>
        <div className={styles.contextLine}>
          <span className={styles.status} data-closed={workflow.month.status === "closed"}>
            {workflow.month.status === "closed" ? "Закрыт" : "Черновик"}
          </span>
          <span>Дата снимка: <strong>{formatDate(workflow.month.snapshot_date, { empty: "не задана" })}</strong></span>
          <Link className={styles.textLink} to={`/months/${workflow.month.id}`}>
            Открыть этот месяц в текущем интерфейсе →
          </Link>
        </div>
        <Results workflow={workflow} />
        <div className={styles.actionGrid}>
          <section className={styles.action} id="v2-action" ref={actionRef} tabIndex={-1}>
            <p className={styles.eyebrow}>{explicitStep ? "Выбранный шаг" : "Следующее действие"}</p>
            {requestedStep && !explicitStep ? (
              <p className={styles.caption}>Шаг по ссылке не найден. Ниже — рекомендация для этого месяца.</p>
            ) : null}
            <h2>{activeStep?.title ?? "Открой итоговую проверку"}</h2>
            <p className={styles.actionWhy}>
              {activeStep?.why ?? "Автоматической рекомендации нет. Посмотри сохранённые итоги месяца."}
            </p>
            {activeStep?.stale.is_stale ? (
              <p className={styles.stale}>Подтверждение этого шага устарело. Оно требует повторной проверки.</p>
            ) : null}
            <div className={styles.actionFooter}>
              <Link
                className={styles.primaryButton}
                data-testid="v2-primary-action"
                to={monthlyCloseReturnPath({
                  monthId: workflow.month.id,
                  step: activeStep?.id ?? "final_review_close",
                })}
              >
                Открыть шаг →
              </Link>
              <span className={styles.handoff}>
                В текущем интерфейсе. Ничего не запускается автоматически.
              </span>
            </div>
            {activeStep?.primary_action ? (
              <p className={styles.caption}>На следующем экране: {activeStep.primary_action.label}.</p>
            ) : null}
          </section>
          <Readiness workflow={workflow} />
        </div>
        <section className={styles.workflow} aria-labelledby="v2-workflow-title">
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>Порядок действий</p>
              <h2 id="v2-workflow-title">От данных к закрытому месяцу</h2>
            </div>
            <p className={styles.progress} data-testid="v2-progress">
              <strong>{workflow.progress.completed_or_skipped} из {workflow.progress.total_applicable}</strong>
              <span>применимых шагов подтверждено или пропущено</span>
            </p>
          </div>
          <ol className={styles.steps}>
            {workflow.steps.map((step) => (
              <li key={step.id}>
                <button
                  aria-label={step.title}
                  aria-pressed={activeStep?.id === step.id}
                  className={styles.step}
                  data-state={step.state}
                  data-testid={`v2-step-${step.id}`}
                  onClick={() => navigate(monthWorkspacePath(workflow.month.id, step.id))}
                  type="button"
                >
                  <span className={styles.stepNumber} aria-hidden="true">{step.order}</span>
                  <span className={styles.stepTitle}>{step.title}</span>
                  <span className={styles.stepState}>
                    {step.applicability === "not_applicable" ? "Не применяется" : STEP_LABELS[step.state] ?? "Проверить"}
                  </span>
                  <span aria-hidden="true">↗</span>
                </button>
              </li>
            ))}
          </ol>
          <p className={styles.caption}>
            Это прогресс подтверждений, а не оценка финансового здоровья. Готовность к закрытию
            проверяется отдельно.
          </p>
        </section>
        <details className={`${styles.details} ${styles.provenance}`}>
          <summary>О данных и границах этой версии</summary>
          <p>Сводка рассчитана: {formatDateTime(workflow.generated_at)}. Это время расчёта, не обновления котировок.</p>
          <p>
            UI v2 читает сохранённые локальные данные. Импорт, редактирование, подтверждение закрытия и
            повторное открытие пока выполняются в текущем интерфейсе. Дата снимка и отчётный месяц
            имеют разный смысл. Прогноз и изменение капитала не заменяют XIRR или TWRR.
          </p>
        </details>
      </>
    );
  }

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#v2-main">К содержанию</a>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} to="/v2">
          <span className={styles.brandMark} aria-hidden="true">H</span>
          <span>Hermes Finance<small>Личные финансы</small></span>
        </Link>
        <nav aria-label="Навигация UI v2" className={styles.navigation}>
          <Link aria-current="page" to={selectedId ? monthWorkspacePath(selectedId) : "/v2"}>
            <span aria-hidden="true">◷</span> Мой месяц
          </Link>
        </nav>
        <div className={styles.sidebarNote}>
          <span className={styles.eyebrow}>Твой месячный ритм</span>
          <p>Обновить данные.<br />Понять результат.<br />Зафиксировать месяц.</p>
        </div>
        <div className={styles.legacyLinks}>
          <p className={styles.eyebrow}>В текущем интерфейсе</p>
          <Link to="/months">Все месяцы <span aria-hidden="true">↗</span></Link>
          <Link to="/accounts">Счета и инструменты <span aria-hidden="true">↗</span></Link>
          <Link to="/analytics">История и доходность <span aria-hidden="true">↗</span></Link>
          <Link to="/goals">Цели <span aria-hidden="true">↗</span></Link>
          <Link to="/export">Экспорт и копии <span aria-hidden="true">↗</span></Link>
          <p className={styles.caption}>В этих разделах месяц выбирается по правилам текущего интерфейса.</p>
        </div>
        <p className={styles.localOnly}>Только на этом компьютере</p>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.topbar}>
          <span>UI v2 <span className={styles.previewBadge}>Предварительная версия</span></span>
          <Link to="/">Вернуться к текущему интерфейсу →</Link>
        </div>
        <RuntimeStatusBanner />
        <main aria-busy={loading} className={styles.main} id="v2-main" tabIndex={-1}>
          <header className={styles.header}>
            <div>
              <p className={styles.eyebrow}>Ежемесячный обзор</p>
              <h1>Мой месяц</h1>
              <p className={styles.subtitle}>Результат, внимание и следующий шаг — вместе.</p>
            </div>
            <label className={styles.monthPicker}>
              <span>Отчётный месяц</span>
              <select
                aria-label="Отчётный месяц"
                disabled={monthsQuery.isPending || monthsQuery.isError || months.length === 0}
                onChange={(event) => navigate(monthWorkspacePath(Number(event.target.value)))}
                value={selectedId ?? ""}
              >
                <option disabled value="">Выбери месяц</option>
                {months.map((month) => (
                  <option key={month.id} value={month.id}>
                    {formatMonth(month.year, month.month)}
                  </option>
                ))}
              </select>
            </label>
          </header>
          {content}
        </main>
      </div>
    </div>
  );
}
