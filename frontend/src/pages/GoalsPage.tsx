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
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
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

function forecastTone(status: string): "ok" | "info" | "closed" | "neutral" {
  if (status === "achieved") return "ok";
  if (status === "not_projectable") return "info";
  if (status === "inactive") return "closed";
  return "neutral";
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
  const activeGoals = useMemo(() => goals.filter((goal) => goal.is_active), [goals]);
  const inactiveGoals = useMemo(() => goals.filter((goal) => !goal.is_active), [goals]);
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
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Планирование</p>
        <h1>Цели</h1>
        <p className="page-header__description">
          Здесь можно вести финансовые цели и смотреть их прогресс по выбранному отчётному месяцу.
          Все финансовые показатели рассчитываются автоматически.
        </p>
      </header>

      <div className="toolbar">
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
        <Button disabled={goalsLoading || summaryLoading} onClick={() => void refresh()}>
          Обновить
        </Button>
      </div>

      {selectedMonth ? (
        <p className="muted tiny">
          Прогресс рассчитан на снимок {formatDate(selectedMonth.snapshot_date)}.
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

      <Panel label="Основные" title={`Активные цели (${activeGoals.length})`}>
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
        ) : (
          <GoalTable
            goals={activeGoals}
            onDelete={setPendingDelete}
            onEdit={openEdit}
            onPatch={patchGoal}
            summaryById={summaryById}
            summaryLoading={summaryLoading}
          />
        )}
      </Panel>

      <Panel label="Архив" title={`Неактивные цели (${inactiveGoals.length})`}>
        {goalsLoading ? (
          <LoadingState description="Загружаем цели…" inline />
        ) : goalsError ? (
          <p className="muted">Архив недоступен, пока список целей не загружен.</p>
        ) : (
          <GoalTable
            goals={inactiveGoals}
            onDelete={setPendingDelete}
            onEdit={openEdit}
            onPatch={patchGoal}
            summaryById={summaryById}
            summaryLoading={summaryLoading}
          />
        )}
      </Panel>

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

type GoalTableProps = {
  goals: Goal[];
  summaryById: Map<number, GoalSummary>;
  summaryLoading: boolean;
  onEdit: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
  onPatch: (goal: Goal, payload: GoalUpdatePayload) => Promise<void>;
};

function GoalTable({
  goals,
  summaryById,
  summaryLoading,
  onEdit,
  onDelete,
  onPatch,
}: GoalTableProps) {
  if (goals.length === 0) return <p className="muted">Нет целей в этой группе.</p>;

  return (
    <Table>
      <thead>
        <tr>
          <Th>Цель</Th>
          <Th>Тип</Th>
          <Th>Целевое значение</Th>
          <Th>Прогресс</Th>
          <Th>Дата достижения</Th>
          <Th>Действия</Th>
        </tr>
      </thead>
      <tbody>
        {goals.map((goal) => {
          const summary = summaryById.get(goal.id);
          const forecast = summary?.achievement_forecast;
          return (
            <tr key={goal.id}>
              <Td>
                <div className="stack-8">
                  <strong>{goal.name}</strong>
                  <div className="row-actions">
                    {goal.is_main ? <Badge tone="info">Основная</Badge> : null}
                    <Badge tone={goal.is_active ? "ok" : "closed"}>
                      {goal.is_active ? "Активна" : "Неактивна"}
                    </Badge>
                  </div>
                  {goal.target_date ? (
                    <span className="muted tiny">Срок: {formatDate(goal.target_date)}</span>
                  ) : null}
                  <span className="muted tiny">
                    Способ расчёта: {goalCalculationModeLabel(goal.calculation_mode)}
                  </span>
                </div>
              </Td>
              <Td>{GOAL_TYPE_LABELS[goal.goal_type] ?? "Другая цель"}</Td>
              <Td>{formatMoney(goal.target_value.amount)}</Td>
              <Td>
                <GoalProgress forecast={forecast} loading={summaryLoading} />
              </Td>
              <Td>
                <AchievementDate forecast={forecast} />
              </Td>
              <Td>
                <div className="row-actions">
                  <Button onClick={() => onEdit(goal)} size="sm">
                    Изменить
                  </Button>
                  {goal.goal_type === "passive_income" && goal.is_active && !goal.is_main ? (
                    <Button
                      onClick={() => void onPatch(goal, { is_main: true })}
                      size="sm"
                      variant="primary"
                    >
                      Сделать основной
                    </Button>
                  ) : null}
                  {!goal.is_main ? (
                    <Button
                      onClick={() => void onPatch(goal, { is_active: !goal.is_active })}
                      size="sm"
                    >
                      {goal.is_active ? "Деактивировать" : "Активировать"}
                    </Button>
                  ) : null}
                  {!goal.is_main ? (
                    <Button onClick={() => onDelete(goal)} size="sm" variant="danger">
                      Удалить
                    </Button>
                  ) : null}
                </div>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function GoalProgress({
  forecast,
  loading,
}: {
  forecast: GoalSummary["achievement_forecast"] | undefined;
  loading: boolean;
}) {
  if (!forecast) return <span className="muted">{loading ? "Загрузка…" : "—"}</span>;
  return (
    <div className="stack-8">
      <Badge tone={forecastTone(forecast.status)}>
        {GOAL_STATUS_LABELS[forecast.status] ?? "Статус недоступен"}
      </Badge>
      {forecast.current_value ? (
        <span>
          Сейчас: <strong>{formatMoney(forecast.current_value.amount)}</strong>
        </span>
      ) : null}
      {forecast.progress_pct != null ? (
        <span>Прогресс: {formatPercent(forecast.progress_pct, { digits: 2 })}</span>
      ) : null}
      {forecast.remaining_amount ? (
        <span className="muted tiny">
          Осталось: {formatMoney(forecast.remaining_amount.amount)}
        </span>
      ) : null}
    </div>
  );
}

function AchievementDate({
  forecast,
}: {
  forecast: GoalSummary["achievement_forecast"] | undefined;
}) {
  if (!forecast) return <span className="muted">—</span>;
  const message = forecast.estimated_achievement_date
    ? `Достигнута на ${formatDate(forecast.estimated_achievement_date)}`
    : forecast.status === "not_projectable"
      ? "Пока нельзя надёжно спрогнозировать дату"
      : forecast.status === "unsupported"
        ? "Расчёт пока не поддерживается"
        : forecast.status === "inactive"
          ? "Не отслеживается"
          : "—";
  return (
    <div className="stack-8">
      <strong>{message}</strong>
      {forecast.reason_code ? (
        <span className="muted tiny">{goalReasonLabel(forecast.reason_code)}</span>
      ) : null}
      {forecast.warnings.length > 0 ? (
        <span className="muted tiny">{forecast.warnings.join(" · ")}</span>
      ) : null}
    </div>
  );
}
