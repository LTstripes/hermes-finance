import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { listGoalSummary, type GoalSummary } from "../api/goals";
import { formatDate, formatMoney, formatPercent } from "../lib/format";
import { goalReasonLabel } from "../lib/goals";
import { Badge, Button, HelpTip } from "./ui";

type MainGoalPanelProps = {
  reportingMonthId: number | null;
  fallbackProgressPct?: string | null;
  fallbackTargetAmount?: string | null;
};

export function MainGoalPanel({
  reportingMonthId,
  fallbackProgressPct = null,
  fallbackTargetAmount = null,
}: MainGoalPanelProps) {
  const [mainGoal, setMainGoal] = useState<GoalSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (monthId: number, signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listGoalSummary(monthId, {}, signal);
      if (!signal?.aborted) setMainGoal(rows.find((goal) => goal.is_main) ?? null);
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
    <article className="overview-card overview-card--goal">
      <div className="overview-card__heading">
        <div className="overview-card__label">Основная цель</div>
        <Link className="overview-card__link" to="/goals">
          Цели →
        </Link>
      </div>

      {reportingMonthId == null ? (
        <GoalFallback
          message="Выбери отчётный месяц"
          progressPct={fallbackProgressPct}
          targetAmount={fallbackTargetAmount}
        />
      ) : mainGoal ? (
        <MainGoalBody goal={mainGoal} />
      ) : loading ? (
        <GoalFallback
          message="Загружаем детали цели…"
          progressPct={fallbackProgressPct}
          targetAmount={fallbackTargetAmount}
        />
      ) : error ? (
        <div className="overview-card__goal-state">
          <GoalFallback
            message="Подробности цели временно недоступны"
            progressPct={fallbackProgressPct}
            targetAmount={fallbackTargetAmount}
          />
          <Button
            onClick={() => void load(reportingMonthId)}
            size="sm"
            type="button"
            variant="secondary"
          >
            Повторить
          </Button>
        </div>
      ) : (
        <div className="overview-card__goal-state">
          <strong>Основная цель не выбрана</strong>
          <span className="overview-card__context">Выбери её в разделе «Цели».</span>
        </div>
      )}
    </article>
  );
}

function GoalFallback({
  progressPct,
  targetAmount,
  message,
}: {
  progressPct: string | null;
  targetAmount: string | null;
  message: string;
}) {
  return (
    <div className="overview-card__goal-state">
      <div className="overview-card__metric-label">Прогресс цели</div>
      <div className="overview-card__value">
        {progressPct ? formatPercent(progressPct, { digits: 1 }) : "…"}
      </div>
      {targetAmount ? (
        <div className="overview-card__supporting">
          <span>Цель</span>
          <strong>{formatMoney(targetAmount)}</strong>
        </div>
      ) : null}
      <span className="overview-card__context">{message}</span>
    </div>
  );
}

function MainGoalBody({ goal }: { goal: GoalSummary }) {
  const forecast = goal.achievement_forecast;
  const help = goalHelpText(goal);

  return (
    <div className="overview-card__goal-state">
      <div className="overview-card__goal-name">
        <strong>{goal.name}</strong>
        <Badge tone="info">Основная</Badge>
      </div>

      <div className="overview-card__metric-label">Прогресс цели</div>
      <div className="overview-card__value">
        {formatPercent(forecast.progress_pct, { digits: 1 })}
      </div>

      <div className="overview-card__goal-values">
        <div>
          <span>Сейчас</span>
          <strong>{formatMoney(forecast.current_value?.amount)}</strong>
        </div>
        <div>
          <span>Цель</span>
          <strong>{formatMoney(forecast.target_value.amount)}</strong>
        </div>
        <div>
          <span>Осталось</span>
          <strong>{formatMoney(forecast.remaining_amount?.amount)}</strong>
        </div>
      </div>

      <div className="overview-card__goal-forecast">
        <span>{goalForecastLabel(goal)}</span>
        {help ? (
          <HelpTip label="Почему прогноз цели выглядит так" align="start">
            {help}
          </HelpTip>
        ) : null}
      </div>
    </div>
  );
}

function goalForecastLabel(goal: GoalSummary): string {
  const forecast = goal.achievement_forecast;
  if (forecast.estimated_achievement_date) {
    return `Достигнута ${formatDate(forecast.estimated_achievement_date)}`;
  }
  if (forecast.status === "inactive") return "Цель не отслеживается";
  if (forecast.status === "unsupported") return "Прогноз даты недоступен";
  if (forecast.status === "not_projectable") return "Прогноз даты недоступен";
  return "Дата достижения —";
}

function goalHelpText(goal: GoalSummary): string {
  const forecast = goal.achievement_forecast;
  const parts: string[] = [];
  if (forecast.reason_code) parts.push(goalReasonLabel(forecast.reason_code));
  parts.push(...forecast.warnings);
  if (forecast.is_approximate) parts.push("Часть значений является оценочной.");
  if (forecast.as_of_date) parts.push(`Данные на ${formatDate(forecast.as_of_date)}.`);
  return parts.join(" ");
}
