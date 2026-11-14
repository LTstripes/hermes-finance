import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import type { CloseReadinessItem, ReportingMonth } from "../api/types";
import {
  useBrokerOriginalContext,
  useBrokerOriginalSession,
} from "../components/month-close/brokerOriginalSession";
import { FinalMonthReview } from "../components/month-close/FinalMonthReview";
import { IntentionalEmptyClose } from "../components/month-close/IntentionalEmptyClose";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import {
  closedFindingCopy,
  closeFindingPanel,
  closeOwnerActionFindings,
  closeOwnerCopy,
} from "../components/month-close/ownerCopy";
import { useSourceIntakeRecovery } from "../components/month-close/SourceIntakeJournal";
import {
  type AlfaStatementTransientOutcome,
  parseAlfaStatementTransientOutcome,
} from "../components/month-close/statementOutcome";
import { useMonthCloseLifecycle } from "../components/month-close/useMonthCloseLifecycle";
import { Button, ConfirmDialog } from "../components/ui";
import { OverflowMenu, OverflowMenuItem } from "../components/ui/OverflowMenu";
import { formatDate, formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import { MonthDraftPayouts } from "./MonthDraftPayouts";
import { MonthNavigationGuard } from "./MonthNavigationGuard";
import {
  monthWorkspacePath,
  resolveMonthSelection,
  selectNewestDraftAfterLatestClosed,
  sortReportingMonths,
} from "./monthSelection";
import UiV2MonthEditorPage, { type EditorSection } from "./UiV2MonthEditorPage";
import {
  figureText,
  INCOMPLETE_MONTH_COPY,
  isIncompleteMonthDraft,
  MONTH_STEP_COPY,
  MonthKpis,
  MonthOverview,
  MonthReadiness,
  MonthStepStrip,
} from "./UiV2MonthOverview";
import overviewStyles from "./UiV2MonthOverview.module.css";
import { UiV2MonthSources } from "./UiV2MonthSources";
import monthStyles from "./UiV2MonthWorkspace.module.css";
import styles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2Skeleton } from "./UiV2StateBlocks";
import { moneyText, moneyWholeText } from "./valueFormat";

const MANUAL_SECTIONS = [
  "general",
  "income",
  "assets",
  "positions",
  "payouts",
  "budget",
  "liabilities",
  "note",
] as const;

function CloseFindings({
  items,
  closed,
  pathFor,
}: {
  items: CloseReadinessItem[];
  closed: boolean;
  pathFor: (panel: string) => string;
}) {
  return (
    <ul className={monthStyles.findings}>
      {items.map((item) => {
        const panel = closeFindingPanel(item);
        return (
          <li
            key={`${item.code}:${item.message}`}
            data-severity={closed ? undefined : item.severity}
          >
            <span>{closed ? closedFindingCopy(item.message) : closeOwnerCopy(item.message)}</span>
            {panel ? (
              <Link className="btn btn--ghost btn--sm" to={pathFor(panel)}>
                Открыть шаг
              </Link>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function MonthStatusChip({
  month,
}: {
  month: { status: ReportingMonth["status"]; snapshot_date: string | null };
}) {
  const closed = month.status === "closed";
  return (
    <span className={overviewStyles.chip} data-state={closed ? "closed" : "draft"}>
      <span>{closed ? "Месяц закрыт" : "Черновик"}</span>
      <span>· снимок {month.snapshot_date ? formatDate(month.snapshot_date) : "не указан"}</span>
    </span>
  );
}

/** Older and newer reporting months, in the order of the months list. */
function MonthStepper({
  months,
  current,
  search,
}: {
  months: ReportingMonth[];
  current: number;
  search: string;
}) {
  const index = months.findIndex((month) => month.id === current);
  if (index < 0) return null;
  const older = months[index + 1];
  const newer = index > 0 ? months[index - 1] : undefined;
  // Keep only the panel: a step or section belongs to the month being left.
  const panel = new URLSearchParams(search).get("panel");
  const query = panel ? `panel=${encodeURIComponent(panel)}` : "";
  const link = (month: ReportingMonth | undefined, symbol: string, label: string) =>
    month ? (
      <Link
        aria-label={`${label}: ${formatMonth(month.year, month.month)}`}
        to={monthWorkspacePath(month.id, undefined, query)}
      >
        {symbol}
      </Link>
    ) : (
      <span aria-hidden="true">{symbol}</span>
    );
  return (
    <nav aria-label="Соседние месяцы" className={overviewStyles.stepper}>
      {link(older, "‹", "Предыдущий месяц")}
      {link(newer, "›", "Следующий месяц")}
    </nav>
  );
}

export default function UiV2ClosePage() {
  const fetching = useIsFetching();
  const [params] = useSearchParams();
  const [emptyClosePending, setEmptyClosePending] = useState(false);
  const location = useLocation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
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
  const panels: string[] = [...MANUAL_SECTIONS, "brokers", "close"];
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
  const PayoutForecastContainer = closed ? "details" : "section";
  const finalReviewActive = panel === "close";
  // Refresh the retained review only where it is displayed. Writer panels and
  // lifecycle commands own their independent GETs and must not be raced here.
  useEffect(() => {
    if (
      (panel === null || finalReviewActive) &&
      workflowQuery.isStale &&
      !lifecycleBusy &&
      !preparingClose &&
      !lifecycleRecovery &&
      queryClient.getQueryState(queryKeys.monthCloseWorkflowWithChecklist(monthId))?.isInvalidated
    )
      void workflowQuery.refetch({ cancelRefetch: false });
  }, [
    finalReviewActive,
    lifecycleBusy,
    preparingClose,
    lifecycleRecovery,
    monthId,
    panel,
    queryClient,
    workflowQuery.isStale,
    workflowQuery.refetch,
  ]);
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
    return monthId
      ? `${monthWorkspacePath(monthId, undefined, query.toString())}${location.hash}`
      : "/v2/close";
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
    content =
      selection.kind === "automatic" ? (
        <UiV2Notice title="Выбери или создай отчётный месяц">
          Открой список месяцев, чтобы выбрать существующий месяц или создать новый.
        </UiV2Notice>
      ) : (
        <UiV2Notice title="Месяц не найден">Выбери или создай отчётный месяц.</UiV2Notice>
      );
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
  else if (!workflowQuery.data) content = <UiV2Skeleton label="Читаем состояние месяца…" />;
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
    const findings =
      workflow.checklist?.remarks ??
      (workflow.final_review.available
        ? closeOwnerActionFindings(workflow.final_review.close_readiness.items).filter(
            (item) => item.severity === "hard_blocker" || item.severity === "warning",
          )
        : []);
    const blocked = !closed && !workflow.readiness.can_close;
    const incomplete = isIncompleteMonthDraft(workflow);
    const blockers = blocked ? findings.filter((item) => item.severity === "hard_blocker") : [];
    const remaining = blocked
      ? findings.filter((item) => item.severity !== "hard_blocker")
      : findings;
    const findingCount =
      workflow.checklist?.remark_count ??
      (workflow.final_review.available
        ? findings.length
        : workflow.readiness.hard_blocker_count + workflow.readiness.warning_count);
    const panelLabel =
      panel && panel in MONTH_STEP_COPY
        ? panel === "close" && closed
          ? "Итоги"
          : MONTH_STEP_COPY[panel as keyof typeof MONTH_STEP_COPY].label
        : undefined;
    const panelStep = workflow.checklist?.steps.find((step) => step.id === panel);
    content = !panel ? (
      <>
        <MonthOverview pathFor={panelPath} workflow={workflow} />
        {closed ? (
          <p>
            <Link to={`/v2/reports/${workflow.month.id}`}>Состав капитала на эту дату</Link>
          </p>
        ) : null}
      </>
    ) : (
      <div className={styles.closeWorkspace} data-testid="v2-close-workspace">
        <MonthStepStrip
          checklist={workflow.checklist}
          closed={closed}
          current={panel}
          pathFor={panelPath}
        />
        {panel === "invalid" ? (
          <UiV2Notice title="Неизвестный раздел">
            <Link to={panelPath(null)}>← К месяцу</Link>
          </UiV2Notice>
        ) : panel ? (
          <section
            className={monthStyles.workArea}
            aria-label={`Рабочая область: ${panelLabel}`}
            id="month-work-area"
          >
            <header className={monthStyles.workHeader}>
              {panel !== "close" ? <h2>{panelLabel}</h2> : null}
              {panel !== "close" ? (
                <strong className={monthStyles.workTotal}>
                  {panel === "payouts" ? "Купоны и дивиденды: " : null}
                  {panel === "payouts" ||
                  panel === "budget" ||
                  panel === "positions" ||
                  panel === "brokers" ? (
                    <span id="month-panel-total" />
                  ) : panelStep ? (
                    closed && panelStep.figure?.kind === "money" ? (
                      <span title={moneyText(panelStep.figure.amount)}>
                        {moneyWholeText(panelStep.figure.amount, "—")}
                      </span>
                    ) : (
                      figureText(panelStep)
                    )
                  ) : (
                    "—"
                  )}
                </strong>
              ) : null}
              <Link to={panelPath(null)}>← К месяцу</Link>
            </header>
            {closed && panel !== "close" ? (
              <p className={monthStyles.viewOnly}>Месяц закрыт — только просмотр.</p>
            ) : null}
            {!closed &&
            panel === "positions" &&
            findings.some((item) => closeFindingPanel(item) === "positions") ? (
              <CloseFindings
                items={findings.filter((item) => closeFindingPanel(item) === "positions")}
                closed={false}
                pathFor={panelPath}
              />
            ) : null}
            {panel === "brokers" ? (
              <UiV2MonthSources
                key={`sources:${workflow.month.id}:${panel}:${discardVersion}`}
                month={workflow.month}
                step={workflow.checklist?.steps.find((step) => step.id === "brokers")}
                readinessRemarks={
                  workflow.final_review.available
                    ? workflow.final_review.close_readiness.items.filter((item) => {
                        const destination = closeFindingPanel(item);
                        return (
                          (item.severity === "warning" || item.severity === "hard_blocker") &&
                          item.code !== "empty_manual_month" &&
                          (destination === "brokers" ||
                            (!destination && !item.code.startsWith("salary")))
                        );
                      })
                    : []
                }
                canClose={workflowReady && workflow.readiness.can_close}
                onPendingChange={setUploadPending}
                onDirtyChange={setJournalDirty}
              />
            ) : null}
            {(MANUAL_SECTIONS as readonly string[]).includes(panel) ? (
              <UiV2MonthEditorPage
                key={`editor:${workflow.month.id}:${panel}:${discardVersion}`}
                embeddedMonthId={workflow.month.id}
                embeddedSection={panel as EditorSection}
                incompleteDraft={incomplete}
                onNavigationStateChange={setEditorNavigation}
              />
            ) : null}
            {panel === "payouts" ? (
              <PayoutForecastContainer className={monthStyles.closeDetails}>
                {closed ? (
                  <summary>Прогноз и календарь выплат</summary>
                ) : (
                  <h3>Прогноз и календарь выплат</h3>
                )}
                <MonthDraftPayouts
                  key={`draft-forecasts:${workflow.month.id}:${discardVersion}`}
                  monthId={workflow.month.id}
                  closed={closed}
                  disabled={
                    !workflowReady ||
                    sourceDirty ||
                    sourcePending ||
                    editorNavigation.dirty ||
                    editorNavigation.pending ||
                    lifecycleBusy ||
                    lifecycleRecovery ||
                    Boolean(pendingLifecycle)
                  }
                  sourceVersion={original.confirmed?.request_id}
                />
              </PayoutForecastContainer>
            ) : null}
            {panel === "close" ? (
              <>
                <div
                  className={monthStyles.closeStatus}
                  data-state={closed ? "closed" : blocked ? "blocked" : "ready"}
                >
                  <div>
                    <h2>
                      {closed
                        ? "Месяц закрыт"
                        : incomplete
                          ? INCOMPLETE_MONTH_COPY
                          : blocked
                            ? `Нужно исправить: ${workflow.readiness.hard_blocker_count}`
                            : findingCount
                              ? `Можно закрыть с замечаниями: ${findingCount}`
                              : "Можно закрывать"}
                    </h2>
                    {closed ? (
                      <>
                        <p>
                          Снимок{" "}
                          {workflow.month.snapshot_date
                            ? formatDate(workflow.month.snapshot_date)
                            : "не указан"}
                        </p>
                        {findingCount ? <p>Закрыт с замечаниями: {findingCount}</p> : null}
                      </>
                    ) : (
                      <>
                        {!incomplete ? <p>Закрытие не подтверждает полноту данных.</p> : null}
                        <MonthReadiness checklist={workflow.checklist} />
                      </>
                    )}
                  </div>
                  {!closed ? (
                    <Button
                      variant={incomplete ? "secondary" : "primary"}
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
                    </div>
                  )}
                </div>
                {blockers.length ? (
                  <section aria-label="Нужно исправить">
                    <CloseFindings items={blockers} closed={false} pathFor={panelPath} />
                  </section>
                ) : null}
                {!workflowReady ? <UiV2Loading label="Проверяем актуальное состояние…" /> : null}
                {workflowQuery.isError ? (
                  <UiV2Notice
                    title="Готовность не подтверждена"
                    retry={() => void workflowQuery.refetch()}
                  >
                    {formatApiError(workflowQuery.error)}
                  </UiV2Notice>
                ) : null}
                {workflow.final_review.available ? (
                  <>
                    <MonthKpis workflow={workflow} variant="close" />
                    {remaining.length ? (
                      closed ? (
                        <section className={monthStyles.closeRemarks} aria-label="Замечания месяца">
                          <p>Чтобы исправить, открой месяц заново.</p>
                          <details>
                            <summary>Замечания ({remaining.length})</summary>
                            <CloseFindings items={remaining} closed pathFor={panelPath} />
                          </details>
                        </section>
                      ) : (
                        <section
                          className={monthStyles.closeRemarks}
                          aria-labelledby="close-remaining-title"
                        >
                          <h3 id="close-remaining-title">Что осталось</h3>
                          <CloseFindings items={remaining} closed={false} pathFor={panelPath} />
                        </section>
                      )
                    ) : null}
                    <details className={monthStyles.closeDetails}>
                      <summary>Подробнее о проверках</summary>
                      <FinalMonthReview review={workflow.final_review} />
                    </details>
                  </>
                ) : workflowReady ? (
                  <UiV2Notice title="Итоги пока недоступны">
                    Проверь сохранённые данные месяца.
                  </UiV2Notice>
                ) : null}
                {selectionIdentityMatches && selectedMonth && finalReviewActive ? (
                  <IntentionalEmptyClose
                    key={`${selectedMonth.id}:${selectedMonth.snapshot_date}`}
                    month={selectedMonth}
                    onPendingChange={setEmptyClosePending}
                    available={false}
                  />
                ) : null}
                {closed && workflow.outlook ? (
                  <details className={monthStyles.closeDetails}>
                    <summary>Что известно о следующем месяце</summary>
                    <NextMonthOutlook outlook={workflow.outlook} />
                  </details>
                ) : null}
              </>
            ) : null}
          </section>
        ) : null}
      </div>
    );
  }
  return (
    <UiV2Shell
      busy={monthsQuery.isPending}
      showRefresh={false}
      header={
        <>
          <div className={overviewStyles.headingMeta}>
            <p className={styles.eyebrow}>Месяц</p>
            <Link className={overviewStyles.allMonths} to="/v2/data/months">
              Все месяцы →
            </Link>
          </div>
          <div className={overviewStyles.titleRow}>
            {selectedPeriod ? (
              <MonthStepper months={months} current={selectedPeriod.id} search={location.search} />
            ) : null}
            <h1>
              {selectedPeriod ? formatMonth(selectedPeriod.year, selectedPeriod.month) : "Месяц"}
            </h1>
            {workflowIdentityMatches ? (
              <MonthStatusChip month={workflow.month} />
            ) : selectedMonth && selectionIdentityMatches ? (
              <MonthStatusChip month={selectedMonth} />
            ) : null}
            <Button
              disabled={monthsQuery.isPending || fetching > 0}
              onClick={() => void queryClient.invalidateQueries()}
            >
              Обновить
            </Button>
            {closed ? (
              <OverflowMenu label="Действия месяца">
                {closed ? (
                  <OverflowMenuItem
                    aria-label="Открыть месяц заново"
                    disabled={lifecycleBusy || lifecycleRecovery}
                    onClick={requestReopen}
                  >
                    Открыть заново
                  </OverflowMenuItem>
                ) : null}
              </OverflowMenu>
            ) : null}
          </div>
        </>
      }
    >
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
          const withinMonth = destination?.split("?")[0] === "/v2/close";
          // External navigation unmounts the itself. Avoid an
          // intermediate remount that could retire the retained File first.
          if (!destination || withinMonth) setDiscardVersion((value) => value + 1);
          setEditorNavigation({ dirty: false, pending: false });
          if (sourceDirty && monthId !== null) {
            // Catalogue round-trips retain the actual File while retiring its
            // preview/decisions. An explicit Month-panel discard drops it.
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
            ? "Закрыть выбранный месяц с текущими данными? Замечания сохранятся. Для исправлений можно открыть месяц заново."
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
