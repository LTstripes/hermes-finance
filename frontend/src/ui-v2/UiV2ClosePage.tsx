import { useBrokerOriginalContext } from "../components/month-close/brokerOriginalSession";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import type { GuidedCloseActionId, GuidedCloseStep } from "../api/monthCloseWorkflow";
import type { ReportingMonth } from "../api/types";
import { listMonths } from "../api/months";
import { FinalMonthReview } from "../components/month-close/FinalMonthReview";
import { BrokerMonthReview } from "../components/month-close/BrokerMonthReview";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import { isGuidedCloseStepId, routeForGuidedAction } from "../components/month-close/navigation";
import { MonthlyCloseStepSummary } from "../components/month-close/ProviderStepSummary";
import { closeOwnerCopy } from "../components/month-close/ownerCopy";
import { withMonthlyCloseReturn } from "../components/month-close/navigation";
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
import { UiV2MonthSources } from "./UiV2MonthSources";
import { UiV2Panel } from "./UiV2Panel";
import monthStyles from "./UiV2MonthWorkspace.module.css";
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

const MANUAL_SECTIONS = [
  ["general", "Снимок и общие данные", "Дата, источник, настройки месяца"],
  ["income", "Зарплата и другие доходы", "Ручные поступления"],
  ["assets", "Депозиты, накопления и деньги", "Остатки и проценты"],
  ["positions", "Счета и позиции", "Количество и оценка"],
  ["payouts", "Полученные выплаты", "Фактические инвестиционные выплаты"],
  ["budget", "Расходы и план", "Обязательные расходы и откладывание"],
  ["liabilities", "Долги, кредитка и недвижимость", "Долг, ипотека и платежи"],
  ["note", "Комментарии", "Пояснения к месяцу"],
] as const;

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
  const location = useLocation();
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
              to={monthWorkspacePath(monthId, step.id, location.search, location.hash)}
            >
              {step.title}
            </Link>
            <p>{closeOwnerCopy(step.why)}</p>
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
  const [intakeSelection, setIntakeSelection] = useState<{ monthId: number; id: number } | null>(
    null,
  );
  useBrokerOriginalContext(monthId, selectedMonth?.status === "closed");
  const selectionKey = params.getAll("month").join(":");
  const identity = useRef<{
    key: string;
    period: Pick<ReportingMonth, "id" | "year" | "month">;
  } | null>(null);
  if (identity.current && identity.current.key !== selectionKey) {
    if (identity.current.key === "" && selectionKey === String(identity.current.period.id)) {
      // The automatic route is canonicalized to its already selected month.
      identity.current.key = selectionKey;
    } else {
      identity.current = null;
    }
  }
  if (!identity.current && selectedMonth && isQueryReady(monthsQuery)) {
    identity.current = { key: selectionKey, period: { ...selectedMonth } };
  }
  const selectedPeriod = identity.current?.period;
  const selectionIdentityMatches =
    Boolean(selectedMonth && selectedPeriod) &&
    selectedMonth?.id === selectedPeriod?.id &&
    selectedMonth?.year === selectedPeriod?.year &&
    selectedMonth?.month === selectedPeriod?.month;
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
  } = useMonthCloseLifecycle(selectionIdentityMatches ? monthId : null, selectedPeriod);
  const [statementOutcome] = useState<AlfaStatementTransientOutcome | null>(() =>
    parseAlfaStatementTransientOutcome(
      (location.state as { alfaStatementOutcome?: unknown } | null)?.alfaStatementOutcome,
    ),
  );
  const focusedStepRef = useRef<string | null>(null);
  const explicitInitialStep = useRef(params.has("step"));
  const workflow = workflowQuery.data;
  const workflowIdentityMatches =
    selectionIdentityMatches &&
    workflow?.contract_version === "monthly_close_workflow_v1" &&
    workflow.month.id === monthId &&
    workflow.month.year === selectedPeriod?.year &&
    workflow.month.month === selectedPeriod?.month &&
    (!workflow.final_review.available ||
      (workflow.final_review.month_header.id === monthId &&
        workflow.final_review.month_header.year === workflow.month.year &&
        workflow.final_review.month_header.month === workflow.month.month &&
        workflow.final_review.month_header.status === workflow.month.status)) &&
    (!workflow.outlook ||
      (workflow.outlook.source_month.id === monthId &&
        workflow.outlook.source_month.year === workflow.month.year &&
        workflow.outlook.source_month.month === workflow.month.month));
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
    const canonicalParams = new URLSearchParams(location.search);
    canonicalParams.set("month", String(monthId));
    canonicalParams.set("step", viewedStep.id);
    const canonical = `/v2/close?${canonicalParams}${location.hash}`;
    if (`${location.pathname}${location.search}${location.hash}` !== canonical) {
      navigate(canonical, { replace: true });
    }
  }, [
    location.pathname,
    location.search,
    location.hash,
    monthId,
    navigate,
    viewedStep,
    workflowIdentityMatches,
  ]);

  useEffect(() => {
    const focusKey = `${monthId}:${viewedStep?.id}`;
    if (!viewedStep || focusedStepRef.current === focusKey) return;
    if (focusedStepRef.current === null && !explicitInitialStep.current) {
      focusedStepRef.current = focusKey;
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const element = document.getElementById(CURRENT_STEP_ID);
      if (!element) return;
      focusedStepRef.current = focusKey;
      element.scrollIntoView?.({ block: "start" });
      element.focus?.({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [monthId, viewedStep]);

  const monthsReady = isQueryReady(monthsQuery);
  const workflowReady = isQueryReady(workflowQuery);
  const closed = workflowIdentityMatches && workflow.month.status === "closed";
  const finalReviewActive = viewedStep?.id === "final_review_close";
  const closeAction = !closed && finalReviewActive;

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice
        title="Не удалось загрузить отчётные месяцы"
        retry={() => void monthsQuery.refetch()}
      >
        Закрытие скрыто, пока список месяцев не подтверждён.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем отчётные месяцы…" />;
  } else if (selection.kind === "invalid") {
    content = (
      <UiV2Notice title="Некорректный месяц">
        Адрес должен содержать один положительный идентификатор месяца. Выбери месяц в{" "}
        <Link to="/v2/data/months">списке отчётных месяцев →</Link>
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
        <Link to="/v2/reports">посмотреть историю отчётов →</Link>
      </UiV2Notice>
    );
  } else if (!selectionIdentityMatches) {
    content = (
      <UiV2Notice title="Период выбранного месяца изменился">
        Действия скрыты. Выбери отчётный месяц заново из{" "}
        <Link to="/v2/data/months">списка месяцев →</Link>.
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
          ? "Этот месяц больше не подтверждён. Другой месяц автоматически не выбран."
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
        Финансовые значения скрыты: полученное состояние закрытия или его разделы не совпали с
        выбранным месяцем, либо шаги отсутствуют.
      </UiV2Notice>
    );
  } else {
    const outlookAction = closed && viewedStep.id === "next_month_outlook";
    const primaryAction = !closed || outlookAction ? viewedStep.primary_action : null;
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
              подтверждены сохранёнными фактами. События следующего месяца — после закрытия.
            </span>
          )}
        </div>

        <UiV2Panel
          eyebrow={closed ? "Сохранённые факты" : "Личные данные"}
          title="Ручные разделы"
          id="month-manual"
          testIdPrefix="month"
          wide
        >
          <nav className={monthStyles.manual} aria-label="Ручные разделы месяца">
            {MANUAL_SECTIONS.map(([section, label, hint]) => (
              <Link
                key={section}
                to={withMonthlyCloseReturn(
                  `/v2/data/months/${workflow.month.id}?section=${section}`,
                  workflow.month.id,
                  viewedStep.id,
                )}
              >
                {label}
                <span>{hint}</span>
              </Link>
            ))}
          </nav>
        </UiV2Panel>

        <UiV2MonthSources
          key={workflow.month.id}
          month={workflow.month}
          onReview={(id) => {
            setIntakeSelection({ monthId: workflow.month.id, id });
            document.getElementById("month-source-review")?.scrollIntoView({ block: "start" });
          }}
        />

        <div id="month-source-review" tabIndex={-1}>
          <BrokerMonthReview
            key={workflow.month.id}
            monthId={workflow.month.id}
            closed={closed}
            intakeSelection={intakeSelection?.monthId === monthId ? intakeSelection : null}
          />
        </div>

        {statementOutcome ? (
          <section className={styles.closeOutcome} role="status">
            <strong>Результат проверки выписки Alfa</strong>
            <p>
              {statementOutcome.kind === "applied"
                ? `Применено выбранных строк: ${statementOutcome.selectedCount}. Состояние закрытия обновлено по сохранённым данным.`
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
              : closeOwnerCopy(viewedStep.why)}
          </p>
          {!closed ? <MonthlyCloseStepSummary step={viewedStep} /> : null}
          {recommendedStep && recommendedStep.id !== viewedStep.id && !closed ? (
            <p className={styles.closeRecommendation}>
              Следующее действие:{" "}
              <Link
                to={monthWorkspacePath(
                  workflow.month.id,
                  recommendedStep.id,
                  location.search,
                  location.hash,
                )}
              >
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
                {primaryAction.id === "open_quote_preview"
                  ? "Открыть котировки"
                  : closeOwnerCopy(primaryAction.label)}
              </Link>
            </div>
          ) : null}
          {!closed && viewedStep.id === "market_quotes" && !primaryAction ? (
            <Link
              className={styles.primaryButton}
              to={actionPath("open_quote_preview", workflow.month.id, viewedStep.id)}
            >
              Открыть котировки
            </Link>
          ) : null}
          {(!closed || outlookAction) && viewedStep.secondary_actions.length > 0 ? (
            <div className={styles.closeSecondaryRow}>
              {viewedStep.secondary_actions.map((action) => (
                <Link
                  className={styles.secondaryButton}
                  key={action.id}
                  to={actionPath(action.id, workflow.month.id, viewedStep.id)}
                >
                  {closeOwnerCopy(action.label)}
                </Link>
              ))}
            </div>
          ) : null}
          <div className={styles.closeSecondaryRow}>
            <Link
              className={styles.secondaryButton}
              to={withMonthlyCloseReturn(
                `/v2/data/months/${workflow.month.id}`,
                workflow.month.id,
                viewedStep.id,
                "monthly-close-v2",
              )}
            >
              {closed ? "Данные закрытого месяца" : "Редактировать данные месяца"}
            </Link>
            <Link
              className={styles.secondaryButton}
              to={`/v2/data/months?month=${workflow.month.id}`}
            >
              Выбрать другой отчётный месяц
            </Link>
            {finalReviewActive && !closed ? (
              <Link
                to={monthWorkspacePath(
                  workflow.month.id,
                  "readiness",
                  location.search,
                  location.hash,
                )}
              >
                ← К проверке данных
              </Link>
            ) : null}
          </div>
        </section>

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
              {preparingClose ? "Проверяем…" : "Закрыть месяц"}
            </Button>
          </section>
        ) : null}

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
              to={monthWorkspacePath(
                workflow.month.id,
                recommendedStep.id,
                location.search,
                location.hash,
              )}
            >
              Открыть следующее действие
            </Link>
          ) : null}
        </section>

        {finalReviewActive || closed ? (
          <FinalMonthReview origin="monthly-close-v2" review={workflow.final_review} />
        ) : (
          <section className={styles.closeCompactReview}>
            <div>
              <p className={styles.eyebrow}>Итоги месяца</p>
              <h2>Финальная проверка</h2>
              <p>
                Полная сводка откроется на финальном шаге. Итоги приведены по сохранённым данным.
              </p>
            </div>
            <Link
              className={styles.secondaryButton}
              to={monthWorkspacePath(
                workflow.month.id,
                "final_review_close",
                location.search,
                location.hash,
              )}
            >
              Открыть итоговую проверку
            </Link>
          </section>
        )}

        <details
          className={styles.closeStepsOverview}
          key={`${workflow.month.id}:${finalReviewActive}:${closed}`}
        >
          <summary>Шаги закрытия · до закрытия и после него</summary>
          <StepList
            monthId={workflow.month.id}
            steps={workflow.steps}
            viewedStepId={viewedStep.id}
          />
        </details>

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
      busy={!monthsReady || (selectionIdentityMatches && monthId !== null && !workflowReady)}
      header={
        <>
          <p className={styles.eyebrow}>Месяц</p>
          <h1>
            {selectedPeriod
              ? `Месяц · ${formatMonth(selectedPeriod.year, selectedPeriod.month)}`
              : "Месяц"}
          </h1>
          <p className={styles.subtitle}>
            Заполни личные данные, добавь выписки и разбери исключения. Затем проверь готовность и
            явно закрой месяц.
          </p>
        </>
      }
    >
      <Link to="/v2/data/months">Отчётные месяцы →</Link>
      {content}
      <ConfirmDialog
        busy={lifecycleBusy}
        cancelLabel="Отмена"
        confirmLabel={pendingLifecycle === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingLifecycle === "close"}
        description={
          pendingLifecycle === "close"
            ? "Закрыть месяц? Перед сохранением состояние месяца будет проверено ещё раз."
            : "Открыть месяц заново? Данные снова станут редактируемыми."
        }
        onCancel={cancelLifecycle}
        onConfirm={() => void confirmLifecycle()}
        open={pendingLifecycle !== null && selectionIdentityMatches}
        title={pendingLifecycle === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />
    </UiV2Shell>
  );
}
