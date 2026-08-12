import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import type { DashboardKpis, DashboardSlice, ReportingMonth } from "../api/types";
import { MainGoalPanel } from "../components/MainGoalPanel";
import { CapitalChart } from "../components/charts/CapitalChart";
import { PassiveIncomeChart } from "../components/charts/PassiveIncomeChart";
import {
  EmptyState,
  ErrorState,
  Field,
  HelpTip,
  LoadingState,
  Panel,
  Select,
} from "../components/ui";
import { formatMoney, formatMoneyDelta, formatMonth, formatPercent } from "../lib/format";
import { MONTH_STATUS_LABELS, labelOf } from "../lib/labels";
import { moneyAmount } from "../lib/money";

function deltaToneFromAmount(amount: string | null | undefined): "up" | "down" | "neutral" {
  if (
    amount == null ||
    amount === "" ||
    amount === "0" ||
    amount === "0.00" ||
    amount === "-0.00"
  ) {
    return "neutral";
  }
  return amount.startsWith("-") ? "down" : "up";
}

function pctLabel(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  return formatPercent(value, { digits: 1 });
}

export function DashboardPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSlice | null>(null);
  const [loadingMonths, setLoadingMonths] = useState(true);
  const [loadingDash, setLoadingDash] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMonths = useCallback(async (signal?: AbortSignal) => {
    setLoadingMonths(true);
    setError(null);
    try {
      const rows = await listMonths(signal);
      if (signal?.aborted) return;
      const sorted = [...rows].sort((a, b) =>
        a.year === b.year ? b.month - a.month : b.year - a.year,
      );
      setMonths(sorted);
      setSelectedId((previous) => {
        if (previous != null && sorted.some((month) => month.id === previous)) return previous;
        return sorted[0]?.id ?? null;
      });
    } catch (loadError) {
      if (!signal?.aborted) {
        setError(formatApiError(loadError));
        setMonths([]);
        setSelectedId(null);
      }
    } finally {
      if (!signal?.aborted) setLoadingMonths(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadMonths(controller.signal);
    return () => controller.abort();
  }, [loadMonths]);

  useEffect(() => {
    if (selectedId == null) {
      setDashboard(null);
      return;
    }

    const controller = new AbortController();
    setLoadingDash(true);
    setError(null);
    void getDashboard(selectedId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setDashboard(data);
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setError(formatApiError(loadError));
          setDashboard(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDash(false);
      });

    return () => controller.abort();
  }, [selectedId]);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedId) ?? null,
    [months, selectedId],
  );
  const kpis = dashboard?.kpis ?? null;

  return (
    <section className="dashboard dashboard-v03 stack-18">
      <header className="page-header dashboard-v03__header">
        <p className="eyebrow">Обзор</p>
        <h1>Дашборд</h1>
        <p className="page-header__description">
          Капитал, пассивный доход, основная цель и покрытие расходов — без служебного шума.
        </p>
      </header>

      <div className="toolbar dashboard-v03__toolbar">
        <FieldMonthSelect
          disabled={loadingMonths || months.length === 0}
          months={months}
          onChange={setSelectedId}
          selectedId={selectedId}
        />
        {selectedMonth ? (
          <Link className="btn btn--primary" to={`/months/${selectedMonth.id}`}>
            Открыть месяц
          </Link>
        ) : (
          <Link className="btn btn--primary" to="/months">
            Создать месяц
          </Link>
        )}
        <Link className="btn btn--ghost" to="/months">
          Все месяцы
        </Link>
        <Link className="btn btn--ghost" to="/analytics">
          Аналитика
        </Link>
      </div>

      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}

      {loadingMonths ? (
        <LoadingState description="Загружаем список месяцев…" inline />
      ) : months.length === 0 ? (
        <EmptyState
          description="Месяцев пока нет — создай первый период в разделе «Месяцы»."
          title="Нет данных"
        />
      ) : null}

      <section className="dashboard-overview-grid" aria-label="Ключевое состояние">
        <CapitalOverviewCard kpis={kpis} loading={loadingDash} />
        <PassiveIncomeOverviewCard kpis={kpis} loading={loadingDash} />
        <MainGoalPanel
          fallbackProgressPct={kpis?.goal_progress_pct ?? null}
          fallbackTargetAmount={kpis ? moneyAmount(kpis.goal_target) : null}
          reportingMonthId={selectedId}
        />
        <CoverageOverviewCard kpis={kpis} loading={loadingDash} />
      </section>

      <Panel
        action={<Link to="/analytics">Подробнее →</Link>}
        label="История"
        title="Динамика капитала"
      >
        {loadingDash ? (
          <LoadingState description="Загружаем показатели…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Не удалось загрузить показатели" />
        ) : dashboard ? (
          <CapitalChart points={dashboard.historical_series ?? []} />
        ) : (
          <EmptyState description="Нет данных для графика." inline title="Пусто" />
        )}
      </Panel>

      <Panel label="Доход" title="Пассивный доход по месяцам">
        {loadingDash ? (
          <LoadingState description="Загружаем показатели…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Не удалось загрузить показатели" />
        ) : dashboard?.kpis ? (
          <PassiveIncomeChart
            average={moneyAmount(dashboard.kpis.passive_income_average)}
            complete12m={dashboard.kpis.passive_income_average_complete}
            countMonths={dashboard.kpis.passive_income_average_months}
            forecast={moneyAmount(dashboard.kpis.forecast_monthly_passive_income)}
            goal={moneyAmount(dashboard.kpis.goal_target)}
            points={dashboard.historical_series ?? []}
          />
        ) : (
          <EmptyState description="Нет данных для графика." inline title="Пусто" />
        )}
      </Panel>
    </section>
  );
}

function CapitalOverviewCard({ kpis, loading }: { kpis: DashboardKpis | null; loading: boolean }) {
  const delta = moneyAmount(kpis?.liquid_capital_delta);
  const tone = deltaToneFromAmount(delta);

  return (
    <article className="overview-card">
      <div className="overview-card__label">Ликвидный капитал</div>
      <div className="overview-card__value">
        {loading || !kpis ? "…" : formatMoney(moneyAmount(kpis.liquid_capital_net))}
      </div>
      <div className={`overview-card__delta overview-card__delta--${tone}`}>
        <span>Изменение за месяц</span>
        <strong>
          {loading || !kpis
            ? "…"
            : kpis.liquid_capital_delta
              ? formatMoneyDelta(delta)
              : "—"}
        </strong>
      </div>
    </article>
  );
}

function PassiveIncomeOverviewCard({
  kpis,
  loading,
}: {
  kpis: DashboardKpis | null;
  loading: boolean;
}) {
  const ready = !loading && kpis != null;
  const countMonths = ready ? kpis.passive_income_average_months : 0;
  const completeWindow = ready && kpis.passive_income_average_complete;

  return (
    <article className="overview-card overview-card--comparison">
      <div className="overview-card__label">Пассивный доход</div>
      <div className="semantic-label semantic-label--fact">Факт · среднее</div>
      <div className="overview-card__value">
        {ready ? formatMoney(moneyAmount(kpis.passive_income_average)) : "…"}
      </div>
      <div className="overview-card__context overview-card__context--with-help">
        {ready ? (
          completeWindow ? (
            <span>12 закрытых месяцев</span>
          ) : (
            <>
              <span>{countMonths} мес. из 12</span>
              <HelpTip label="Почему среднее пока неполное" align="start">
                Среднее фактического пассивного дохода рассчитано только по доступным закрытым
                месяцам. После 12 закрытых месяцев окно станет полным.
              </HelpTip>
            </>
          )
        ) : (
          <span>Фактические закрытые месяцы</span>
        )}
      </div>
      <div className="overview-card__compare">
        <div className="overview-card__compare-item overview-card__compare-item--forecast">
          <span className="semantic-label semantic-label--forecast">Прогноз</span>
          <strong>{ready ? formatMoney(moneyAmount(kpis.forecast_monthly_passive_income)) : "…"}</strong>
        </div>
        <div className="overview-card__compare-item overview-card__compare-item--goal">
          <span className="semantic-label semantic-label--goal">Цель</span>
          <strong>{ready ? formatMoney(moneyAmount(kpis.goal_target)) : "…"}</strong>
        </div>
      </div>
    </article>
  );
}

function CoverageOverviewCard({
  kpis,
  loading,
}: {
  kpis: DashboardKpis | null;
  loading: boolean;
}) {
  const ready = !loading && kpis != null;

  return (
    <article className="overview-card">
      <div className="overview-card__label">Покрытие расходов</div>
      <div className="overview-card__value">
        {ready ? pctLabel(kpis.mandatory_expense_coverage_pct) : "…"}
      </div>
      <div className="overview-card__supporting">
        <span>Обязательные расходы</span>
        <strong>{ready ? formatMoney(moneyAmount(kpis.mandatory_expenses)) : "…"}</strong>
      </div>
      <details className="overview-card__details">
        <summary>Ещё показатель</summary>
        <div>
          <span>Покрытие ипотеки</span>
          <strong>{ready ? pctLabel(kpis.mortgage_coverage_pct) : "…"}</strong>
        </div>
        <div>
          <span>Остаток ипотеки</span>
          <strong>{ready ? formatMoney(moneyAmount(kpis.mortgage_balance)) : "…"}</strong>
        </div>
      </details>
    </article>
  );
}

function FieldMonthSelect({
  months,
  selectedId,
  onChange,
  disabled,
}: {
  months: ReportingMonth[];
  selectedId: number | null;
  onChange: (id: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="field--inline">
      <Field htmlFor="kpi-month" label="Отчётный месяц">
        <Select
          disabled={disabled}
          id="kpi-month"
          onChange={(event) => onChange(Number(event.target.value))}
          value={selectedId ?? ""}
        >
          {months.length === 0 ? <option value="">—</option> : null}
          {months.map((month) => (
            <option key={month.id} value={month.id}>
              {formatMonth(month.year, month.month)} · {labelOf(MONTH_STATUS_LABELS, month.status)}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}
