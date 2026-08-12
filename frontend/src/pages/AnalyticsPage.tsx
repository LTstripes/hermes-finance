import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { getCapitalComposition } from "../api/analytics";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import type { CapitalCompositionHistory, DashboardSlice, ReportingMonth } from "../api/types";
import { AssetAllocationChart } from "../components/charts/AssetAllocationChart";
import {
  CapitalCompositionChart,
  type CapitalCompositionMode,
} from "../components/charts/CapitalCompositionChart";
import { InvestmentResultChart } from "../components/charts/InvestmentResultChart";
import { EmptyState, ErrorState, Field, LoadingState, Panel, Select } from "../components/ui";
import { formatMonth } from "../lib/format";

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year));
}

function monthOptionLabel(month: ReportingMonth): string {
  return `${formatMonth(month.year, month.month)} · ${month.status === "closed" ? "закрыт" : "черновик"}`;
}

export function AnalyticsPage() {
  const [history, setHistory] = useState<CapitalCompositionHistory | null>(null);
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSlice | null>(null);
  const [mode, setMode] = useState<CapitalCompositionMode>("amount");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setHistoryLoading(true);
    void getCapitalComposition(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setHistory(data);
          setHistoryError(null);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHistory(null);
          setHistoryError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setMonthsLoading(true);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        const sorted = sortMonths(rows);
        setMonths(sorted);
        setSelectedMonthId((previous) =>
          previous != null && sorted.some((month) => month.id === previous)
            ? previous
            : (sorted[0]?.id ?? null),
        );
        setMonthsError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMonths([]);
          setSelectedMonthId(null);
          setMonthsError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMonthsLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (selectedMonthId == null) {
      setDashboard(null);
      setDashboardLoading(false);
      return;
    }

    const controller = new AbortController();
    setDashboardLoading(true);
    void getDashboard(selectedMonthId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setDashboard(data);
          setDashboardError(null);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setDashboard(null);
          setDashboardError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDashboardLoading(false);
      });
    return () => controller.abort();
  }, [selectedMonthId]);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );
  const error = historyError ?? monthsError;

  return (
    <section className="analytics-v03 stack-18">
      <header className="page-header analytics-v03__header">
        <p className="eyebrow">Обзор</p>
        <h1>Аналитика</h1>
        <p className="page-header__description">
          Состав ликвидных активов по закрытым месяцам и подробный срез выбранного периода.
        </p>
      </header>

      <div className="toolbar analytics-v03__toolbar">
        <Field htmlFor="analytics-current-month" label="Текущий срез">
          <Select
            aria-label="Текущий срез"
            disabled={monthsLoading || months.length === 0}
            id="analytics-current-month"
            onChange={(event) => setSelectedMonthId(Number(event.target.value))}
            value={selectedMonthId ?? ""}
          >
            {months.length === 0 ? <option value="">Нет месяцев</option> : null}
            {months.map((month) => (
              <option key={month.id} value={month.id}>
                {monthOptionLabel(month)}
              </option>
            ))}
          </Select>
        </Field>
        {selectedMonth ? (
          <Link className="btn btn--ghost" to={`/months/${selectedMonth.id}`}>
            Открыть месяц
          </Link>
        ) : (
          <Link className="btn btn--primary" to="/months">
            Создать месяц
          </Link>
        )}
      </div>

      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}

      <Panel
        action={
          <fieldset className="analytics-v03__toggle">
            <legend className="visually-hidden">Режим отображения</legend>
            <button
              aria-pressed={mode === "amount"}
              className={`btn btn--sm ${mode === "amount" ? "btn--primary" : "btn--secondary"}`}
              onClick={() => setMode("amount")}
              type="button"
            >
              Сумма ₽
            </button>
            <button
              aria-pressed={mode === "share"}
              className={`btn btn--sm ${mode === "share" ? "btn--primary" : "btn--secondary"}`}
              onClick={() => setMode("share")}
              type="button"
            >
              Доля %
            </button>
          </fieldset>
        }
        className="analytics-v03__history-panel"
        label="Капитал"
        title="Состав капитала во времени"
      >
        {historyLoading ? (
          <LoadingState description="Загружаем историю состава капитала…" inline />
        ) : historyError ? (
          <ErrorState description={historyError} inline title="Не удалось загрузить историю" />
        ) : history ? (
          <CapitalCompositionChart
            assetClasses={history.asset_classes}
            mode={mode}
            points={history.points}
          />
        ) : (
          <EmptyState description="Нет данных для графика." inline title="Пусто" />
        )}
      </Panel>

      <section aria-label="Подробности текущего среза" className="analytics-v03__drilldown">
        <Panel label="Структура" title="Текущее распределение">
          {dashboardLoading ? (
            <LoadingState description="Загружаем текущий срез…" inline />
          ) : dashboardError ? (
            <ErrorState description={dashboardError} inline title="Не удалось загрузить срез" />
          ) : dashboard ? (
            <AssetAllocationChart allocation={dashboard.asset_allocation ?? []} />
          ) : (
            <EmptyState
              description="Выбери месяц с данными, чтобы увидеть распределение по классам."
              inline
              title="Нет текущего среза"
            />
          )}
        </Panel>

        <Panel label="Результат" title="Результат инвестиций">
          {dashboardLoading ? (
            <LoadingState description="Загружаем результат…" inline />
          ) : dashboardError ? (
            <ErrorState
              description={dashboardError}
              inline
              title="Не удалось загрузить результат"
            />
          ) : dashboard ? (
            <InvestmentResultChart
              accounts={dashboard.result_by_account ?? []}
              classes={dashboard.result_by_instrument_class ?? []}
            />
          ) : (
            <EmptyState
              description="Выбери месяц с данными, чтобы увидеть результат по счетам и классам."
              inline
              title="Нет результата"
            />
          )}
        </Panel>
      </section>
    </section>
  );
}
