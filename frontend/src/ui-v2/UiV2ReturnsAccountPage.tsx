import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, lazy, Suspense, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import sheet from "./ReportSheet.module.css";
import layout from "./returns/Dashboard.module.css";
import { reasonCopy } from "../lib/reasonCopy";
import { breakdownRows } from "./returns/breakdown";
import { UiV2Skeleton } from "./UiV2StateBlocks";
import { UiV2Tabs } from "./UiV2Tabs";
import resultStyles from "./returns/InstrumentResult.module.css";
import {
  compareDecimal,
  displayMetric,
  getContext,
  getOverview,
  type Instrument,
  isPartialResult,
  type Period,
  type Result,
  periodKey,
  periodLabel,
  ranked,
  unavailable,
  validDate,
} from "./returns/model";
import styles from "./returns/Returns.module.css";
import { ReturnsAcceptedIncome } from "./returns/ReturnsAcceptedIncome";
import { MissingName, ReturnsAvailable } from "./returns/ReturnsAvailable";
import { ReturnsBasket } from "./returns/ReturnsBasket";
import { ReturnsBreakdown } from "./returns/ReturnsBreakdown";
import { ReturnsDetail } from "./returns/ReturnsDetail";
import { ReturnsHistory } from "./returns/ReturnsHistory";
import { Explanation, Info, Value } from "./returns/ReturnsInfo";
import { ReturnsInstrumentResult } from "./returns/ReturnsInstrumentResult";
import { ReturnsResultMeta } from "./returns/ReturnsResultMeta";
import { UiV2Shell } from "./UiV2Shell";

const ReturnsSourceDiagnostics = lazy(() => import("./ReturnsSourceDiagnostics"));
const ReturnsPerformanceDiagnostics = lazy(() => import("./ReturnsPerformanceDiagnostics"));
const BrokerStatementReturnDiagnostics = lazy(() => import("./BrokerStatementReturnDiagnostics"));

function Instruments({
  rows,
  period,
  scope,
  revision,
  reasonCodes,
  initialIsin,
}: {
  rows: Instrument[];
  period: Period;
  scope: string;
  revision: number;
  reasonCodes: string[];
  initialIsin: string | null;
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState("pnl-desc");
  const [expanded, setExpanded] = useState<string | null>(initialIsin);
  const [limit, setLimit] = useState(20);
  const [mode, setMode] = useState<"pnl" | "rate">(() =>
    ranked(rows, period, "pnl", true).length || ranked(rows, period, "pnl", false).length
      ? "pnl"
      : "rate",
  );
  const hasLeaders = (["pnl", "rate"] as const).some((metric) =>
    [true, false].some((positive) => ranked(rows, period, metric, positive).length > 0),
  );
  const filtered = rows.filter(
    (r) =>
      (kind === "all" || r.kind === kind) &&
      `${r.name} ${r.isin}`.toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru")),
  );
  const [field, direction] = sort.split("-");
  filtered.sort((a, b) => {
    if (field === "name") return a.name.localeCompare(b.name, "ru");
    const x = a[field as "pnl" | "rate"].value;
    const y = b[field as "pnl" | "rate"].value;
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return compareDecimal(x, y) * (direction === "asc" ? 1 : -1) || a.isin.localeCompare(b.isin);
  });
  return (
    <>
      <section className={styles.panel} aria-labelledby="returns-instruments">
        <div className={styles.sectionHead}>
          <h2 id="returns-instruments">По инструментам</h2>
          <span>{rows.length} бумаг</span>
        </div>
        <div className={styles.filters}>
          <label>
            Поиск
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setLimit(20);
              }}
              placeholder="Название или ISIN"
            />
          </label>
          <label>
            Тип
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setLimit(20);
              }}
            >
              <option value="all">Все бумаги</option>
              <option value="stock">Акции</option>
              <option value="bond">Облигации</option>
            </select>
          </label>
          <label>
            Сортировка
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="pnl-desc">Результат ₽: больше</option>
              <option value="pnl-asc">Результат ₽: меньше</option>
              <option value="rate-desc">Доходность %: больше</option>
              <option value="rate-asc">Доходность %: меньше</option>
              <option value="name-asc">Название</option>
            </select>
          </label>
        </div>
        {!filtered.length ? (
          <div>
            Бумаги не найдены.{" "}
            {!!reasonCodes.length && (
              <Info label="Инструменты">
                <Explanation codes={reasonCodes} />
              </Info>
            )}
          </div>
        ) : (
          <table className={`${styles.instruments} ${resultStyles.list}`}>
            <thead>
              <tr>
                <th>Инструмент</th>
                <th colSpan={2}>Результат ₽ и доходность %</th>
                <th>Купоны / дивиденды</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, limit).map((row) => (
                <Fragment key={row.isin}>
                  <tr>
                    <th>
                      <button
                        type="button"
                        className={styles.instrumentName}
                        aria-expanded={expanded === row.isin}
                        onClick={() => setExpanded(expanded === row.isin ? null : row.isin)}
                      >
                        {expanded === row.isin ? "▾" : "▸"} {row.name}
                      </button>
                      <MissingName name={row.name} isin={row.isin} />
                      <small>
                        {row.isin} ·{" "}
                        {row.kind === "bond"
                          ? "Облигация"
                          : row.kind === "stock"
                            ? "Акция"
                            : "Бумага"}
                      </small>
                    </th>
                    <td colSpan={2}>
                      <ReturnsInstrumentResult result={row} />
                      <ReturnsResultMeta
                        period={row.period}
                        valuationDate={row.valuation_date}
                        accountLink={row.account_link}
                      />
                    </td>
                    <td>
                      <Value metric={row.coupons} label={`${row.name}: купоны`} />
                      <span className={styles.divider}> / </span>
                      <Value metric={row.dividends} label={`${row.name}: дивиденды`} />
                    </td>
                  </tr>
                  {expanded === row.isin && (
                    <tr>
                      <td colSpan={4}>
                        <ReturnsDetail
                          scope={scope}
                          period={period}
                          isin={row.isin}
                          revision={revision}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
        {filtered.length > limit && (
          <button type="button" onClick={() => setLimit(limit + 20)}>
            Показать ещё
          </button>
        )}
      </section>
      {hasLeaders && (
        <section className={styles.panel} aria-labelledby="returns-leaders">
          <div className={styles.sectionHead}>
            <div>
              <h2 id="returns-leaders">Лидеры и отстающие</h2>
              <p>{periodLabel(period)}</p>
            </div>
            <fieldset className={styles.toggle} aria-label="Показатель топов">
              <button type="button" aria-pressed={mode === "pnl"} onClick={() => setMode("pnl")}>
                P&amp;L ₽
              </button>
              <button type="button" aria-pressed={mode === "rate"} onClick={() => setMode("rate")}>
                %
              </button>
            </fieldset>
          </div>
          <div className={styles.tops}>
            {mode === "pnl" && rows.some((row) => isPartialResult(row.pnl)) && (
              <p>
                Порядок основан на показанных суммах; * — известная часть результата, не полный
                итог.
              </p>
            )}
            {[true, false].map((positive) => {
              const top = ranked(rows, period, mode, positive);
              if (!top.length) return null;
              return (
                <div key={String(positive)}>
                  <h3>{positive ? "Топ-5 прибыльных" : "Топ-5 убыточных"}</h3>
                  {!top.length ? (
                    <p className={styles.empty}>
                      Нет {positive ? "положительных" : "отрицательных"} результатов.
                    </p>
                  ) : (
                    <ol>
                      {top.map((r) => (
                        <li key={r.isin}>
                          <span>
                            {r.name}
                            <MissingName name={r.name} isin={r.isin} />
                            {r.name !== r.isin && <small>{r.isin}</small>}
                          </span>
                          <strong className={positive ? styles.positive : styles.negative}>
                            {displayMetric(r[mode], true)}
                            {mode === "pnl" && isPartialResult(r.pnl) && (
                              <>
                                <sup aria-hidden="true">*</sup>
                                <span className={sheet.visuallyHidden}>
                                  {" "}
                                  (известная часть, не полный итог)
                                </span>
                              </>
                            )}
                          </strong>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </>
  );
}

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
    const defaultAccount =
      params.get("period") !== "history" && context.data.closed_periods.length
        ? context.data.accounts.find((a) => a.id === "portfolio")
        : context.data.accounts.find((a) => a.basis === "statements");
    if (!params.has("scope") && defaultAccount) next.set("scope", defaultAccount.id);
    const sourcePeriods = context.data.source_periods[next.get("scope") ?? ""] ?? [];
    // Without a CLOSED default, only an explicitly selected source period may
    // drive the account result. Do not silently default to a DRAFT interval.
    const defaultPeriod =
      params.get("period") === "history"
        ? (context.data.source_history_periods?.[next.get("scope") ?? ""] ?? sourcePeriods.at(-1))
        : context.data.default_period;
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
  const options = [
    ...(scope.startsWith("source:")
      ? (context.data?.source_periods[scope] ?? [])
      : (context.data?.closed_periods ?? [])),
    ...(data?.periods ?? []),
  ]
    .filter(
      (p, i, all) => p.start < p.end && all.findIndex((v) => periodKey(v) === periodKey(p)) === i,
    )
    .sort((a, b) => b.end.localeCompare(a.end) || b.start.localeCompare(a.start));
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
  return (
    <div className={styles.page}>
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
          <label>
            Счёт
            <select
              aria-label="Счёт"
              value={scope}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("scope", e.target.value);
                // A different account has its own exact proof interval. Never
                // retain another account's inception dates as a valid selection.
                const periods = context.data?.source_periods[e.target.value] ?? [];
                const available = periods.some((p) => periodKey(p) === periodKey(period));
                if (!available) {
                  const own =
                    context.data?.source_history_periods?.[e.target.value] ??
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
              <option value="" disabled>
                Выберите счёт
              </option>
              {currentAccount && !selectableAccounts.includes(currentAccount) && (
                <option value={scope} disabled hidden>
                  {currentAccount.account_link?.status === "linked"
                    ? currentAccount.account_link.label
                    : currentAccount.label}
                </option>
              )}
              {selectableAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.account_link?.status === "linked"
                    ? account.account_link.label
                    : account.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Период
            <select
              aria-label="Период"
              value={
                options.some((p) => periodKey(p) === periodKey(period)) ? periodKey(period) : ""
              }
              onChange={(e) => {
                const [start, end] = e.target.value.split("/");
                if (validDate(start) && validDate(end) && start < end) choose({ start, end });
              }}
            >
              <option value="" disabled>
                Выберите период
              </option>
              {options.map((p) => (
                <option key={periodKey(p)} value={periodKey(p)}>
                  {periodLabel(p)}
                </option>
              ))}
            </select>
          </label>
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
        <p className={styles.basisNote}>
          {scope.startsWith("source:") ? (
            <>
              Основа подробностей — сохранённые выписки выбранного счёта. Это предварительная
              оценка; сохранение источника не означает принятия финансового месяца.
            </>
          ) : (
            <>
              Основа подробностей — принятые данные закрытых месяцев. Закрытие сохраняет факты, но
              само по себе не подтверждает полноту потоков для расчёта процента.{" "}
              <Link to="/v2/data/months">Открыть отчёты месяцев</Link>
            </>
          )}
        </p>
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
                          Доходность выбранного периода:{" "}
                          <Value metric={data.selected.rate} label="Доходность периода" />
                        </div>
                      )}
                    </>
                  ) : data.selected.pnl.value === null ? (
                    <>
                      <h2>Доходность периода</h2>
                      <Value metric={data.selected.rate} label="Доходность периода" />
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
                          : data.selected.pnl.reason_codes.includes("clean_partial_result")
                            ? "Известная часть за период"
                            : "Результат периода"}
                      </h2>
                      <div className={styles.mainValue}>
                        <Value metric={data.selected.pnl} label="Результат периода" signed />
                      </div>
                      {data.contract_version !== "returns_capital_v1" && (
                        <Value metric={data.selected.rate} label="Доходность периода" />
                      )}
                    </>
                  )}
                  <ReturnsResultMeta
                    period={data.selected.period}
                    valuationDate={data.selected.valuation_date}
                    accountLink={data.account_link}
                  />
                </section>
              )}
              {(data.available_months_total?.pnl.value != null ||
                data.all_history?.pnl.value != null) && (
                <section
                  className={styles.card}
                  aria-label={
                    data.available_months_total ? "За доступные месяцы" : "За всю историю"
                  }
                >
                  {data.available_months_total ? (
                    <ReturnsAvailable value={data.available_months_total} />
                  ) : (
                    <>
                      <h2>
                        {data.contract_version === "returns_capital_v1"
                          ? "Изменение капитала за историю"
                          : data.all_history?.pnl.reason_codes.includes("clean_partial_result")
                            ? "Известная часть за историю"
                            : "За всю историю"}
                      </h2>
                      <div className={styles.mainValue}>
                        <Value
                          metric={data.all_history?.pnl ?? unavailable}
                          label="Результат за историю"
                          signed
                        />
                      </div>
                      {data.all_history && (
                        <ReturnsResultMeta
                          period={data.all_history.period}
                          valuationDate={data.all_history.valuation_date}
                        />
                      )}
                      {!data.all_history && <small>Границы истории не установлены</small>}
                    </>
                  )}
                </section>
              )}
              {data.selected.coupons.value !== null && (
                <section className={styles.card} aria-label="Полученные купоны">
                  <h2>Полученные купоны</h2>
                  <div className={styles.mainValue}>
                    <Value metric={data.selected.coupons} label="Полученные купоны" />
                  </div>
                  <small>За выбранный период</small>
                </section>
              )}
              {data.selected.dividends.value !== null && (
                <section className={styles.card} aria-label="Полученные дивиденды">
                  <h2>Полученные дивиденды</h2>
                  <div className={styles.mainValue}>
                    <Value metric={data.selected.dividends} label="Полученные дивиденды" />
                  </div>
                  <small>За выбранный период</small>
                </section>
              )}
            </div>
            {data.accepted_income?.net_kopecks != null ? (
              <ReturnsAcceptedIncome value={data.accepted_income} />
            ) : data.breakdown && hasBreakdown ? (
              <ReturnsBreakdown value={data.breakdown} total={data.selected.pnl} />
            ) : null}
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
