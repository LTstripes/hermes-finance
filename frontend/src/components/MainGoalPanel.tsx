import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { listGoalSummary, type GoalSummary } from "../api/goals";
import { formatApiError } from "../api/client";
import { formatDate, formatMoney, formatPercent } from "../lib/format";
import { GOAL_STATUS_LABELS, GOAL_TYPE_LABELS } from "../lib/goals";
import { Badge, Button, EmptyState, ErrorState, LoadingState, Panel } from "./ui";

function statusTone(status: string): "ok" | "info" | "closed" | "neutral" {
  if (status === "achieved") return "ok";
  if (status === "not_projectable") return "info";
  if (status === "inactive") return "closed";
  return "neutral";
}

export function MainGoalPanel({ reportingMonthId }: { reportingMonthId: number | null }) {
  const [mainGoal, setMainGoal] = useState<GoalSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (monthId: number, signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listGoalSummary(monthId, {}, signal);
      if (!signal?.aborted) {
        setMainGoal(rows.find((goal) => goal.is_main) ?? null);
      }
    } catch (loadError) {
      if (!signal?.aborted) {
        setMainGoal(null);
        setError(formatApiError(loadError));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (reportingMonthId == null) {
      setMainGoal(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    void load(reportingMonthId, controller.signal);
    return () => controller.abort();
  }, [load, reportingMonthId]);

  return (
    <Panel action={<Link to="/goals">Открыть цели →</Link>} label="Цель" title="Основная цель">
      {reportingMonthId == null ? (
        <EmptyState description="Выбери отчётный месяц." inline title="Нет месяца" />
      ) : loading ? (
        <LoadingState description="Загружаем прогресс основной цели…" inline />
      ) : error ? (
        <div className="stack-8">
          <ErrorState description={error} inline title="Не удалось загрузить цель" />
          <Button onClick={() => void load(reportingMonthId)} size="sm">
            Повторить
          </Button>
        </div>
      ) : !mainGoal ? (
        <EmptyState
          description="Основная цель не выбрана. Открой раздел «Цели» и выбери активную цель пассивного дохода."
          inline
          title="Нет основной цели"
        />
      ) : (
        <MainGoalBody goal={mainGoal} />
      )}
    </Panel>
  );
}

function MainGoalBody({ goal }: { goal: GoalSummary }) {
  const forecast = goal.achievement_forecast;
  return (
    <div className="stack-18">
      <div className="stack-8">
        <div className="row-actions">
          <strong>{goal.name}</strong>
          <Badge tone="info">Основная</Badge>
          <Badge tone={statusTone(forecast.status)}>
            {GOAL_STATUS_LABELS[forecast.status] ?? forecast.status}
          </Badge>
        </div>
        <span className="muted tiny">
          {GOAL_TYPE_LABELS[goal.goal_type] ?? goal.goal_type}
          {goal.target_date ? ` · срок ${formatDate(goal.target_date)}` : ""}
        </span>
      </div>

      <div className="form-row-2">
        <div className="field">
          <span className="field__label">Текущее значение</span>
          <strong>{formatMoney(forecast.current_value?.amount)}</strong>
        </div>
        <div className="field">
          <span className="field__label">Цель</span>
          <strong>{formatMoney(forecast.target_value.amount)}</strong>
        </div>
        <div className="field">
          <span className="field__label">Прогресс</span>
          <strong>{formatPercent(forecast.progress_pct, { digits: 2 })}</strong>
        </div>
        <div className="field">
          <span className="field__label">Осталось</span>
          <strong>{formatMoney(forecast.remaining_amount?.amount)}</strong>
        </div>
      </div>

      <div className="stack-8">
        <strong>
          {forecast.estimated_achievement_date
            ? `Цель достигнута на снимке ${formatDate(forecast.estimated_achievement_date)}`
            : forecast.status === "not_projectable"
              ? "Дата достижения: нет честного прогноза"
              : forecast.status === "unsupported"
                ? "Дата достижения: расчёт не поддерживается"
                : forecast.status === "inactive"
                  ? "Цель не отслеживается"
                  : "Дата достижения: —"}
        </strong>
        {forecast.reason_code ? (
          <span className="muted tiny">Причина: {forecast.reason_code}</span>
        ) : null}
        {forecast.warnings.length > 0 ? (
          <div className="inline-alert inline-alert--warn" role="status">
            {forecast.warnings.join(" · ")}
          </div>
        ) : null}
        <span className="muted tiny">
          Значения рассчитаны backend на {formatDate(forecast.as_of_date)} · {forecast.method_version}
          {forecast.source_forecast_version ? ` · forecast ${forecast.source_forecast_version}` : ""}
        </span>
      </div>
    </div>
  );
}
