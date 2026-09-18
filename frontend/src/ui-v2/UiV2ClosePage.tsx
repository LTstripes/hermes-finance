import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import type { GuidedCloseActionId, GuidedCloseStep } from "../api/monthCloseWorkflow";
import { listMonths } from "../api/months";
import { FinalMonthReview } from "../components/month-close/FinalMonthReview";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import { isGuidedCloseStepId, routeForGuidedAction } from "../components/month-close/navigation";
import { MonthlyCloseStepSummary } from "../components/month-close/ProviderStepSummary";
import {
  parseAlfaStatementTransientOutcome,
  type AlfaStatementTransientOutcome,
} from "../components/month-close/statementOutcome";
import { useMonthCloseLifecycle } from "../components/month-close/useMonthCloseLifecycle";
import { Button, ConfirmDialog } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import {
  monthWorkspacePath,
  resolveMonthSelection,
  selectNewestDraftAfterLatestClosed,
  sortReportingMonths,
} from "./monthSelection";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import styles from "./UiV2Page.module.css";

const STATE_LABELS: Record<GuidedCloseStep["state"], string> = {
  not_started: "Ещё не начато",
  ready: "Следующее действие",
  completed: "Готово",
  skipped: "Не применяется",
  warning: "Нужно внимание",
  blocked: "Требуется исправить",
};

const CURRENT_STEP_ID = "v2-close-current-step";

function actionPath(actionId: GuidedCloseActionId, monthId: number, stepId: GuidedCloseStep["id"]) {
  if (actionId === "open_final_review") return monthWorkspacePath(monthId, "final_review_close");
  return routeForGuidedAction(actionId, monthId, stepId, "monthly-close-v2");
}

function StepList({
  monthId,
  steps,
  viewedStepId,
}: {
  monthId: number;
  steps: GuidedCloseStep[];
  viewedStepId: GuidedCloseStep["id"] | null;
}) {
  return (
    <ol className={styles.closeStepList} aria-label="Шаги закрытия">
      {steps.map((step) => (
        <li
          className={styles.closeStep}
          data-active={step.id === viewedStepId ? "true" : undefined}
          id={`v2-close-step-${step.id}`}
          key={step.id}
        >
          <span className={styles.closeStepOrder}>{step.order}</span>
          <div className={styles.closeStepCopy}>
            <Link
              aria-current={step.id === viewedStepId ? "step" : undefined}
              to={monthWorkspacePath(monthId, step.id)}
            >
              {step.title}
            </Link>
            <p>{step.why}</p>
            <MonthlyCloseStepSummary compact step={step} />
          </div>
          <span className={styles.closeStepState} data-state={step.state}>
            {STATE_LABELS[step.state]}
          </span>
        </li>
      ))}
    </ol>
  );
}

export default function UiV2ClosePage() {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const { newestDraft } = selectNewestDraftAfterLatestClosed(months);
  const selection = resolveMonthSelection(params.getAll("month"), months);
  const selectedMonth =
    selection.kind === "selected"
      ? selection.month
      : selection.kind === "automatic"
        ? newestDraft
        : null;
  const monthId = selectedMonth?.id ?? null;
  const {
    cancelLifecycle,
    confirmLifecycle,
    lifecycleBusy,
    lifecycleError,
    pendingLifecycle,
    prepareClose,
    preparingClose,
    requestReopen,
    workflowQuery,
  } = useMonthCloseLifecycle(monthId);
  const [statementOutcome] = useState<AlfaStatementTransientOutcome | null>(() =>
    parseAlfaStatementTransientOutcome(
      (location.state as { alfaStatementOutcome?: unknown } | null)?.alfaStatementOutcome,
    ),
  );
  const focusedStepRef = useRef<string | null>(null);
  const workflow = workflowQuery.data;
  const workflowIdentityMatches =
    workflow?.contract_version === "monthly_close_workflow_v1" && workflow.month.id === monthId;
  const stepValues = params.getAll("step");
  const requestedStep =
    stepValues.length === 1 && isGuidedCloseStepId(stepValues[0]) ? stepValues[0] : null;
  const viewedStep = workflowIdentityMatches
    ? (workflow.steps.find((step) => step.id === requestedStep) ??
      workflow.steps.find((step) => step.id === workflow.recommended_step_id) ??
      null)
    : null;
  const recommendedStep = workflowIdentityMatches
    ? (workflow.steps.find((step) => step.id === workflow.recommended_step_id) ?? null)
    : null;

  useEffect(() => {
    if (!statementOutcome) return;
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.pathname, location.search, navigate, statementOutcome]);

  useEffect(() => {
    if (!workflowIdentityMatches || !viewedStep || monthId === null) return;
    const canonical = monthWorkspacePath(monthId, viewedStep.id);
    if (`${location.pathname}${location.search}` !== canonical) {
      navigate(canonical, { replace: true });
    }
  }, [location.pathname, location.search, monthId, navigate, viewedStep, workflowIdentityMatches]);

  useEffect(() => {
    if (!viewedStep || focusedStepRef.current === viewedStep.id) return;
    const frame = window.requestAnimationFrame(() => {
      const element = document.getElementById(CURRENT_STEP_ID);
      if (!element) return;
      focusedStepRef.current = viewedStep.id;
      element.scrollIntoView?.({ block: "start" });
      element.focus?.({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [viewedStep]);

  const v1ReturnPath =
    monthId === null
      ? "/monthly-close"
      : `/months/${monthId}/close${viewedStep ? `#${viewedStep.id}` : ""}`;
  const monthsReady = isQueryReady(monthsQuery);
  const workflowReady = isQueryReady(workflowQuery);
  const closed = workflowIdentityMatches && workflow.month.status === "closed";
  const finalReviewActive = viewedStep?.id === "final_review_close";
  const closeAction =
    !closed && finalReviewActive && viewedStep.primary_action?.id === "confirm_close";

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice
        title="Не удалось загрузить отчётные месяцы"
        retry={() => void monthsQuery.refetch()}
      >
        Закрытие скрыто, пока список месяцев не подтверждён сервером.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем отчётные месяцы…" />;
  } else if (selection.kind === "invalid") {
    content = (
      <UiV2Notice title="Некорректный месяц">
        Адрес должен содержать один положительный идентификатор месяца. Выбери месяц заново в{" "}
        <Link to="/monthly-close">текущем интерфейсе →</Link>
      </UiV2Notice>
    );
  } else if (selection.kind === "missing") {
    content = (
      <UiV2Notice title="Месяц не найден">
        Такой отчётный месяц не подтверждён. <Link to="/v2">Вернуться в «Мои финансы» →</Link>
      </UiV2Notice>
    );
  } else if (!selectedMonth) {
    content = (
      <UiV2Notice title="Нет незакрытого месяца">
        Сейчас нет черновика для продолжения. <Link to="/v2">Открыть «Мои финансы» →</Link> или{" "}
        <Link to="/months">посмотреть историю отчётов ↗</Link>
      </UiV2Notice>
    );
  } else if (workflowQuery.isError) {
    const missing =
      workflowQuery.error instanceof ApiClientError && workflowQuery.error.status === 404;
    content = (
      <UiV2Notice
        title={missing ? "Месяц не найден" : "Не удалось открыть закрытие"}
        retry={() => void workflowQuery.refetch()}
      >
        {missing
          ? "Сервер больше не подтверждает этот месяц. Другой месяц автоматически не выбран."
          : formatApiError(workflowQuery.error)}
      </UiV2Notice>
    );
  } else if (!workflowReady) {
    content = <UiV2Loading label="Определяем актуальный шаг закрытия…" />;
  } else if (!workflowIdentityMatches || !viewedStep) {
    content = (
      <UiV2Notice
        title="Состояние месяца не подтверждено"
        retry={() => void workflowQuery.refetch()}
      >
        Финансовые значения скрыты: ответ workflow не совпал с выбранным месяцем или шаги
        отсутствуют.
      </UiV2Notice>
    );
  } else {
    const primaryAction = closed ? null : viewedStep.primary_action;
    const primaryPath =
      primaryAction && primaryAction.id !== "confirm_close"
        ? actionPath(primaryAction.id, workflow.month.id, viewedStep.id)
        : null;
    content = (
      <div className={styles.closeWorkspace} data-testid="v2-close-workspace">
        <div className={styles.closeContext}>
          <span className={closed ? styles.closedBadge : styles.draftBadge}>
            {closed ? "Месяц закрыт" : "Черновик"}
          </span>
          <span>
            Снимок{" "}
            {workflow.month.snapshot_date ? formatDate(workflow.month.snapshot_date) : "не указан"}
          </span>
          {closed ? (
            <strong>Месяц зафиксирован</strong>
          ) : (
            <span>
              {workflow.progress.completed_or_skipped} из {workflow.progress.total_applicable} шагов
              подтверждены сохранёнными фактами
            </span>
          )}
        </div>

        {statementOutcome ? (
          <section className={styles.closeOutcome} role="status">
            <strong>Результат проверки PDF Alfa</strong>
            <p>
              {statementOutcome.kind === "applied"
                ? `Применено выбранных строк: ${statementOutcome.selectedCount}. Workflow перечитан по сохранённым данным.`
                : "Подходящих выплат не найдено. Предпросмотр не сохранён и не засчитан как прогресс."}
            </p>
          </section>
        ) : null}

        <section className={styles.closeCurrent} id={CURRENT_STEP_ID} tabIndex={-1}>
          <p className={styles.eyebrow}>{closed ? "Зафиксированный месяц" : "Сейчас"}</p>
          <div className={styles.closeCurrentHeading}>
            <h2>{closed ? "Месяц зафиксирован" : viewedStep.title}</h2>
            {!closed ? (
              <span className={styles.closeStepState} data-state={viewedStep.state}>
                {STATE_LABELS[viewedStep.state]}
              </span>
            ) : null}
          </div>
          <p>
            {closed
              ? "Сохранённые факты защищены от случайного изменения. Чтобы внести правку, сначала открой месяц заново."
              : viewedStep.why}
          </p>
          {!closed ? <MonthlyCloseStepSummary step={viewedStep} /> : null}
          {recommendedStep && recommendedStep.id !== viewedStep.id && !closed ? (
            <p className={styles.closeRecommendation}>
              Следующее действие:{" "}
              <Link to={monthWorkspacePath(workflow.month.id, recommendedStep.id)}>
                {recommendedStep.title}
              </Link>
            </p>
          ) : null}
          {lifecycleError ? (
            <p className={styles.closeError} role="alert">
              {lifecycleError}
            </p>
          ) : null}
          {primaryAction && primaryPath && !finalReviewActive ? (
            <div className={styles.closePrimaryRow}>
              <Link className={styles.primaryButton} to={primaryPath}>
                {primaryAction.label}
              </Link>
            </div>
          ) : null}
          {!closed && viewedStep.secondary_actions.length > 0 ? (
            <div className={styles.closeSecondaryRow}>
              {viewedStep.secondary_actions.map((action) => (
                <Link
                  className={styles.secondaryButton}
                  key={action.id}
                  to={actionPath(action.id, workflow.month.id, viewedStep.id)}
                >
                  {action.label}
                </Link>
              ))}
            </div>
          ) : null}
        </section>

        <section className={styles.closeAttention} aria-label="Готовность к закрытию">
          <div>
            <p className={styles.eyebrow}>Требует внимания</p>
            <strong>
              Блокеров: {workflow.readiness.hard_blocker_count} · Предупреждений:{" "}
              {workflow.readiness.warning_count}
            </strong>
          </div>
          {!closed && recommendedStep ? (
            <Link
              className={styles.secondaryButton}
              to={monthWorkspacePath(workflow.month.id, recommendedStep.id)}
            >
              Открыть следующее действие
            </Link>
          ) : null}
        </section>

        <section className={styles.closeStepsDesktop} aria-labelledby="v2-close-steps-title">
          <h2 id="v2-close-steps-title">Шаги закрытия</h2>
          <StepList
            monthId={workflow.month.id}
            steps={workflow.steps}
            viewedStepId={viewedStep.id}
          />
        </section>
        <details className={styles.closeStepsNarrow}>
          <summary>Шаги закрытия · {workflow.steps.length}</summary>
          <StepList
            monthId={workflow.month.id}
            steps={workflow.steps}
            viewedStepId={viewedStep.id}
          />
        </details>

        {finalReviewActive || closed ? (
          <FinalMonthReview origin="monthly-close-v2" review={workflow.final_review} />
        ) : (
          <section className={styles.closeCompactReview}>
            <div>
              <p className={styles.eyebrow}>Итоги месяца</p>
              <h2>Финальная проверка</h2>
              <p>
                Полная сводка откроется на финальном шаге. Значения не пересчитываются в браузере.
              </p>
            </div>
            <Link
              className={styles.secondaryButton}
              to={monthWorkspacePath(workflow.month.id, "final_review_close")}
            >
              Открыть итоговую проверку
            </Link>
          </section>
        )}

        {closeAction ? (
          <section className={styles.closeLifecyclePanel} aria-label="Закрыть месяц">
            <div>
              <h2>Зафиксировать {formatMonth(workflow.month.year, workflow.month.month)}</h2>
              <p>
                Блокеров: {workflow.readiness.hard_blocker_count} · Предупреждений:{" "}
                {workflow.readiness.warning_count}. После закрытия данные доступны только для чтения
                до явного открытия.
              </p>
            </div>
            <Button
              disabled={!workflow.readiness.can_close || preparingClose || lifecycleBusy}
              onClick={() => void prepareClose()}
              type="button"
              variant="primary"
            >
              {preparingClose ? "Проверяем…" : viewedStep.primary_action?.label}
            </Button>
          </section>
        ) : null}

        {closed && workflow.outlook ? <NextMonthOutlook outlook={workflow.outlook} /> : null}

        {closed ? (
          <section className={styles.closeClosedActions}>
            <Link className={styles.primaryButton} to="/v2">
              Вернуться в «Мои финансы»
            </Link>
            <Button
              disabled={lifecycleBusy}
              onClick={requestReopen}
              type="button"
              variant="secondary"
            >
              Открыть месяц заново
            </Button>
          </section>
        ) : null}
      </div>
    );
  }

  return (
    <UiV2Shell
      active={null}
      busy={!monthsReady || (monthId !== null && !workflowReady)}
      header={
        <>
          <p className={styles.eyebrow}>Пошаговое закрытие</p>
          <h1>
            {selectedMonth
              ? `Закрытие месяца · ${formatMonth(selectedMonth.year, selectedMonth.month)}`
              : "Закрытие месяца"}
          </h1>
          <p className={styles.subtitle}>
            Сервер определяет порядок, состояние, готовность и следующее действие.
          </p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
      <ConfirmDialog
        busy={lifecycleBusy}
        cancelLabel="Отмена"
        confirmLabel={pendingLifecycle === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingLifecycle === "close"}
        description={
          pendingLifecycle === "close"
            ? "Закрыть месяц? Перед сохранением workflow будет перечитан ещё раз."
            : "Открыть месяц заново? Данные снова станут редактируемыми."
        }
        onCancel={cancelLifecycle}
        onConfirm={() => void confirmLifecycle()}
        open={pendingLifecycle !== null}
        title={pendingLifecycle === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />
    </UiV2Shell>
  );
}
