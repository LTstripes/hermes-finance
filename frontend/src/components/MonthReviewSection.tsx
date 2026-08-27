import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listGoalSummary, type GoalSummary } from "../api/goals";
import { closeMonth, getCloseReadiness, reopenMonth } from "../api/months";
import type { CloseReadiness, CloseReadinessItem, DashboardKpis } from "../api/types";
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

const GROUP_META: {
  severity: CloseReadinessItem["severity"];
  title: string;
  empty: string;
  tone: "closed" | "draft" | "info";
}[] = [
  {
    severity: "hard_blocker",
    title: "Блокирует закрытие",
    empty: "Нет причин, из-за которых сервер отклонит закрытие.",
    tone: "closed",
  },
  {
    severity: "warning",
    title: "Стоит проверить",
    empty: "Предупреждений нет.",
    tone: "draft",
  },
  {
    severity: "info",
    title: "Контекст",
    empty: "Дополнительного контекста нет.",
    tone: "info",
  },
];

function itemsFor(
  readiness: CloseReadiness | null,
  severity: CloseReadinessItem["severity"],
): CloseReadinessItem[] {
  return (readiness?.items ?? []).filter((item) => item.severity === severity);
}

export function MonthReviewSection({ dirty, monthId, readOnly, status, onStatusChanged }: Props) {
  const [previewKpis, setPreviewKpis] = useState<DashboardKpis | null>(null);
  const [readiness, setReadiness] = useState<CloseReadiness | null>(null);
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
        const [dashboard, goals, closeReadiness] = await Promise.all([
          getDashboard(monthId, signal).catch(() => null),
          listGoalSummary(monthId, {}, signal).catch(() => []),
          getCloseReadiness(monthId, signal),
        ]);
        if (signal?.aborted) return;
        setPreviewKpis(dashboard?.kpis ?? null);
        setMainGoal(goals.find((goal) => goal.is_main) ?? null);
        setReadiness(closeReadiness);
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

  const blockers = useMemo(() => itemsFor(readiness, "hard_blocker"), [readiness]);
  const warnings = useMemo(() => itemsFor(readiness, "warning"), [readiness]);
  const infos = useMemo(() => itemsFor(readiness, "info"), [readiness]);
  const closeBlocked = readiness == null || !readiness.can_close;
  const closeDisabled = busy || readOnly || dirty || closeBlocked || status !== "draft";

  async function confirmAction() {
    if (!pendingAction) return;
    if (pendingAction === "close" && closeDisabled) return;
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

  const closeDescription =
    warnings.length > 0
      ? "Есть предупреждения, но они не блокируют закрытие. Закрыть месяц? Данные будут зафиксированы до явного повторного открытия."
      : "Закрыть месяц? Данные будут зафиксированы до явного повторного открытия.";

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

        <div className="close-cockpit" data-testid="close-cockpit">
          {GROUP_META.map((group) => {
            const grouped = { hard_blocker: blockers, warning: warnings, info: infos };
            const items = grouped[group.severity];
            return (
              <section
                aria-label={group.title}
                className={`close-cockpit__group close-cockpit__group--${group.severity}`}
                key={group.severity}
              >
                <div className="close-cockpit__group-heading">
                  <h3>{group.title}</h3>
                  <Badge tone={group.tone}>{items.length}</Badge>
                </div>
                {group.severity === "warning" ? (
                  <p className="muted close-cockpit__hint">
                    Предупреждения не блокируют закрытие. Их стоит посмотреть до финального шага.
                  </p>
                ) : null}
                {group.severity === "hard_blocker" ? (
                  <p className="muted close-cockpit__hint">
                    Кнопка «Закрыть месяц» отключается только этими пунктами — тем, что сервер и так
                    отклонит.
                  </p>
                ) : null}
                {items.length === 0 ? (
                  <p className="muted">{group.empty}</p>
                ) : (
                  <ul className="close-cockpit__items">
                    {items.map((item) => (
                      <li key={`${item.severity}:${item.code}:${item.message}`}>
                        <span className="close-cockpit__code">{item.code}</span>
                        <span>{item.message}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>

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
            disabled={closeDisabled}
            onClick={() => setPendingAction("close")}
            title={
              dirty
                ? "Сначала сохрани изменения"
                : closeBlocked
                  ? "Закрытие сейчас отклонит сервер"
                  : undefined
            }
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
            ? closeDescription
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
