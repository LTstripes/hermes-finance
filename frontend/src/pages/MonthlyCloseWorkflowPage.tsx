import { useEffect } from "react";
import { Link, useParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import { useMonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { FinalMonthReview } from "../components/month-close/FinalMonthReview";
import { routeForGuidedAction } from "../components/month-close/navigation";
import { MonthlyCloseStepSummary } from "../components/month-close/ProviderStepSummary";
import { Badge, EmptyState, ErrorState, LoadingState, Panel } from "../components/ui";
import { formatDate, formatMonth } from "../lib/format";
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";

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
  const parsedMonthId = Number(params.monthId);
  const monthId = Number.isInteger(parsedMonthId) && parsedMonthId > 0 ? parsedMonthId : null;
  const workflowQuery = useMonthCloseWorkflow(monthId);

  useEffect(() => {
    function refetchOnFocus() {
      void workflowQuery.refetch();
    }
    window.addEventListener("focus", refetchOnFocus);
    return () => window.removeEventListener("focus", refetchOnFocus);
  }, [workflowQuery.refetch]);

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
  const workflow = workflowQuery.data;
  if (!workflow) return null;
  const recommended =
    workflow.steps.find((step) => step.id === workflow.recommended_step_id) ?? null;
  const primaryAction = recommended?.primary_action ?? null;
  const finalReviewActive = recommended?.id === "final_review_close";

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

      {recommended ? (
        <Panel className="monthly-close__current" label="Сейчас" title={recommended.title}>
          <p>{recommended.why}</p>
          <MonthlyCloseStepSummary step={recommended} />
          <div className="monthly-close__primary-row">
            <span className="muted">
              {workflow.progress.completed_or_skipped} из {workflow.progress.total_applicable} шагов
              подтверждены сохранёнными фактами
            </span>
            {primaryAction && !finalReviewActive ? (
              <Link
                className="btn btn--primary"
                to={routeForGuidedAction(primaryAction.id, workflow.month.id, recommended.id)}
              >
                {primaryAction.label}
              </Link>
            ) : null}
          </div>
        </Panel>
      ) : (
        <Panel label="Статус" title="Нет следующего действия">
          <p>Backend не рекомендовал действие для текущего состояния месяца.</p>
        </Panel>
      )}

      <FinalMonthReview
        active={finalReviewActive}
        onClosed={() => void workflowQuery.refetch()}
        review={workflow.final_review}
      />

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
        <Link className="btn btn--secondary" to="/monthly-close">
          Другой месяц
        </Link>
        <Link className="btn btn--ghost" to={`/months/${workflow.month.id}`}>
          Открыть месяц напрямую
        </Link>
      </div>
    </section>
  );
}
