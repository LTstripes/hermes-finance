import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listGoalSummary, type GoalSummary } from "../api/goals";
import { closeMonth, reopenMonth } from "../api/months";
import type { DashboardKpis } from "../api/types";
import { formatMoney, formatPercent } from "../lib/format";
import { moneyAmount } from "../lib/money";
import { Badge, Button, ConfirmDialog, ErrorState, LoadingState, Panel } from "./ui";

type Props = {
  dirty: boolean;
  monthId: number;
  readOnly: boolean;
  status: "draft" | "closed";
  onStatusChanged: () => void;
};

export function MonthReviewSection({ dirty, monthId, readOnly, status, onStatusChanged }: Props) {
  const [previewKpis, setPreviewKpis] = useState<DashboardKpis | null>(null);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [mainGoal, setMainGoal] = useState<GoalSummary | null>(null);
  const [pendingAction, setPendingAction] = useState<"close" | "reopen" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [dashboard, goals] = await Promise.all([
          getDashboard(monthId, signal).catch(() => null),
          listGoalSummary(monthId, {}, signal).catch(() => []),
        ]);
        if (signal?.aborted) return;
        setPreviewKpis(dashboard?.kpis ?? null);
        setPreviewWarnings(dashboard?.warnings ?? []);
        setMainGoal(goals.find((goal) => goal.is_main) ?? null);
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [monthId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function confirmAction() {
    if (!pendingAction) return;
    setBusy(true);
    setActionError(null);
    try {
      if (pendingAction === "close") await closeMonth(monthId);
      else await reopenMonth(monthId);
      setPendingAction(null);
      onStatusChanged();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Готовим проверку месяца…" inline />;
  if (error) return <ErrorState description={error} inline title="Не удалось проверить месяц" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}
      <Panel
        action={
          status === "closed" ? (
            <Badge tone="closed">Закрыт</Badge>
          ) : (
            <Badge tone="draft">Черновик</Badge>
          )
        }
        label="Перед закрытием"
        title="Проверка месяца"
      >
        {previewKpis ? (
          <div className="totals-bar">
            <span>
              Ликвидный капитал:{" "}
              <strong>{formatMoney(moneyAmount(previewKpis.liquid_capital_net))}</strong>
            </span>
            <span>
              Средний пассивный доход:{" "}
              <strong>{formatMoney(moneyAmount(previewKpis.passive_income_average))}</strong>
            </span>
            <span>
              Прогноз:{" "}
              <strong>
                {formatMoney(moneyAmount(previewKpis.forecast_monthly_passive_income))}
              </strong>
            </span>
            <span>
              Прогресс цели:{" "}
              <strong>
                {previewKpis.goal_progress_pct != null ? `${previewKpis.goal_progress_pct}%` : "—"}
              </strong>
            </span>
          </div>
        ) : (
          <p className="muted">Краткие показатели временно недоступны.</p>
        )}

        {previewWarnings.length === 0 ? (
          <div className="inline-alert inline-alert--ok" role="status">
            Существенных предупреждений нет. Месяц можно закрыть после финальной проверки данных.
          </div>
        ) : (
          <div className="inline-alert inline-alert--warn" role="status">
            Есть детали, которые стоит проверить перед закрытием.
            <details className="field-details">
              <summary>Показать предупреждения ({previewWarnings.length})</summary>
              <ul className="closeout-warnings">
                {previewWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          </div>
        )}

        {status === "closed" ? (
          <p className="muted">
            Месяц закрыт — данные зафиксированы до явного повторного открытия.
          </p>
        ) : (
          <p className="muted">
            Закрытие фиксирует состояние месяца. При необходимости его можно открыть заново.
          </p>
        )}
        {status === "closed" ? (
          <Button disabled={busy} onClick={() => setPendingAction("reopen")} type="button">
            Открыть заново
          </Button>
        ) : (
          <Button
            disabled={busy || readOnly || dirty}
            onClick={() => setPendingAction("close")}
            title={dirty ? "Сначала сохрани изменения" : undefined}
            type="button"
            variant="primary"
          >
            Закрыть месяц
          </Button>
        )}
      </Panel>

      <Panel action={<Link to="/goals">Открыть цели →</Link>} label="Сводка" title="Основная цель">
        {mainGoal ? (
          <div className="totals-bar">
            <span>
              {mainGoal.name}:{" "}
              <strong>
                {formatPercent(mainGoal.achievement_forecast.progress_pct, { digits: 1 })}
              </strong>
            </span>
            <span>
              Сейчас:{" "}
              <strong>
                {formatMoney(moneyAmount(mainGoal.achievement_forecast.current_value))}
              </strong>
            </span>
            <span>
              Цель:{" "}
              <strong>
                {formatMoney(moneyAmount(mainGoal.achievement_forecast.target_value))}
              </strong>
            </span>
          </div>
        ) : (
          <p className="muted">Основная цель не выбрана. Подробности доступны в разделе «Цели».</p>
        )}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel={pendingAction === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingAction === "close"}
        description={
          pendingAction === "close"
            ? "Закрыть месяц? Данные будут зафиксированы до явного повторного открытия."
            : "Открыть месяц заново? Данные снова станут редактируемыми."
        }
        onCancel={() => setPendingAction(null)}
        onConfirm={() => void confirmAction()}
        open={pendingAction !== null}
        title={pendingAction === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />
    </div>
  );
}
