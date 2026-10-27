import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import type { GuidedCloseActionId, GuidedCloseStep } from "../api/monthCloseWorkflow";
import { listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { useBrokerOriginalContext } from "../components/month-close/brokerOriginalSession";
import {
  FinalMonthReview,
  MonthCompletionSummary,
} from "../components/month-close/FinalMonthReview";
import { IntentionalEmptyClose } from "../components/month-close/IntentionalEmptyClose";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import { isGuidedCloseStepId, routeForGuidedAction } from "../components/month-close/navigation";
import { closeOwnerCopy } from "../components/month-close/ownerCopy";
import { MoneyAmount } from "../components/ui";
import UiV2MonthEditorPage, { type EditorSection } from "./UiV2MonthEditorPage";
import { MonthNavigationGuard } from "./MonthNavigationGuard";
import { useBrokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import { useSourceIntakeRecovery } from "../components/month-close/SourceIntakeJournal";
import { MonthlyCloseStepSummary } from "../components/month-close/ProviderStepSummary";
import {
  type AlfaStatementTransientOutcome,
  parseAlfaStatementTransientOutcome,
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
import { UiV2MonthSources } from "./UiV2MonthSources";
import monthStyles from "./UiV2MonthWorkspace.module.css";
import styles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

const STATE_LABELS: Record<GuidedCloseStep["state"], string> = {
  not_started: "Ещё не начато",
  ready: "Следующее действие",
  completed: "Готово",
  skipped: "Не применяется",
  warning: "Нужно внимание",
  blocked: "Требуется исправить",
};

const MANUAL_SECTIONS = [
  ["general", "Снимок и общие данные", "Дата, источник, настройки месяца"],
  ["income", "Зарплата и другие доходы", "Ручные поступления"],
  ["assets", "Депозиты, накопления и деньги", "Остатки и проценты"],
  ["positions", "Счета и позиции", "Количество и оценка"],
  ["payouts", "Выплаты", "Получено / из выписок · Ожидается · T-Invest"],
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
  const [emptyClosePending, setEmptyClosePending] = useState(false);
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
    lifecycleRecovery,
    recoverLifecycle,
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
  const panels = [...MANUAL_SECTIONS.map(([id]) => id), "brokers", "close"];
  const panelValues = params.getAll("panel");
  const legacySection = params.getAll("section");
  const panel = panelValues.length
    ? panelValues.length === 1 && panels.includes(panelValues[0])
      ? panelValues[0]
      : "invalid"
    : legacySection.length
      ? legacySection.length === 1 && panels.includes(legacySection[0])
        ? legacySection[0]
        : "invalid"
      : params.has("step")
        ? "close"
        : null;
  const closed = workflowIdentityMatches && workflow.month.status === "closed";
  const finalReviewActive = panel === "close";
  const previousPanel = useRef(panel);
  const refetchWorkflow = workflowQuery.refetch;
  useEffect(() => {
    if (previousPanel.current !== panel && panel === "close") void refetchWorkflow();
    previousPanel.current = panel;
  }, [panel, refetchWorkflow]);
  const workflowReady = isQueryReady(workflowQuery);
  const { original, session } = useBrokerOriginalSession();
  const { command: journalCommand } = useSourceIntakeRecovery();
  const [uploadPending, setUploadPending] = useState(false);
  const [journalDirty, setJournalDirty] = useState(false);
  const [editorNavigation, setEditorNavigation] = useState({ dirty: false, pending: false });
  const [discardVersion, setDiscardVersion] = useState(0);
  const sourcePending = Boolean(
    original.pending || original.busy || journalCommand || uploadPending,
  );
  const sourceDirty =
    ["brokers", "payouts"].includes(panel ?? "") &&
    (journalDirty || (Boolean(original.file) && !original.confirmed));
  const panelPath = (next: string | null) => {
    const query = new URLSearchParams(location.search);
    query.delete("panel");
    query.delete("section");
    query.delete("step");
    if (next) query.set("panel", next);
    return monthId ? monthWorkspacePath(monthId, undefined, query.toString()) : "/v2/close";
  };
  useEffect(() => {
    if (selection.kind === "automatic" && selectedMonth)
      navigate(monthWorkspacePath(selectedMonth.id), { replace: true });
  }, [selection.kind, selectedMonth, navigate]);
  useEffect(() => {
    if (!statementOutcome) return;
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.pathname, location.search, navigate, statementOutcome]);

  let content: ReactNode;
  if (selection.kind === "invalid")
    content = <UiV2Notice title="Некорректный месяц">Выбери период явно.</UiV2Notice>;
  else if (monthsQuery.isPending) content = <UiV2Loading label="Загружаем месяцы…" />;
  else if (monthsQuery.isError && !selectedPeriod)
    content = (
      <UiV2Notice title="Список месяцев не подтверждён" retry={() => void monthsQuery.refetch()}>
        {formatApiError(monthsQuery.error)}
      </UiV2Notice>
    );
  else if (!selectedMonth)
    content = <UiV2Notice title="Месяц не найден">Выбери или создай отчётный месяц.</UiV2Notice>;
  else if (!selectionIdentityMatches)
    content = (
      <UiV2Notice title="Период выбранного месяца изменился">
        Выбери месяц из списка явно.
      </UiV2Notice>
    );
  else if (!workflowQuery.data && workflowQuery.isError)
    content = (
      <UiV2Notice title="Не удалось открыть месяц" retry={() => void workflowQuery.refetch()}>
        {formatApiError(workflowQuery.error)}
      </UiV2Notice>
    );
  else if (!workflowQuery.data) content = <UiV2Loading label="Читаем состояние месяца…" />;
  else if (!workflowIdentityMatches)
    content = (
      <UiV2Notice
        title="Состояние месяца не подтверждено"
        retry={() => void workflowQuery.refetch()}
      >
        Ответ не совпал с выбранным периодом. Действия скрыты.
      </UiV2Notice>
    );
  else {
    const tiles = [
      ...MANUAL_SECTIONS.filter(([id]) =>
        ["general", "income", "assets", "budget", "liabilities"].includes(id),
      ),
      ["brokers", "Брокерские выписки", "Загрузка и разбор источников"],
      ...MANUAL_SECTIONS.filter(([id]) => ["positions", "payouts", "note"].includes(id)),
      ["close", "Закрыть месяц", "Итоговая проверка"],
    ];
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
        </div>
        <nav className={monthStyles.manual} aria-label="Разделы месяца">
          {tiles.map(([id, label, hint]) => (
            <Link key={id} to={panelPath(id)} aria-current={panel === id ? "page" : undefined}>
              {label}
              <span>{hint}</span>
            </Link>
          ))}
        </nav>
        {panel === "invalid" ? (
          <UiV2Notice title="Неизвестный раздел">
            <Link to={panelPath(null)}>← К месяцу</Link>
          </UiV2Notice>
        ) : panel ? (
          <section
            className={monthStyles.workArea}
            aria-label={`Рабочая область: ${tiles.find(([id]) => id === panel)?.[1]}`}
            id="month-work-area"
          >
            <header className={monthStyles.workHeader}>
              <h2>{tiles.find(([id]) => id === panel)?.[1]}</h2>
              <Link to={panelPath(null)}>← К месяцу</Link>
            </header>
            {panel === "payouts" ? (
              <>
                <nav className={monthStyles.sourceNav} aria-label="Выплаты месяца">
                  <a href="#month-instruments">Получено / из выписок</a>
                  <a href="#month-payout-preview">Ожидается · T-Invest</a>
                  <a href="#month-accepted-payouts">Принятые фактические выплаты</a>
                  <a href="#month-source-review">Рассмотрение и сверка</a>
                </nav>
                <p>
                  Выписка показывает наблюдения источника. Принятые выплаты показаны отдельно;
                  наблюдения не прибавляются к ним повторно. T-Invest даёт предварительные будущие
                  выплаты, а не подтверждение полученной суммы.
                </p>
              </>
            ) : null}
            {panel === "brokers" || panel === "payouts" ? (
              <UiV2MonthSources
                key={`sources:${workflow.month.id}:${panel}:${discardVersion}`}
                month={workflow.month}
                payoutsOnly={panel === "payouts"}
                canClose={workflowReady && workflow.readiness.can_close}
                onPendingChange={setUploadPending}
                onDirtyChange={setJournalDirty}
              />
            ) : null}
            {MANUAL_SECTIONS.some(([id]) => id === panel) ? (
              <UiV2MonthEditorPage
                key={`editor:${workflow.month.id}:${panel}:${discardVersion}`}
                embeddedMonthId={workflow.month.id}
                embeddedSection={panel as EditorSection}
                onNavigationStateChange={setEditorNavigation}
              />
            ) : null}
            {panel === "close" ? (
              <>
                {!workflowReady ? <UiV2Loading label="Проверяем актуальное состояние…" /> : null}
                {workflowQuery.isError ? (
                  <UiV2Notice
                    title="Готовность не подтверждена"
                    retry={() => void workflowQuery.refetch()}
                  >
                    {formatApiError(workflowQuery.error)}
                  </UiV2Notice>
                ) : null}
                {workflowReady && workflow.final_review.available ? (
                  <>
                    <fieldset className={monthStyles.totals} aria-label="Итоги месяца">
                      <div>
                        <span>Ликвидный капитал</span>
                        <MoneyAmount
                          amount={
                            workflow.final_review.assets_and_cash.liquid_capital
                              ?.liquid_capital_net ?? null
                          }
                        />
                      </div>
                      <div>
                        <span>Пассивный доход</span>
                        <MoneyAmount amount={workflow.final_review.actual_passive_income} />
                      </div>
                      <div>
                        <span>Инвестиции</span>
                        <MoneyAmount amount={workflow.final_review.investments.market_value} />
                      </div>
                    </fieldset>
                    <MonthCompletionSummary
                      cards={workflow.final_review.manual_review_cards}
                      className={monthStyles.completion}
                    />
                    <p>
                      {closed
                        ? "Данные зафиксированы"
                        : `Подтверждено шагов: ${workflow.progress.completed_or_skipped} из ${workflow.progress.total_applicable}`}{" "}
                      ·{" "}
                      {workflow.readiness.can_close
                        ? "Готов к закрытию"
                        : `Требует внимания: ${workflow.readiness.hard_blocker_count}`}
                    </p>
                    {workflow.final_review.close_readiness.items
                      .filter((item) => item.severity === "hard_blocker")
                      .map((item) => (
                        <p role="status" key={`${item.code}:${item.message}`}>
                          {closeOwnerCopy(item.message)}
                        </p>
                      ))}
                    <details>
                      <summary>Подробнее об итогах и проверках</summary>
                      <FinalMonthReview
                        workspace
                        origin="monthly-close-v2"
                        review={workflow.final_review}
                      />
                    </details>
                  </>
                ) : workflowReady ? (
                  <UiV2Notice title="Итоги пока недоступны">
                    Проверь сохранённые данные месяца.
                  </UiV2Notice>
                ) : null}
                {!closed ? (
                  <Button
                    variant="primary"
                    type="button"
                    disabled={
                      !workflowReady ||
                      !workflow.readiness.can_close ||
                      preparingClose ||
                      lifecycleBusy ||
                      lifecycleRecovery ||
                      emptyClosePending
                    }
                    onClick={() => void prepareClose()}
                  >
                    {preparingClose ? "Проверяем…" : "Закрыть месяц"}
                  </Button>
                ) : (
                  <div className={monthStyles.sourceNav}>
                    <Link to="/v2">Открыть «Мои финансы»</Link>
                    <Button
                      type="button"
                      disabled={lifecycleBusy || lifecycleRecovery}
                      onClick={requestReopen}
                    >
                      Открыть месяц заново
                    </Button>
                  </div>
                )}
                {selectionIdentityMatches && selectedMonth && finalReviewActive ? (
                  <IntentionalEmptyClose
                    key={`${selectedMonth.id}:${selectedMonth.snapshot_date}`}
                    month={selectedMonth}
                    onPendingChange={setEmptyClosePending}
                    available={Boolean(
                      workflowIdentityMatches &&
                        workflowReady &&
                        !closed &&
                        workflow.readiness.reason_codes.includes("empty_manual_month"),
                    )}
                  />
                ) : null}
                <details>
                  <summary>Дополнительные интеграции и проверки</summary>
                  <StepList
                    monthId={workflow.month.id}
                    steps={workflow.steps}
                    viewedStepId={viewedStep?.id ?? null}
                  />
                  {!closed && viewedStep?.id === "market_quotes" && !viewedStep.primary_action ? (
                    <Link to={actionPath("open_quote_preview", workflow.month.id, viewedStep.id)}>
                      Открыть котировки
                    </Link>
                  ) : null}
                  {viewedStep &&
                    (!closed || viewedStep.id === "next_month_outlook") &&
                    [viewedStep.primary_action, ...viewedStep.secondary_actions].map((action) =>
                      action && action.id !== "confirm_close" ? (
                        <Link
                          key={action.id}
                          to={actionPath(action.id, workflow.month.id, viewedStep.id)}
                        >
                          {closeOwnerCopy(action.label)}
                        </Link>
                      ) : null,
                    )}
                  {closed && workflow.outlook ? (
                    <NextMonthOutlook outlook={workflow.outlook} />
                  ) : null}
                </details>
              </>
            ) : null}
            <footer className={monthStyles.workFooter}>
              <Link to={panelPath(null)}>← К месяцу</Link>
            </footer>
          </section>
        ) : null}
      </div>
    );
  }
  return (
    <UiV2Shell
      busy={monthsQuery.isPending}
      header={
        <>
          <p className={styles.eyebrow}>Месяц</p>
          <h1>
            {selectedPeriod
              ? `Месяц · ${formatMonth(selectedPeriod.year, selectedPeriod.month)}`
              : "Месяц"}
          </h1>
        </>
      }
    >
      <Link to="/v2/data/months">Отчётные месяцы →</Link>
      {lifecycleError ? <p role="alert">{lifecycleError}</p> : null}
      {lifecycleRecovery && !lifecycleBusy ? (
        <p role="status">
          Результат изменения месяца ещё не подтверждён.
          <Button type="button" disabled={workflowQuery.isFetching} onClick={recoverLifecycle}>
            Проверить состояние месяца
          </Button>
        </p>
      ) : null}
      {content}
      <MonthNavigationGuard
        dirty={sourceDirty || editorNavigation.dirty}
        pending={
          sourcePending ||
          editorNavigation.pending ||
          lifecycleBusy ||
          lifecycleRecovery ||
          Boolean(pendingLifecycle) ||
          emptyClosePending
        }
        onDiscard={(destination) => {
          setDiscardVersion((value) => value + 1);
          setEditorNavigation({ dirty: false, pending: false });
          if (sourceDirty && monthId !== null) {
            // Catalogue round-trips retain the actual File while retiring its
            // preview/decisions. An explicit Month-panel discard drops it.
            const withinMonth = destination?.split("?")[0] === "/v2/close";
            session.select(withinMonth ? null : original.file, monthId, original.accountId);
          }
        }}
      />
      <ConfirmDialog
        busy={lifecycleBusy}
        cancelLabel="Отмена"
        confirmLabel={pendingLifecycle === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingLifecycle === "close"}
        description={
          pendingLifecycle === "close"
            ? "Зафиксировать данные выбранного месяца?"
            : "Открыть месяц для исправлений?"
        }
        onCancel={cancelLifecycle}
        onConfirm={() => void confirmLifecycle()}
        open={pendingLifecycle !== null && selectionIdentityMatches}
        title={pendingLifecycle === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />
    </UiV2Shell>
  );
}
