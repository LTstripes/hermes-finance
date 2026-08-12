import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiClientError, formatApiError } from "../api/client";
import {
  createGoal,
  deleteGoal,
  listGoals,
  listGoalSummary,
  updateGoal,
  type Goal,
  type GoalCreatePayload,
  type GoalSummary,
  type GoalUpdatePayload,
} from "../api/goals";
import { listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { GoalFormDialog } from "../components/GoalFormDialog";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  HelpTip,
  LoadingState,
  OverflowMenu,
  OverflowMenuItem,
  Panel,
  Select,
} from "../components/ui";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../lib/format";
import {
  GOAL_STATUS_LABELS,
  GOAL_TYPE_LABELS,
  goalCalculationModeLabel,
  goalReasonLabel,
} from "../lib/goals";

const GOALS_API_MISSING_MESSAGE = "Раздел целей недоступен в текущей версии приложения.";

function newestMonth(rows: ReportingMonth[]): ReportingMonth | null {
  return (
    [...rows].sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year))[0] ?? null
  );
}

export function GoalsPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [summary, setSummary] = useState<GoalSummary[]>([]);
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [goalsLoading, setGoalsLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [goalsError, setGoalsError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingGoal, setEditingGoal] = useState<Goal | null>(null);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Goal | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadGoals = useCallback(async (signal?: AbortSignal) => {
    setGoalsLoading(true);
    setGoalsError(null);
    try {
      const rows = await listGoals(true, signal);
      if (!signal?.aborted) setGoals(rows);
    } catch (error) {
      if (!signal?.aborted) {
        setGoals([]);
        setGoalsError(
          error instanceof ApiClientError && error.status === 404
            ? GOALS_API_MISSING_MESSAGE
            : formatApiError(error),
        );
      }
    } finally {
      if (!signal?.aborted) setGoalsLoading(false);
    }
  }, []);

  const loadSummary = useCallback(async (monthId: number, signal?: AbortSignal) => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const rows = await listGoalSummary(monthId, { includeInactive: true }, signal);
      if (!signal?.aborted) setSummary(rows);
    } catch (error) {
      if (!signal?.aborted) {
        setSummary([]);
        setSummaryError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadGoals(controller.signal);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setMonths(rows);
        setSelectedMonthId((previous) => {
          if (previous != null && rows.some((row) => row.id === previous)) return previous;
          return newestMonth(rows)?.id ?? null;
        });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setSummaryError(formatApiError(error));
      });
    return () => controller.abort();
  }, [loadGoals]);

  useEffect(() => {
    if (selectedMonthId == null) {
      setSummary([]);
      return;
    }
    const controller = new AbortController();
    void loadSummary(selectedMonthId, controller.signal);
    return () => controller.abort();
  }, [loadSummary, selectedMonthId]);

  const summaryById = useMemo(
    () => new Map(summary.map((row) => [row.id, row] as const)),
    [summary],
  );
  const activeGoals = useMemo(
    () =>
      goals
        .filter((goal) => goal.is_active)
        .sort((a, b) => Number(b.is_main) - Number(a.is_main) || a.id - b.id),
    [goals],
  );
  const inactiveGoals = useMemo(
    () => goals.filter((goal) => !goal.is_active).sort((a, b) => a.id - b.id),
    [goals],
  );
  const selectedMonth = months.find((row) => row.id === selectedMonthId) ?? null;

  async function refresh() {
    await loadGoals();
    if (selectedMonthId != null) await loadSummary(selectedMonthId);
  }

  function openCreate() {
    setEditingGoal(null);
    setFormError(null);
    setDialogOpen(true);
  }

  function openEdit(goal: Goal) {
    setEditingGoal(goal);
    setFormError(null);
    setDialogOpen(true);
  }

  async function handleSubmit(payload: GoalCreatePayload | GoalUpdatePayload) {
    setFormBusy(true);
    setFormError(null);
    try {
      if (editingGoal) {
        await updateGoal(editingGoal.id, payload as GoalUpdatePayload);
      } else {
        await createGoal(payload as GoalCreatePayload);
      }
      setDialogOpen(false);
      setEditingGoal(null);
      await refresh();
    } catch (error) {
      setFormError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function patchGoal(goal: Goal, payload: GoalUpdatePayload) {
    setActionError(null);
    try {
      await updateGoal(goal.id, payload);
      await refresh();
    } catch (error) {
      setActionError(formatApiError(error));
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      await deleteGoal(pendingDelete.id);
      setPendingDelete(null);
      await refresh();
    } catch (error) {
      setPendingDelete(null);
      setActionError(formatApiError(error));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="goals-page goals-v03 stack-18">
      <header className="page-header">
        <p className="eyebrow">Планирование</p>
        <h1>Цели</h1>
        <p className="page-header__description">
          Текущий прогресс, оставшийся путь и одна главная цель — без широкой таблицы и служебного
          шума.
        </p>
      </header>

      <div className="toolbar goals-v03__toolbar">
        {months.length > 0 ? (
          <div className="field--inline">
            <Field htmlFor="goals-month" label="Оценка на месяц">
              <Select
                id="goals-month"
                onChange={(event) => setSelectedMonthId(Number(event.target.value))}
                value={selectedMonthId ?? ""}
              >
                {[...months]
                  .sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year))
                  .map((month) => (
                    <option key={month.id} value={month.id}>
                      {formatMonth(month.year, month.month)}
                    </option>
                  ))}
              </Select>
            </Field>
          </div>
        ) : null}
        <Button onClick={openCreate} variant="primary">
          Создать цель
        </Button>
        <Button
          disabled={goalsLoading || summaryLoading}
          onClick={() => void refresh()}
          variant="ghost"
        >
          Обновить
        </Button>
      </div>

      {selectedMonth ? (
        <p className="goals-v03__as-of muted tiny">
          Прогресс на снимок {formatDate(selectedMonth.snapshot_date)}.
        </p>
      ) : (
        <div className="inline-alert inline-alert--warn" role="status">
          Нет отчётного месяца: цели можно редактировать, но их финансовый прогресс пока нельзя
          показать.
        </div>
      )}

      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}
      {summaryError ? (
        <div className="inline-alert inline-alert--warn" role="status">
          Прогресс целей недоступен: {summaryError}
        </div>
      ) : null}

      <Panel label="Активные" title={`Цели (${activeGoals.length})`}>
        {goalsLoading ? (
          <LoadingState description="Загружаем цели…" inline />
        ) : goalsError ? (
          <div className="stack-8">
            <ErrorState description={goalsError} inline title="Не удалось загрузить цели" />
            {goalsError === GOALS_API_MISSING_MESSAGE ? (
              <details className="muted tiny">
                <summary>Технические подробности</summary>
                <span>API /api/goals отсутствует</span>
              </details>
            ) : null}
            <Button onClick={() => void loadGoals()} size="sm">
              Повторить
            </Button>
          </div>
        ) : goals.length === 0 ? (
          <EmptyState
            action={
              <Button onClick={openCreate} size="sm" variant="primary">
                Создать цель
              </Button>
            }
            description="Список целей пока пуст."
            inline
            title="Нет целей"
          />
        ) : activeGoals.length === 0 ? (
          <EmptyState
            description="Активных целей нет. Можно создать новую или вернуть цель из архива."
            inline
            title="Нет активных целей"
          />
        ) : (
          <div className="goal-card-grid" role="list">
            {activeGoals.map((goal) => (
              <GoalCard
                goal={goal}
                key={goal.id}
                onDelete={setPendingDelete}
                onEdit={openEdit}
                onPatch={patchGoal}
                summary={summaryLoading ? undefined : summaryById.get(goal.id)}
                summaryLoading={summaryLoading}
              />
            ))}
          </div>
        )}
      </Panel>

      {!goalsLoading && !goalsError && inactiveGoals.length > 0 ? (
        <details className="goals-archive">
          <summary>
            <span>Архив</span>
            <strong>{inactiveGoals.length}</strong>
          </summary>
          <div className="goal-card-grid goal-card-grid--archive" role="list">
            {inactiveGoals.map((goal) => (
              <GoalCard
                compact
                goal={goal}
                key={goal.id}
                onDelete={setPendingDelete}
                onEdit={openEdit}
                onPatch={patchGoal}
                summary={summaryLoading ? undefined : summaryById.get(goal.id)}
                summaryLoading={summaryLoading}
              />
            ))}
          </div>
        </details>
      ) : null}

      <GoalFormDialog
        busy={formBusy}
        error={formError}
        goal={editingGoal}
        onCancel={() => {
          if (!formBusy) {
            setDialogOpen(false);
            setEditingGoal(null);
          }
        }}
        onSubmit={handleSubmit}
        open={dialogOpen}
      />

      <ConfirmDialog
        busy={deleting}
        confirmLabel="Удалить"
        danger
        description={
          pendingDelete
            ? `Цель «${pendingDelete.name}» будет удалена безвозвратно.`
            : "Цель будет удалена."
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
        open={pendingDelete != null}
        title="Удалить цель?"
      />
    </section>
  );
}

type GoalCardProps = {
  goal: Goal;
  summary: GoalSummary | undefined;
  summaryLoading: boolean;
  compact?: boolean;
  onEdit: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
  onPatch: (goal: Goal, payload: GoalUpdatePayload) => Promise<void>;
};

function GoalCard({
  goal,
  summary,
  summaryLoading,
  compact = false,
  onEdit,
  onDelete,
  onPatch,
}: GoalCardProps) {
  const forecast = summary?.achievement_forecast;
  const hasOverflowActions = !goal.is_main;

  return (
    <article
      className={`goal-card${goal.is_main ? " goal-card--main" : ""}${
        compact ? " goal-card--compact" : ""
      }`}
      role="listitem"
    >
      <header className="goal-card__header">
        <div className="goal-card__identity">
          <div className="goal-card__badges">
            {goal.is_main ? <Badge tone="info">Основная</Badge> : null}
            <Badge tone={goal.is_active ? "ok" : "closed"}>
              {goal.is_active ? "Активна" : "Неактивна"}
            </Badge>
          </div>
          <h3>{goal.name}</h3>
          <span className="goal-card__type">
            {GOAL_TYPE_LABELS[goal.goal_type] ?? "Другая цель"}
            {goal.target_date ? ` · срок ${formatDate(goal.target_date)}` : ""}
          </span>
        </div>

        <div className="goal-card__actions">
          <Button onClick={() => onEdit(goal)} size="sm" variant="secondary">
            Изменить
          </Button>
          {hasOverflowActions ? (
            <OverflowMenu label={`Действия для цели «${goal.name}»`}>
              {goal.goal_type === "passive_income" && goal.is_active ? (
                <OverflowMenuItem onClick={() => void onPatch(goal, { is_main: true })}>
                  Сделать основной
                </OverflowMenuItem>
              ) : null}
              <OverflowMenuItem
                onClick={() => void onPatch(goal, { is_active: !goal.is_active })}
              >
                {goal.is_active ? "Деактивировать" : "Активировать"}
              </OverflowMenuItem>
              <OverflowMenuItem danger onClick={() => onDelete(goal)}>
                Удалить
              </OverflowMenuItem>
            </OverflowMenu>
          ) : null}
        </div>
      </header>

      {compact ? (
        <div className="goal-card__compact-value">
          <span>Цель</span>
          <strong>{formatMoney(goal.target_value.amount)}</strong>
        </div>
      ) : (
        <GoalMetrics goal={goal} forecast={forecast} loading={summaryLoading} />
      )}

      {!compact ? <GoalForecast forecast={forecast} goal={goal} loading={summaryLoading} /> : null}

      <GoalDetails forecast={forecast} goal={goal} />
    </article>
  );
}

function GoalMetrics({
  goal,
  forecast,
  loading,
}: {
  goal: Goal;
  forecast: GoalSummary["achievement_forecast"] | undefined;
  loading: boolean;
}) {
  const progress = !loading ? forecast?.progress_pct ?? null : null;
  const current = !loading ? forecast?.current_value?.amount ?? null : null;
  const remaining = !loading ? forecast?.remaining_amount?.amount ?? null : null;

  return (
    <div className="goal-card__metrics">
      <div className="goal-card__progress-row">
        <span>Прогресс</span>
        <strong>{loading ? "…" : progress ? formatPercent(progress, { digits: 1 }) : "—"}</strong>
      </div>
      <progress
        aria-label={`Прогресс цели «${goal.name}»`}
        className="goal-card__progress"
        max={100}
        value={progress ?? 0}
      />
      <div className="goal-card__values">
        <DataValue label="Сейчас" value={loading ? "…" : current ? formatMoney(current) : "—"} />
        <DataValue label="Цель" value={formatMoney(goal.target_value.amount)} />
        <DataValue
          label="Осталось"
          value={loading ? "…" : remaining ? formatMoney(remaining) : "—"}
        />
      </div>
    </div>
  );
}

function GoalForecast({
  forecast,
  goal,
  loading,
}: {
  forecast: GoalSummary["achievement_forecast"] | undefined;
  goal: Goal;
  loading: boolean;
}) {
  if (loading) return <span className="goal-card__forecast muted">Прогноз загружается…</span>;
  if (!forecast) return null;

  const help = forecastHelp(forecast);

  if (forecast.estimated_achievement_date) {
    return (
      <div className="goal-card__forecast">
        <span>{forecast.status === "achieved" ? "Достигнута" : "Прогноз достижения"}</span>
        <strong>{formatDate(forecast.estimated_achievement_date)}</strong>
        {help ? (
          <HelpTip label={`Подробности прогноза цели «${goal.name}»`} align="start">
            {help}
          </HelpTip>
        ) : null}
      </div>
    );
  }

  if (forecast.status === "inactive") return null;

  return (
    <div className="goal-card__forecast goal-card__forecast--muted">
      <span>Прогноз даты пока недоступен</span>
      {help ? (
        <HelpTip label={`Почему нет прогноза даты для цели «${goal.name}»`} align="start">
          {help}
        </HelpTip>
      ) : null}
    </div>
  );
}

function GoalDetails({
  forecast,
  goal,
}: {
  forecast: GoalSummary["achievement_forecast"] | undefined;
  goal: Goal;
}) {
  return (
    <details className="goal-card__details">
      <summary>Подробнее</summary>
      <div className="goal-card__details-body">
        <div>
          <span>Способ расчёта</span>
          <strong>{goalCalculationModeLabel(goal.calculation_mode)}</strong>
        </div>
        {forecast ? (
          <div>
            <span>Статус расчёта</span>
            <strong>{GOAL_STATUS_LABELS[forecast.status] ?? "Статус недоступен"}</strong>
          </div>
        ) : null}
        {goal.notes ? (
          <div>
            <span>Заметка</span>
            <strong>{goal.notes}</strong>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function forecastHelp(forecast: GoalSummary["achievement_forecast"]): string {
  const parts: string[] = [];
  if (forecast.reason_code) parts.push(goalReasonLabel(forecast.reason_code));
  parts.push(...forecast.warnings);
  if (forecast.is_approximate) parts.push("Часть значений является оценочной.");
  if (forecast.as_of_date) parts.push(`Данные на ${formatDate(forecast.as_of_date)}.`);
  return parts.join(" ");
}
