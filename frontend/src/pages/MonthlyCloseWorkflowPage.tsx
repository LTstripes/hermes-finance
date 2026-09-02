import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import { useMonthCloseWorkflow, type MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { closeMonth, reopenMonth } from "../api/months";
import { FinalMonthReview } from "../components/month-close/FinalMonthReview";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import { routeForGuidedAction } from "../components/month-close/navigation";
import { MonthlyCloseStepSummary } from "../components/month-close/ProviderStepSummary";
import {
  parseAlfaStatementTransientOutcome,
  type AlfaStatementTransientOutcome,
} from "../components/month-close/statementOutcome";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  Panel,
} from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { queryKeys } from "../queryClient";

const STATE_LABELS = {
  not_started: "Ещё не начато",
  ready: "Следующее действие",
  completed: "Готово",
  skipped: "Не применяется",
  warning: "Нужно внимание",
  blocked: "Требуется исправить",
} as const;

function stateTone(state: keyof typeof STATE_LABELS) {
  if (state === "completed") return "ok" as const;
  if (state === "skipped") return "info" as const;
  if (state === "warning") return "stale" as const;
  if (state === "blocked") return "missing" as const;
  return "draft" as const;
}

export function MonthlyCloseWorkflowPage() {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const parsedMonthId = Number(params.monthId);
  const monthId = Number.isInteger(parsedMonthId) && parsedMonthId > 0 ? parsedMonthId : null;
  const workflowQuery = useMonthCloseWorkflow(monthId);
  const queryClient = useQueryClient();
  const [pendingLifecycle, setPendingLifecycle] = useState<"close" | "reopen" | null>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [preparingClose, setPreparingClose] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [statementOutcome] = useState<AlfaStatementTransientOutcome | null>(() =>
    parseAlfaStatementTransientOutcome(
      (location.state as { alfaStatementOutcome?: unknown } | null)?.alfaStatementOutcome,
    ),
  );

  useEffect(() => {
    if (!statementOutcome) return;
    navigate(`${location.pathname}${location.search}${location.hash}`, {
      replace: true,
      state: null,
    });
  }, [location.hash, location.pathname, location.search, navigate, statementOutcome]);

  useEffect(() => {
    function refetchOnFocus() {
      void workflowQuery.refetch();
    }
    window.addEventListener("focus", refetchOnFocus);
    return () => window.removeEventListener("focus", refetchOnFocus);
  }, [workflowQuery.refetch]);

  const workflow = workflowQuery.data;
  const activeStep = workflow
    ? (workflow.steps.find((step) => step.id === location.hash.replace(/^#/, "")) ??
      workflow.steps.find((step) => step.id === workflow.recommended_step_id) ??
      null)
    : null;

  useEffect(() => {
    if (!location.hash || !activeStep) return;
    const frame = window.requestAnimationFrame(() => {
      const element = document.getElementById(activeStep.id);
      if (element && typeof element.scrollIntoView === "function") {
        element.scrollIntoView({ block: "start" });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeStep, location.hash]);

  async function refetchAuthoritativeWorkflow(): Promise<MonthCloseWorkflow> {
    const result = await workflowQuery.refetch();
    if (result.error) throw result.error;
    if (!result.data) throw new Error("Актуальное состояние месяца не получено.");
    return result.data;
  }

  function closeIsAllowed(current: MonthCloseWorkflow): boolean {
    return current.month.status === "draft" && current.readiness.can_close;
  }

  async function prepareClose() {
    if (!workflow || preparingClose || lifecycleBusy) return;
    setPreparingClose(true);
    setLifecycleError(null);
    try {
      const latest = await refetchAuthoritativeWorkflow();
      if (latest.month.status === "closed") {
        setLifecycleError("Месяц уже закрыт в другой вкладке. Состояние обновлено.");
      } else if (!closeIsAllowed(latest)) {
        setLifecycleError(
          "Состояние готовности изменилось. Проверь актуальные блокеры и предупреждения.",
        );
      } else {
        setPendingLifecycle("close");
      }
    } catch (error) {
      setLifecycleError(formatApiError(error));
    } finally {
      setPreparingClose(false);
    }
  }

  async function confirmLifecycle() {
    if (!pendingLifecycle || !workflow || lifecycleBusy) return;
    setLifecycleBusy(true);
    setLifecycleError(null);
    try {
      const latest = await refetchAuthoritativeWorkflow();
      if (pendingLifecycle === "close" && !closeIsAllowed(latest)) {
        setPendingLifecycle(null);
        setLifecycleError(
          latest.month.status === "closed"
            ? "Месяц уже закрыт в другой вкладке. Состояние обновлено."
            : "Состояние готовности изменилось. Проверь актуальные блокеры и предупреждения.",
        );
        return;
      }
      if (pendingLifecycle === "reopen" && latest.month.status !== "closed") {
        setPendingLifecycle(null);
        setLifecycleError("Месяц уже открыт для редактирования. Состояние обновлено.");
        return;
      }

      const persisted =
        pendingLifecycle === "close"
          ? await closeMonth(monthId as number)
          : await reopenMonth(monthId as number);
      const expectedStatus = pendingLifecycle === "close" ? "closed" : "draft";
      if (persisted.status !== expectedStatus) {
        throw new Error("Сервер не подтвердил новое состояние месяца.");
      }

      await queryClient.invalidateQueries({ queryKey: queryKeys.months });
      await queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(monthId) });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.monthCloseWorkflow(monthId),
        refetchType: "none",
      });
      const refreshed = await refetchAuthoritativeWorkflow();
      if (refreshed.month.status !== expectedStatus) {
        throw new Error("Актуальное состояние месяца не совпало с ответом сервера.");
      }
      setPendingLifecycle(null);
    } catch (error) {
      setPendingLifecycle(null);
      setLifecycleError(formatApiError(error));
      try {
        await refetchAuthoritativeWorkflow();
      } catch {
        // The query state contains the authoritative error, including a possible 404.
      }
    } finally {
      setLifecycleBusy(false);
    }
  }

  if (monthId === null) {
    return (
      <EmptyState
        action={
          <Link className="btn btn--primary" to="/monthly-close">
            Выбрать месяц
          </Link>
        }
        description="В адресе нужен числовой идентификатор отчётного месяца."
        title="Некорректный месяц"
      />
    );
  }
  if (workflowQuery.isPending) return <LoadingState description="Определяем следующее действие…" />;
  if (workflowQuery.error) {
    const missing =
      workflowQuery.error instanceof ApiClientError && workflowQuery.error.status === 404;
    return (
      <ErrorState
        description={
          missing
            ? "Такого отчётного месяца больше нет. Выбери другой месяц."
            : formatApiError(workflowQuery.error)
        }
        title={missing ? "Месяц не найден" : "Не удалось открыть закрытие"}
      />
    );
  }
  if (!workflow) return null;
  const recommended =
    workflow.steps.find((step) => step.id === workflow.recommended_step_id) ?? null;
  const primaryAction = activeStep?.primary_action ?? null;
  const finalReviewActive = activeStep?.id === "final_review_close";
  const closeAction = finalReviewActive && primaryAction?.id === "confirm_close";
  const finalReviewAction =
    workflow.month.status === "draft" &&
    activeStep?.id !== "final_review_close" &&
    workflow.steps.some((step) => step.id === "final_review_close")
      ? routeForGuidedAction("open_final_review", workflow.month.id, activeStep?.id ?? "readiness")
      : null;

  return (
    <section className="stack-18 monthly-close">
      <header className="page-header">
        <p className="eyebrow">Пошаговое закрытие</p>
        <h1>{formatMonth(workflow.month.year, workflow.month.month)}</h1>
        <div className="monthly-close__meta">
          <Badge tone={workflow.month.status === "closed" ? "closed" : "draft"}>
            {labelOf(MONTH_STATUS_LABELS, workflow.month.status)}
          </Badge>
          <span>
            Дата снимка:{" "}
            {workflow.month.snapshot_date ? formatDate(workflow.month.snapshot_date) : "не указана"}
          </span>
        </div>
        <p className="page-header__description">
          Состояние заново получено из локальных данных. Предпросмотры провайдеров здесь не
          запускаются, прогресс в браузере не сохраняется.
        </p>
      </header>

      {statementOutcome ? (
        <div className="statement-import__wizard-outcome" role="status">
          <div>
            <strong>Результат проверки PDF Alfa</strong>
            <p>
              {statementOutcome.kind === "applied"
                ? `Применено выбранных строк: ${statementOutcome.selectedCount}. Состояние шага подтверждается сохранёнными данными.`
                : "В этом PDF подходящих выплат не найдено. Это только текущий результат проверки; шаг остаётся доступным для повторного запроса."}
            </p>
          </div>
        </div>
      ) : null}

      {activeStep ? (
        <Panel className="monthly-close__current" label="Сейчас" title={activeStep.title}>
          <p>{activeStep.why}</p>
          <MonthlyCloseStepSummary step={activeStep} />
          <div className="monthly-close__primary-row">
            <span className="muted">
              {workflow.progress.completed_or_skipped} из {workflow.progress.total_applicable} шагов
              подтверждены сохранёнными фактами
            </span>
            {lifecycleError ? (
              <span className="inline-alert inline-alert--error" role="alert">
                {lifecycleError}
              </span>
            ) : null}
            {closeAction ? (
              <Button
                disabled={!workflow.readiness.can_close || preparingClose || lifecycleBusy}
                onClick={() => void prepareClose()}
                type="button"
                variant="primary"
              >
                {preparingClose ? "Проверяем…" : primaryAction.label}
              </Button>
            ) : primaryAction && !finalReviewActive ? (
              <Link
                className="btn btn--primary"
                to={routeForGuidedAction(primaryAction.id, workflow.month.id, activeStep.id)}
              >
                {primaryAction.label}
              </Link>
            ) : null}
          </div>
          {recommended &&
          recommended.id === activeStep.id &&
          recommended.secondary_actions.length > 0 ? (
            <div className="monthly-close__secondary-row">
              {recommended.secondary_actions.map((action) => (
                <Link
                  className="btn btn--secondary"
                  key={action.id}
                  to={routeForGuidedAction(action.id, workflow.month.id, recommended.id)}
                >
                  {action.label}
                </Link>
              ))}
            </div>
          ) : null}
          {finalReviewAction ? (
            <div className="monthly-close__secondary-row">
              <Link className="btn btn--secondary" to={finalReviewAction}>
                Открыть итоговую проверку
              </Link>
            </div>
          ) : null}
        </Panel>
      ) : (
        <Panel label="Статус" title="Нет следующего действия">
          <p>Для текущего состояния месяца нет следующего действия.</p>
        </Panel>
      )}

      <FinalMonthReview review={workflow.final_review} />
      {workflow.month.status === "closed" && workflow.outlook ? (
        <NextMonthOutlook outlook={workflow.outlook} />
      ) : null}

      <ol className="monthly-close__steps" aria-label="Шаги закрытия">
        {workflow.steps.map((step) => (
          <li className="monthly-close__step" id={step.id} key={step.id}>
            <span className="monthly-close__step-order">{step.order}</span>
            <div>
              <strong>{step.title}</strong>
              <p>{step.why}</p>
              <MonthlyCloseStepSummary compact step={step} />
            </div>
            <Badge tone={stateTone(step.state)}>{STATE_LABELS[step.state]}</Badge>
          </li>
        ))}
      </ol>

      <div className="monthly-close__footer-actions">
        {workflow.month.status === "closed" ? (
          <Button
            disabled={lifecycleBusy}
            onClick={() => {
              setLifecycleError(null);
              setPendingLifecycle("reopen");
            }}
            type="button"
            variant="secondary"
          >
            Открыть месяц заново
          </Button>
        ) : null}
        <Link className="btn btn--secondary" to="/monthly-close">
          Другой месяц
        </Link>
        <Link className="btn btn--ghost" to={`/months/${workflow.month.id}`}>
          Открыть месяц напрямую
        </Link>
      </div>
      <ConfirmDialog
        busy={lifecycleBusy}
        cancelLabel="Отмена"
        confirmLabel={pendingLifecycle === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingLifecycle === "close"}
        description={
          pendingLifecycle === "close"
            ? "Закрыть месяц? Данные будут зафиксированы до явного повторного открытия."
            : "Открыть месяц заново? Данные снова станут редактируемыми."
        }
        onCancel={() => setPendingLifecycle(null)}
        onConfirm={() => void confirmLifecycle()}
        open={pendingLifecycle !== null}
        title={pendingLifecycle === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />
    </section>
  );
}
