import { useAccountName } from "./returns/useAccountName";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import sheet from "./ReportSheet.module.css";
import layout from "./returns/Dashboard.module.css";
import { reasonCopy } from "../lib/reasonCopy";
import { breakdownRows } from "./returns/breakdown";
import { UiV2Skeleton } from "./UiV2StateBlocks";
import { UiV2Tabs } from "./UiV2Tabs";
import { ReturnsMonthInstruments as Instruments } from "./returns/ReturnsMonthInstruments";
import {
  getContext,
  getOverview,
  isPartialResult,
  type Period,
  type Result,
  periodKey,
  periodLabel,
  validDate,
  unavailable,
} from "./returns/model";
import styles from "./returns/Returns.module.css";
import { ReturnsAcceptedIncome } from "./returns/ReturnsAcceptedIncome";
import { ReturnsAvailable } from "./returns/ReturnsAvailable";
import { ReturnsBasket } from "./returns/ReturnsBasket";
import { ReturnsBreakdown } from "./returns/ReturnsBreakdown";
import { ReturnsHistory } from "./returns/ReturnsHistory";
import { CompactValue, Info, Value } from "./returns/ReturnsInfo";
import { ReturnsResultMeta } from "./returns/ReturnsResultMeta";
import { UiV2Shell } from "./UiV2Shell";

const ReturnsSourceDiagnostics = lazy(() => import("./ReturnsSourceDiagnostics"));
const ReturnsPerformanceDiagnostics = lazy(() => import("./ReturnsPerformanceDiagnostics"));
const BrokerStatementReturnDiagnostics = lazy(() => import("./BrokerStatementReturnDiagnostics"));

export default function UiV2ReturnsAccountPage() {
  const [params, setParams] = useSearchParams();
  const [diagnosticsExpanded, setDiagnosticsExpanded] = useState(() => params.has("diagnostics"));
  const [diagnosticsLoaded, setDiagnosticsLoaded] = useState(diagnosticsExpanded);
  const [statementExpanded, setStatementExpanded] = useState(
    () => params.get("diagnostics") === "statement",
  );
  const [statementLoaded, setStatementLoaded] = useState(statementExpanded);
  const [basketExpanded, setBasketExpanded] = useState(() => params.has("categories"));
  const navigate = useNavigate();
  const { hash } = useLocation();
  const queryClient = useQueryClient();
  const context = useQuery({
    queryKey: ["returns", "context"],
    queryFn: ({ signal }) => getContext(signal),
    staleTime: 5 * 60 * 1000,
  });
  const accountName = useAccountName(context.data?.accounts.map((a) => a.account_link) ?? []);
  const scope = params.get("scope") ?? "";
  const period = { start: params.get("start") ?? "", end: params.get("end") ?? "" };
  const selectionValid =
    !!context.data?.accounts.some((a) => a.id === scope) &&
    validDate(period.start) &&
    validDate(period.end) &&
    period.start < period.end &&
    ["scope", "start", "end"].every((k) => params.getAll(k).length === 1);
  useEffect(() => {
    if (!context.data || context.isFetching || context.isError) return;
    if (["scope", "start", "end"].some((k) => params.getAll(k).length > 1)) return;
    const next = new URLSearchParams(params);
    const canonical = context.data.scope_aliases?.[scope];
    if (canonical) next.set("scope", canonical);
    const defaultAccount = params.has("diagnostics")
      ? params.get("period") !== "history" && context.data.closed_periods.length
        ? context.data.accounts.find((a) => a.id === "portfolio")
        : context.data.accounts.find((a) => a.basis === "statements")
      : (context.data.accounts.find(
          (a) => a.id !== "portfolio" && (context.data.source_periods[a.id]?.length ?? 0) > 0,
        ) ?? context.data.accounts.find((a) => a.id === "portfolio"));
    if (!params.has("scope") && defaultAccount) next.set("scope", defaultAccount.id);
    const sourcePeriods = context.data.source_periods[next.get("scope") ?? ""] ?? [];
    // Explicit URLs and diagnostics retain their CLOSED/history defaults.
    // An ordinary fresh entry can use its own last saved source interval.
    const defaultPeriod =
      params.get("period") === "history"
        ? (context.data.source_history_periods?.[next.get("scope") ?? ""] ?? sourcePeriods.at(-1))
        : (context.data.default_period ??
          (!params.has("scope") && !params.has("diagnostics") ? sourcePeriods.at(-1) : null));
    if (!params.has("start") && !params.has("end") && defaultPeriod) {
      next.set("start", defaultPeriod.start);
      next.set("end", defaultPeriod.end);
      next.delete("period");
    }
    if (next.toString() !== params.toString())
      navigate({ search: next.toString(), hash }, { replace: true });
  }, [context.data, context.isError, context.isFetching, params, navigate, hash, scope]);
  const overview = useQuery({
    queryKey: ["returns", "overview", scope, period.start, period.end],
    queryFn: ({ signal }) => getOverview(scope, period, signal),
    // Refresh the same selection once; display still waits for current context.
    enabled: selectionValid && !context.isError,
    staleTime: 5 * 60 * 1000,
  });
  const busy = context.isFetching || (selectionValid && overview.isFetching);
  const error = context.isError || (selectionValid && overview.isError);
  const data = !busy && !error && selectionValid ? overview.data : undefined;
  const choose = (p: Period) => {
    const next = new URLSearchParams(params);
    next.set("start", p.start);
    next.set("end", p.end);
    next.delete("month");
    setParams(next);
  };
  const hasResult = (row: Result | null | undefined) =>
    !!row &&
    [row.pnl, row.rate, row.coupons, row.dividends].some((metric) => metric.value !== null);
  const historyRows = data?.history ?? [];
  const hasHistoryValues = historyRows.some(
    (row) => row.pnl.value !== null || row.rate.value !== null,
  );
  const instrumentRows = data?.instruments ?? [];
  const hasBreakdown =
    !!data?.breakdown && breakdownRows(data.breakdown).some((row) => row.value !== null);
  const empty =
    !!data &&
    !hasResult(data.selected) &&
    !hasResult(data.all_history) &&
    data.available_months_total?.pnl.value == null &&
    data.selected_available_months_total?.pnl.value == null &&
    data.accepted_income?.net_kopecks == null &&
    !hasBreakdown &&
    !hasHistoryValues &&
    !instrumentRows.length;
  const emptyReason = data
    ? [
        ...data.selected.pnl.reason_codes,
        ...data.selected.rate.reason_codes,
        ...data.instrument_reason_codes,
      ][0]
    : undefined;
  const selectableAccounts =
    context.data?.accounts.filter(
      (account) =>
        account.id === "portfolio" || (context.data?.source_periods[account.id]?.length ?? 0) > 0,
    ) ?? [];
  const currentAccount = context.data?.accounts.find((account) => account.id === scope);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["returns"] });
  const summary =
    data && !empty ? (
      <>
        <div className={styles.cards}>
          {(data.selected.pnl.value !== null ||
            data.selected.rate.value !== null ||
            data.selected_available_months_total?.pnl.value != null) && (
            <section
              className={`${styles.card} ${styles.primaryCard}`}
              aria-label="Результат периода"
            >
              {data.selected.pnl.value === null &&
              data.selected_available_months_total?.pnl.value != null ? (
                <>
                  <ReturnsAvailable value={data.selected_available_months_total} />
                  {data.selected.rate.value !== null && (
                    <div>
                      Доходность выбранного периода: <CompactValue metric={data.selected.rate} />
                    </div>
                  )}
                </>
              ) : data.selected.pnl.value === null ? (
                <>
                  <h2>Доходность периода</h2>
                  <CompactValue metric={data.selected.rate} />
                  <p className={styles.basisNote}>
                    {
                      reasonCopy(
                        data.selected.pnl.reason_codes[0] ?? "selected_components_incomplete",
                        { surface: "returns" },
                      ).message
                    }
                  </p>
                  {data.selected_available_months_total && (
                    <small>
                      Месяцы: {data.selected_available_months_total.covered_months} из{" "}
                      {data.selected_available_months_total.total_months}
                    </small>
                  )}
                </>
              ) : (
                <>
                  <h2>
                    {data.contract_version === "returns_capital_v1"
                      ? "Изменение капитала за период"
                      : isPartialResult(data.selected.pnl)
                        ? "Известная часть за период"
                        : "Результат периода"}
                  </h2>
                  <div className={styles.mainValue}>
                    <CompactValue metric={data.selected.pnl} signed />
                  </div>
                  {data.contract_version !== "returns_capital_v1" &&
                    data.selected.rate.value !== null && (
                      <CompactValue metric={data.selected.rate} />
                    )}
                </>
              )}
              <ReturnsResultMeta
                period={data.selected.period}
                valuationDate={data.selected.valuation_date}
                accountLink={
                  data.account_link?.status === "unlinked" ? data.account_link : undefined
                }
                accountLabel={accountName(data.account_link, currentAccount?.label ?? "")}
              />
            </section>
          )}
          {data.selected.coupons.value !== null && data.selected.coupons.value !== "0" && (
            <section className={styles.card} aria-label="Полученные купоны">
              <h2>Купоны</h2>
              <div className={styles.mainValue}>
                <CompactValue metric={data.selected.coupons} />
              </div>
            </section>
          )}
          {data.selected.dividends.value !== null && data.selected.dividends.value !== "0" && (
            <section className={styles.card} aria-label="Полученные дивиденды">
              <h2>Дивиденды</h2>
              <div className={styles.mainValue}>
                <CompactValue metric={data.selected.dividends} />
              </div>
            </section>
          )}
        </div>
        <Link className={layout.quiet} to="/v2/returns">
          За всю историю →
        </Link>
        {data.accepted_income?.net_kopecks != null ? (
          <ReturnsAcceptedIncome value={data.accepted_income} />
        ) : data.breakdown && hasBreakdown ? (
          <details className={layout.income}>
            <summary>Из чего сложился результат</summary>
            <ReturnsBreakdown value={data.breakdown} total={data.selected.pnl} />
          </details>
        ) : null}
      </>
    ) : null;
  return (
    <div className={`${styles.page} ${styles.monthPage}`}>
      <UiV2Shell
        showRefresh={false}
        active="returns"
        busy={busy}
        header={
          <div className={sheet.titleRow}>
            <h1>Доходность</h1>
            <span className={sheet.titleLinks}>
              <button type="button" className={layout.quiet} onClick={refresh} disabled={busy}>
                Обновить
              </button>
            </span>
          </div>
        }
      >
        <UiV2Tabs
          label="Разделы доходности"
          tabs={[
            { label: "Обзор", to: "/v2/returns", active: false },
            { label: "По месяцам", to: `/v2/returns/account?${params}`, active: true },
          ]}
        />
        <div className={styles.controls}>
          <fieldset className={sheet.segmented} aria-label="Счета">
            {currentAccount && !selectableAccounts.includes(currentAccount) && (
              <button
                type="button"
                aria-pressed="true"
                disabled
                title={currentAccount.account_link?.source_account_id}
              >
                {accountName(currentAccount.account_link, currentAccount.label)}
              </button>
            )}
            {selectableAccounts.map((account) => (
              <button
                type="button"
                key={account.id}
                aria-pressed={scope === account.id}
                title={account.account_link?.source_account_id}
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.set("scope", account.id);
                  // A different account has its own exact proof interval. Never
                  // retain another account's inception dates as a valid selection.
                  const periods = context.data?.source_periods[account.id] ?? [];
                  const available = periods.some((p) => periodKey(p) === periodKey(period));
                  if (!available) {
                    const own =
                      context.data?.source_history_periods?.[account.id] ??
                      periods.at(-1) ??
                      context.data?.default_period;
                    if (own) {
                      next.set("start", own.start);
                      next.set("end", own.end);
                    } else {
                      next.delete("start");
                      next.delete("end");
                    }
                  }
                  for (const key of ["isin", "source_account", "bond_isin", "bond_period"])
                    next.delete(key);
                  setParams(next);
                }}
              >
                {accountName(account.account_link, account.label)}
              </button>
            ))}
          </fieldset>
          <details className={styles.dates}>
            <summary>Свой интервал</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                choose({ start: String(f.get("start")), end: String(f.get("end")) });
              }}
              key={periodKey(period)}
            >
              <label>
                Начальная стоимость на
                <input required type="date" name="start" defaultValue={period.start} />
              </label>
              <label>
                Конечная стоимость на
                <input required type="date" name="end" defaultValue={period.end} />
              </label>
              <button type="submit">Показать</button>
            </form>
          </details>
        </div>
        {params.has("diagnostics") && (
          <details
            className={styles.diagnostics}
            open={basketExpanded}
            onToggle={(event) => setBasketExpanded(event.currentTarget.open)}
          >
            <summary>Дополнительная диагностика портфеля за выбранный период</summary>
            {basketExpanded && (
              <ReturnsBasket
                period={period}
                refreshing={context.isFetching || context.isError}
                contextError={context.isError}
              />
            )}
          </details>
        )}
        {selectionValid && (
          <div className={styles.periodLine}>
            {periodLabel(period)}
            {scope.startsWith("source:") && <span className={styles.estimate}>Оценка</span>}
            <Info label="Границы периода">
              <p>
                Стоимость — на конец указанных дней. Денежные операции учитываются после начальной
                даты, включая конечную.
              </p>
            </Info>
          </div>
        )}
        {error ? (
          <p role="alert" className={styles.status}>
            Не удалось загрузить доходность.{" "}
            <button type="button" onClick={refresh}>
              Повторить
            </button>
          </p>
        ) : busy ? (
          <UiV2Skeleton label="Загружаем доходность…" expectedTime />
        ) : !selectionValid ? (
          <p className={styles.status}>
            Выберите счёт и корректный период.
            {!context.data?.default_period && " Закрытых месяцев пока нет."}
          </p>
        ) : null}
        {empty && (
          <section className={styles.panel} aria-label="Нет данных о доходности">
            <h2>За выбранный период пока нет данных о доходности</h2>
            <p>
              {
                reasonCopy(emptyReason ?? "source_result_unavailable", { surface: "returns" })
                  .message
              }
            </p>
            <Link to="/v2/returns">Открыть итог за всю историю</Link>
          </section>
        )}
        {data && !empty && (
          <>
            {!hasHistoryValues && summary}
            {hasHistoryValues && (
              <ReturnsHistory
                key={`${scope}/${periodKey(period)}`}
                rows={
                  data.contract_version === "returns_capital_v1"
                    ? historyRows.map((row) => ({
                        ...row,
                        rate: { ...unavailable, unit: "fraction" },
                      }))
                    : historyRows
                }
                selected={period}
                choose={choose}
                summary={summary}
              />
            )}
            {instrumentRows.length > 0 && (
              <Instruments
                key={`${scope}/${periodKey(period)}/${overview.dataUpdatedAt}`}
                scope={scope}
                period={period}
                rows={instrumentRows}
                revision={overview.dataUpdatedAt}
                reasonCodes={data.instrument_reason_codes}
                initialIsin={params.get("isin")}
              />
            )}
          </>
        )}
        {!!scope && !params.has("diagnostics") && !error && !busy && (
          <details className={layout.footer}>
            <summary>Подробнее о данных</summary>
            <p className={styles.basisNote}>
              {scope.startsWith("source:") ? (
                <>
                  Основа подробностей — сохранённые выписки выбранного счёта. Это предварительная
                  оценка; сохранение источника не означает принятия финансового месяца.
                </>
              ) : (
                <>
                  Основа подробностей — принятые данные закрытых месяцев. Закрытие сохраняет факты,
                  но само по себе не подтверждает полноту потоков для расчёта процента.{" "}
                  <Link to="/v2/data/months">Открыть отчёты месяцев</Link>
                </>
              )}
            </p>

            <p>
              Процент по бумагам — Modified Dietz за выбранный период, без пересчёта на год. Прочерк
              означает отсутствие подтверждённого значения.
            </p>
            {data && (
              <>
                <Value metric={data.selected.pnl} label="Результат периода" signed />
                <Value metric={data.selected.rate} label="Доходность периода" />
                <Value metric={data.selected.coupons} label="Полученные купоны" />
                <Value metric={data.selected.dividends} label="Полученные дивиденды" />
                {data.available_months_total && (
                  <section aria-label="За доступные месяцы">
                    <ReturnsAvailable value={data.available_months_total} />
                  </section>
                )}
              </>
            )}
          </details>
        )}
        {!!scope && params.has("diagnostics") && (
          <details
            className={styles.diagnostics}
            open={diagnosticsExpanded}
            onToggle={(event) => {
              setDiagnosticsExpanded(event.currentTarget.open);
              if (event.currentTarget.open) setDiagnosticsLoaded(true);
            }}
          >
            <summary>Подробнее о данных</summary>
            <p>
              Результаты используют существующие расчёты; неизвестные значения остаются пустыми.
            </p>
            <p>
              Основа:{" "}
              {scope.startsWith("source:")
                ? "сохранённые брокерские выписки; оценка"
                : "принятые данные закрытых месяцев"}
              . Источник выбран явно: <code>{scope}</code>.
            </p>
            <p>
              Состояние проверки: <code>{data?.proof_status ?? "не загружено"}</code>. Покрытие и
              причины недоступности указаны у каждой метрики и в истории.
            </p>
            {data?.proof_status === "stale" && (
              <p>
                Ранее сохранённая проверка устарела; доступные данные источников показаны отдельно.
              </p>
            )}
            {diagnosticsLoaded && (
              <Suspense fallback={<p>Загружаем подробности…</p>}>
                {scope.startsWith("source:") ? (
                  context.data?.accounts.some((account) => account.id === scope) ? (
                    <ReturnsSourceDiagnostics key={scope} account={scope.slice(7)} />
                  ) : null
                ) : (
                  <>
                    <ReturnsPerformanceDiagnostics />
                    <details
                      open={statementExpanded}
                      onToggle={(event) => {
                        setStatementExpanded(event.currentTarget.open);
                        if (event.currentTarget.open) setStatementLoaded(true);
                      }}
                    >
                      <summary>Доходность по отдельной выписке и сценарий</summary>
                      {statementLoaded && (
                        <BrokerStatementReturnDiagnostics
                          key={scope}
                          accountId={
                            /^account:[1-9]\d*$/.test(scope) ? Number(scope.slice(8)) : undefined
                          }
                        />
                      )}
                    </details>
                  </>
                )}
              </Suspense>
            )}
          </details>
        )}
      </UiV2Shell>
    </div>
  );
}
