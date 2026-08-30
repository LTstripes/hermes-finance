import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { formatApiError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import type {
  AssetAllocationPoint,
  DashboardForecast,
  DashboardKpis,
  DashboardSlice,
  ReportingMonth,
} from "../api/types";
import { CapitalChart } from "../components/charts/CapitalChart";
import { PassiveIncomeChart } from "../components/charts/PassiveIncomeChart";
import { CashFlowLadder } from "../components/CashFlowLadder";
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
import { labelOf, MONTH_STATUS_LABELS } from "../lib/labels";
import { moneyAmount } from "../lib/money";
import { queryKeys } from "../queryClient";

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

const ASSET_CLASS_META: Record<string, { label: string; color: string }> = {
  cash: { label: "Наличные", color: "#9db9a7" },
  deposits: { label: "Депозиты", color: "#d1ad72" },
  stocks: { label: "Акции", color: "#8ca9d8" },
  bonds: { label: "Облигации", color: "#b79bd4" },
  gold_other: { label: "Золото и прочее", color: "#d48c68" },
};

export function DashboardPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    select: (rows: ReportingMonth[]) =>
      [...rows].sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year)),
  });
  const months = monthsQuery.data ?? [];

  useEffect(() => {
    setSelectedId((previous) => {
      if (previous != null && months.some((month) => month.id === previous)) return previous;
      return months[0]?.id ?? null;
    });
  }, [months]);

  const dashboardQuery = useQuery<DashboardSlice, Error>({
    enabled: selectedId != null,
    placeholderData: (previousData: DashboardSlice | undefined) => previousData,
    queryKey: queryKeys.dashboard(selectedId),
    queryFn: async ({ signal }): Promise<DashboardSlice> => {
      if (selectedId == null) {
        return Promise.reject(new Error("Dashboard month is not selected"));
      }
      return getDashboard(selectedId, signal);
    },
  });

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedId) ?? null,
    [months, selectedId],
  );
  const loadingMonths = monthsQuery.isPending;
  const loadingDash = selectedId != null && dashboardQuery.isFetching;
  const error = monthsQuery.error
    ? formatApiError(monthsQuery.error)
    : dashboardQuery.error
      ? formatApiError(dashboardQuery.error)
      : null;
  const dashboard: DashboardSlice | null = error ? null : (dashboardQuery.data ?? null);
  const kpis = dashboard?.kpis ?? null;

  return (
    <section className="dashboard dashboard-v03 stack-18">
      <header className="page-header dashboard-v03__header">
        <p className="eyebrow">Обзор</p>
        <h1>Дашборд</h1>
        <p className="page-header__description">
          Капитал, пассивный доход, основная цель и покрытие расходов — в одном месте.
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
        <CapitalOverviewCard
          allocation={dashboard?.asset_allocation}
          allocationDelta={dashboard?.asset_allocation_delta}
          kpis={kpis}
          loading={loadingDash}
        />
        <PassiveIncomeOverviewCard kpis={kpis} loading={loadingDash} />
        <ForecastOverviewCard
          forecast={dashboard?.summary?.forecast ?? null}
          kpis={kpis}
          loading={loadingDash}
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

      <Panel label="Казначейство" title="Ближайшие события и денежная лестница">
        {loadingDash ? (
          <LoadingState description="Загружаем ожидаемые потоки…" inline />
        ) : dashboard?.cash_flow_ladder ? (
          <CashFlowLadder ladder={dashboard.cash_flow_ladder} />
        ) : (
          <EmptyState
            description="Нет данных о будущих денежных потоках для выбранного месяца."
            inline
            title="Лестница недоступна"
          />
        )}
      </Panel>
    </section>
  );
}

function CapitalOverviewCard({
  allocation,
  allocationDelta,
  kpis,
  loading,
}: {
  allocation?: AssetAllocationPoint[];
  allocationDelta?: AssetAllocationPoint[];
  kpis: DashboardKpis | null;
  loading: boolean;
}) {
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
          {loading || !kpis ? "…" : kpis.liquid_capital_delta ? formatMoneyDelta(delta) : "—"}
        </strong>
      </div>
      {!loading && allocation?.length ? (
        <div className="overview-card__breakdown">
          <div className="overview-card__breakdown-heading">
            <span>По классам</span>
            <span>Сейчас</span>
            <span>К месяцу ранее</span>
          </div>
          {allocation.map((item) => {
            const meta = ASSET_CLASS_META[item.asset_class] ?? {
              label: "Прочее",
              color: "#a6a6a6",
            };
            const previousDelta = allocationDelta?.find(
              (candidate) => candidate.asset_class === item.asset_class,
            );
            const deltaAmount = moneyAmount(previousDelta?.amount);
            return (
              <div className="overview-card__breakdown-row" key={item.asset_class}>
                <span className="overview-card__breakdown-label">
                  <i aria-hidden="true" style={{ backgroundColor: meta.color }} />
                  {meta.label}
                </span>
                <strong>{formatMoney(moneyAmount(item.amount))}</strong>
                <strong
                  className={`overview-card__breakdown-delta overview-card__delta--${deltaToneFromAmount(deltaAmount)}`}
                >
                  {previousDelta ? formatMoneyDelta(deltaAmount) : "—"}
                </strong>
              </div>
            );
          })}
        </div>
      ) : null}
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
    <article className="overview-card">
      <div className="overview-card__label">Пассивный доход · факт</div>
      <div className="overview-card__value">
        {ready ? formatMoney(moneyAmount(kpis.passive_income_actual)) : "…"}
      </div>
      <div className="overview-card__context overview-card__context--with-help">
        {ready ? (
          <>
            <span>
              {completeWindow
                ? "12 закрытых месяцев из 12"
                : `${countMonths} закрытых месяцев из 12`}
            </span>
            <HelpTip label="Подробнее о периоде" align="start">
              {!completeWindow ? (
                <p>Среднее рассчитано по закрытым месяцам в окне до 12 месяцев.</p>
              ) : null}
              <p>
                {kpis.passive_income_history_start_month
                  ? `Доступная история для среднего начинается с ${kpis.passive_income_history_start_month}.`
                  : "Для среднего используется вся доступная история."}
              </p>
              {!completeWindow ? <p>По мере закрытия новых месяцев окно обновляется.</p> : null}
            </HelpTip>
          </>
        ) : (
          <span>Фактические закрытые месяцы</span>
        )}
      </div>
      <div className="overview-card__supporting">
        <span>Среднее за закрытые месяцы</span>
        <strong>{ready ? formatMoney(moneyAmount(kpis.passive_income_average)) : "…"}</strong>
      </div>
      <div
        className={`overview-card__delta overview-card__delta--${ready ? deltaToneFromAmount(moneyAmount(kpis.passive_income_delta)) : "neutral"}`}
      >
        <span>К предыдущему месяцу</span>
        <strong>
          {ready && kpis.passive_income_delta
            ? formatMoneyDelta(moneyAmount(kpis.passive_income_delta))
            : "—"}
        </strong>
      </div>
    </article>
  );
}

function ForecastOverviewCard({
  forecast,
  kpis,
  loading,
}: {
  forecast: DashboardForecast | null;
  kpis: DashboardKpis | null;
  loading: boolean;
}) {
  const ready = !loading && kpis != null;

  return (
    <article className="overview-card">
      <div className="overview-card__label">Прогноз · 12 месяцев</div>
      <div className="overview-card__value">
        {ready ? formatMoney(moneyAmount(kpis.forecast_monthly_passive_income)) : "…"}
      </div>
      <div className="overview-card__supporting">
        <span>За следующие 12 месяцев</span>
        <strong>
          {ready ? formatMoney(moneyAmount(kpis.forecast_annual_passive_income)) : "…"}
        </strong>
      </div>
      <div className="overview-card__compare">
        <div>
          <span>Цель пассивного дохода</span>
          <strong>{ready ? formatMoney(moneyAmount(kpis.goal_target)) : "…"}</strong>
        </div>
        <div>
          <span>Прогноз / цель</span>
          <strong>{ready ? pctLabel(kpis.goal_progress_pct) : "…"}</strong>
        </div>
      </div>
      {ready ? <ForecastBreakdown forecast={forecast} /> : null}
      <Link className="overview-card__link" to="/goals">
        Настроить цель →
      </Link>
    </article>
  );
}

function ForecastBreakdown({ forecast }: { forecast: DashboardForecast | null }) {
  // These are backend-provided components.  The frontend only formats and
  // labels them; it does not recreate the forecast formula.
  if (!forecast) return null;

  return (
    <>
      <div className="overview-card__compare">
        <div>
          <span>Вклады</span>
          <strong>{formatMoney(moneyAmount(forecast.breakdown.expected_deposit_interest))}</strong>
        </div>
        <div>
          <span>Купоны</span>
          <strong>{formatMoney(moneyAmount(forecast.breakdown.expected_coupon_net))}</strong>
        </div>
        <div>
          <span>Дивиденды</span>
          <strong>
            {formatMoney(moneyAmount(forecast.breakdown.expected_dividend_component))}
          </strong>
        </div>
        <div>
          <span>Прочее</span>
          <strong>
            {formatMoney(moneyAmount(forecast.breakdown.other_expected_capital_income))}
          </strong>
        </div>
      </div>
      <div className="overview-card__context overview-card__context--with-help">
        {forecast.is_approximate ? <span>Часть прогноза оценочная</span> : null}
        <HelpTip label="Как составлен прогноз" align="start">
          Проценты по вкладам — оценка по снимкам выбранного месяца и текущему месячному прогнозу ×
          12; срок и изменение ставки не моделируются. Ручной процент складывается с этой оценкой,
          поэтому не вводи один и тот же процент дважды. Купоны берутся только из локального
          применённого календаря выплат. Дивидендный компонент построен по фактической истории;
          погашения исключены.
          {forecast.warnings.length > 0 ? (
            <ul className="overview-card__help-list">
              {forecast.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </HelpTip>
      </div>
    </>
  );
}

function CoverageOverviewCard({ kpis, loading }: { kpis: DashboardKpis | null; loading: boolean }) {
  const ready = !loading && kpis != null;

  return (
    <article className="overview-card">
      <div className="overview-card__label">Покрытие расходов</div>
      <div className="overview-card__value">
        {ready ? pctLabel(kpis.actual_mandatory_expense_coverage_pct) : "…"}
      </div>
      <div className="overview-card__supporting">
        <span>Обязательные расходы</span>
        <strong>{ready ? formatMoney(moneyAmount(kpis.mandatory_expenses)) : "…"}</strong>
      </div>
      <div className="overview-card__compare">
        <div>
          <span>Прогноз покрытия</span>
          <strong>{ready ? pctLabel(kpis.mandatory_expense_coverage_pct) : "…"}</strong>
        </div>
        <div>
          <span>Покрытие ипотеки</span>
          <strong>{ready ? pctLabel(kpis.mortgage_coverage_pct) : "…"}</strong>
        </div>
        <div>
          <span>Остаток ипотеки</span>
          <strong>{ready ? formatMoney(moneyAmount(kpis.mortgage_balance)) : "…"}</strong>
        </div>
      </div>
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
