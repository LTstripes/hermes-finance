import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  useBrokerOriginalContext,
  useBrokerOriginalSession,
} from "../components/month-close/brokerOriginalSession";
import {
  FinalMonthReview,
  MonthCompletionSummary,
} from "../components/month-close/FinalMonthReview";
import { IntentionalEmptyClose } from "../components/month-close/IntentionalEmptyClose";
import { NextMonthOutlook } from "../components/month-close/NextMonthOutlook";
import { closeOwnerCopy } from "../components/month-close/ownerCopy";
import { useSourceIntakeRecovery } from "../components/month-close/SourceIntakeJournal";
import {
  type AlfaStatementTransientOutcome,
  parseAlfaStatementTransientOutcome,
} from "../components/month-close/statementOutcome";
import { useMonthCloseLifecycle } from "../components/month-close/useMonthCloseLifecycle";
import { Button, ConfirmDialog, MoneyAmount } from "../components/ui";
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
import { MONTH_STEP_COPY, MonthOverview, MonthStepStrip } from "./UiV2MonthOverview";
import overviewStyles from "./UiV2MonthOverview.module.css";
import { UiV2MonthSources } from "./UiV2MonthSources";
import monthStyles from "./UiV2MonthWorkspace.module.css";
import styles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

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
    const panelLabel =
      panel && panel in MONTH_STEP_COPY
        ? MONTH_STEP_COPY[panel as keyof typeof MONTH_STEP_COPY].label
        : undefined;
    content = !panel ? (
      <MonthOverview pathFor={panelPath} workflow={workflow} />
    ) : (
      <div className={styles.closeWorkspace} data-testid="v2-close-workspace">
        <MonthStepStrip checklist={workflow.checklist} current={panel} pathFor={panelPath} />
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
              <h2>{panelLabel}</h2>
              <Link to={panelPath(null)}>← К месяцу</Link>
            </header>
            {panel === "payouts" ? (
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
            ) : null}
            {panel === "brokers" ? (
              <UiV2MonthSources
                key={`sources:${workflow.month.id}:${panel}:${discardVersion}`}
                month={workflow.month}
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
                onNavigationStateChange={setEditorNavigation}
              />
            ) : null}
            {panel === "close" ? (
              <>
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
                        ? "Месяц закрыт по вашему решению. Замечания сохранены."
                        : "Можно закрыть с предупреждениями. Закрытие не подтверждает полноту данных."}
                    </p>
                    {workflow.final_review.close_readiness.items
                      .filter(
                        (item) => item.severity === "hard_blocker" || item.severity === "warning",
                      )
                      .map((item) => (
                        <p role="status" key={`${item.code}:${item.message}`}>
                          {closeOwnerCopy(item.message)}
                        </p>
                      ))}
                    <details>
                      <summary>Подробнее об итогах и проверках</summary>
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
                  <details>
                    <summary>Что известно о следующем месяце</summary>
                    <NextMonthOutlook outlook={workflow.outlook} />
                  </details>
                ) : null}
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
            <Link className={overviewStyles.allMonths} to="/v2/data/months">
              Отчётные месяцы →
            </Link>
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
