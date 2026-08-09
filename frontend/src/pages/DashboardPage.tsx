import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { BackendStatus } from "../components/BackendStatus";
import { AssetAllocationChart } from "../components/charts/AssetAllocationChart";
import { CapitalChart } from "../components/charts/CapitalChart";
import { InvestmentResultChart } from "../components/charts/InvestmentResultChart";
import { PassiveIncomeChart } from "../components/charts/PassiveIncomeChart";
import {
  Badge,
  Button,
  CloneMonthDialog,
  EmptyState,
  ErrorState,
  Field,
  KpiCard,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import type { DashboardKpis, DashboardSlice, ReportingMonth } from "../api/types";
import {
  formatDate,
  formatMoney,
  formatMoneyDelta,
  formatMonth,
  formatPercent,
} from "../lib/format";
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
  if (value == null || value === "") {
    return "—";
  }
  return formatPercent(value, { digits: 1 });
}

export function DashboardPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSlice | null>(null);
  const [loadingMonths, setLoadingMonths] = useState(true);
  const [loadingDash, setLoadingDash] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);

  const loadMonths = useCallback(async (signal?: AbortSignal) => {
    setLoadingMonths(true);
    setError(null);
    try {
      const rows = await listMonths(signal);
      if (signal?.aborted) return;
      // newest first for selector convenience
      const sorted = [...rows].sort((a, b) =>
        a.year === b.year ? b.month - a.month : b.year - a.year,
      );
      setMonths(sorted);
      setSelectedId((prev) => {
        if (prev != null && sorted.some((m) => m.id === prev)) {
          return prev;
        }
        return sorted[0]?.id ?? null;
      });
    } catch (err) {
      if (!signal?.aborted) {
        setError(formatApiError(err));
        setMonths([]);
        setSelectedId(null);
      }
    } finally {
      if (!signal?.aborted) {
        setLoadingMonths(false);
      }
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
        if (!controller.signal.aborted) {
          setDashboard(data);
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(formatApiError(err));
          setDashboard(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingDash(false);
        }
      });
    return () => controller.abort();
  }, [selectedId]);

  const selectedMonth = useMemo(
    () => months.find((m) => m.id === selectedId) ?? null,
    [months, selectedId],
  );
  const kpis: DashboardKpis | null = dashboard?.kpis ?? null;

  const liquidDelta = moneyAmount(kpis?.liquid_capital_delta);
  const liquidTone = deltaToneFromAmount(liquidDelta);

  return (
    <section className="dashboard stack-18">
      <header className="page-header">
        <p className="eyebrow">Обзор</p>
        <h1>Дашборд</h1>
        <p className="page-header__description">
          KPI приходят готовыми из <code>GET /api/months/{"{id}"}/dashboard</code>. Без клиентских
          финансовых формул.
        </p>
      </header>

      <div className="toolbar">
        <FieldMonthSelect
          months={months}
          onChange={setSelectedId}
          selectedId={selectedId}
          disabled={loadingMonths || months.length === 0}
        />
        <Button
          disabled={!selectedMonth}
          onClick={() => setCloneOpen(true)}
          type="button"
          variant="primary"
        >
          Создать следующий месяц
        </Button>
        <Button
          disabled={loadingMonths || loadingDash}
          onClick={() => void loadMonths()}
          type="button"
        >
          Обновить
        </Button>
        {selectedMonth ? (
          <Link className="btn" to={`/months/${selectedMonth.id}`}>
            Открыть редактор
          </Link>
        ) : null}
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

      <section className="kpi-grid" aria-label="Ключевые показатели">
        <KpiCard
          label="Ликвидный капитал"
          value={loadingDash || !kpis ? "…" : formatMoney(moneyAmount(kpis.liquid_capital_net))}
          delta={
            loadingDash || !kpis
              ? "изменение за месяц"
              : kpis.liquid_capital_delta
                ? `${formatMoneyDelta(liquidDelta)} · месяц`
                : "нет изменений"
          }
          deltaTone={liquidTone}
        />
        <KpiCard
          label="Изменение за месяц"
          value={
            loadingDash || !kpis
              ? "…"
              : kpis.liquid_capital_delta
                ? formatMoneyDelta(liquidDelta)
                : "—"
          }
          delta="ликвидный капитал Δ"
          deltaTone={liquidTone}
        />
        <KpiCard
          label="Прогноз пассивного дохода"
          value={
            loadingDash || !kpis
              ? "…"
              : formatMoney(moneyAmount(kpis.forecast_monthly_passive_income))
          }
          delta="прогноз / мес"
          deltaTone="neutral"
        />
        <KpiCard
          label="Средний фактический доход"
          value={loadingDash || !kpis ? "…" : formatMoney(moneyAmount(kpis.passive_income_average))}
          delta="среднее фактическое значение"
          deltaTone="neutral"
        />
        <KpiCard
          label="Прогресс цели"
          value={loadingDash || !kpis ? "…" : pctLabel(kpis.goal_progress_pct)}
          delta="цель / покрытие"
          deltaTone="neutral"
        />
        <KpiCard
          label="Обязательные расходы"
          value={loadingDash || !kpis ? "…" : formatMoney(moneyAmount(kpis.mandatory_expenses))}
          delta="обязательные"
          deltaTone="neutral"
        />
        <KpiCard
          label="Покрытие расходов"
          value={loadingDash || !kpis ? "…" : pctLabel(kpis.mandatory_expense_coverage_pct)}
          delta="пассивный доход / обязательные"
          deltaTone="neutral"
        />
        <KpiCard
          label="Покрытие ипотеки"
          value={loadingDash || !kpis ? "…" : pctLabel(kpis.mortgage_coverage_pct)}
          delta={
            loadingDash || !kpis
              ? "ипотека"
              : `баланс ${formatMoney(moneyAmount(kpis.mortgage_balance))}`
          }
          deltaTone="neutral"
        />
      </section>

      <Panel label="История" title="Динамика капитала">
        {loadingDash ? (
          <LoadingState description="Тянем dashboard API…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Ошибка dashboard" />
        ) : dashboard ? (
          <CapitalChart points={dashboard.historical_series ?? []} />
        ) : (
          <EmptyState description="Нет данных для графика." inline title="Пусто" />
        )}
      </Panel>

      <Panel label="Доход" title="Пассивный доход">
        {loadingDash ? (
          <LoadingState description="Тянем dashboard API…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Ошибка dashboard" />
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

      <Panel label="Результат" title="Результат по классам и счетам">
        {loadingDash ? (
          <LoadingState description="Тянем dashboard API…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Ошибка dashboard" />
        ) : dashboard ? (
          <InvestmentResultChart
            accounts={dashboard.result_by_account ?? []}
            classes={dashboard.result_by_instrument_class ?? []}
          />
        ) : (
          <EmptyState description="Нет данных о результате." inline title="Пусто" />
        )}
      </Panel>

      <Panel label="Активы" title="Распределение активов">
        {loadingDash ? (
          <LoadingState description="Тянем dashboard API…" inline />
        ) : error && !dashboard ? (
          <ErrorState description={error} inline title="Ошибка dashboard" />
        ) : dashboard ? (
          <AssetAllocationChart allocation={dashboard.asset_allocation ?? []} />
        ) : (
          <EmptyState description="Нет данных для диаграммы." inline title="Пусто" />
        )}
      </Panel>

      <div className="dashboard-grid">
        <BackendStatus />

        <Panel
          label="Сводка"
          title={
            selectedMonth
              ? formatMonth(selectedMonth.year, selectedMonth.month)
              : "Нет выбранного месяца"
          }
        >
          {loadingDash ? (
            <LoadingState description="Тянем dashboard API…" inline />
          ) : error && !dashboard ? (
            <ErrorState description={error} inline title="Ошибка dashboard" />
          ) : dashboard?.kpis ? (
            <div className="stack-8">
              <p className="muted field-hint">
                Статус:{" "}
                <Badge tone={selectedMonth?.status === "draft" ? "draft" : "closed"}>
                  {selectedMonth ? labelOf(MONTH_STATUS_LABELS, selectedMonth.status) : "—"}
                </Badge>{" "}
                · снимок {selectedMonth ? formatDate(selectedMonth.snapshot_date) : "—"}
                {dashboard.calculation_version ? ` · calc ${dashboard.calculation_version}` : null}
              </p>
              {dashboard.warnings && dashboard.warnings.length > 0 ? (
                <div className="inline-alert inline-alert--warn" role="status">
                  {dashboard.warnings.join(" · ")}
                </div>
              ) : (
                <p className="muted">Предупреждений нет.</p>
              )}
            </div>
          ) : (
            <EmptyState description="Выбери месяц со сводкой." inline title="Пусто" />
          )}
        </Panel>
      </div>

      <Panel action={<Link to="/months">К списку →</Link>} label="Периоды" title="Отчётные месяцы">
        {months.length === 0 ? (
          <EmptyState description="Список пуст." inline title="Нет месяцев" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Период</Th>
                <Th>Статус</Th>
                <Th numeric>Снимок</Th>
                <Th>Действия</Th>
              </tr>
            </thead>
            <tbody>
              {months.map((row) => (
                <tr key={row.id}>
                  <Td>{formatMonth(row.year, row.month)}</Td>
                  <Td>
                    <Badge tone={row.status === "draft" ? "draft" : "closed"}>
                      {labelOf(MONTH_STATUS_LABELS, row.status)}
                    </Badge>
                  </Td>
                  <Td numeric>{formatDate(row.snapshot_date)}</Td>
                  <Td>
                    <div className="row-actions">
                      <Button
                        onClick={() => setSelectedId(row.id)}
                        size="sm"
                        type="button"
                        variant={row.id === selectedId ? "primary" : "secondary"}
                      >
                        KPI
                      </Button>
                      <Link className="btn btn--sm" to={`/months/${row.id}`}>
                        Открыть
                      </Link>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>

      {selectedMonth ? (
        <CloneMonthDialog
          onCancel={() => setCloneOpen(false)}
          onCloned={(cloned) => {
            setCloneOpen(false);
            setSelectedId(cloned.id);
            void loadMonths();
          }}
          open={cloneOpen}
          source={selectedMonth}
        />
      ) : null}
    </section>
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
      <Field htmlFor="kpi-month" label="Месяц KPI">
        <Select
          disabled={disabled}
          id="kpi-month"
          onChange={(e) => onChange(Number(e.target.value))}
          value={selectedId ?? ""}
        >
          {months.length === 0 ? <option value="">—</option> : null}
          {months.map((m) => (
            <option key={m.id} value={m.id}>
              {formatMonth(m.year, m.month)} · {labelOf(MONTH_STATUS_LABELS, m.status)}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}
