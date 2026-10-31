import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import {
  compareDecimal,
  displayMetric,
  getContext,
  getOverview,
  type Instrument,
  type Period,
  periodKey,
  periodLabel,
  ranked,
  unavailable,
  validDate,
} from "./returns/model";
import styles from "./returns/Returns.module.css";
import { MissingName, ReturnsAvailable } from "./returns/ReturnsAvailable";
import { ReturnsBasket } from "./returns/ReturnsBasket";
import { ReturnsDetail } from "./returns/ReturnsDetail";
import { ReturnsHistory } from "./returns/ReturnsHistory";
import { Explanation, Info, Value } from "./returns/ReturnsInfo";
import { UiV2Shell } from "./UiV2Shell";
import { readDisplayNames } from "./returns/dashboard";

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
  const [mode, setMode] = useState<"pnl" | "rate">("pnl");
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
          <table className={styles.instruments}>
            <thead>
              <tr>
                <th>Инструмент</th>
                <th>Результат ₽</th>
                <th>Доходность %</th>
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
                    <td>
                      <Value metric={row.pnl} label={`${row.name}: результат`} signed />
                    </td>
                    <td>
                      <Value metric={row.rate} label={`${row.name}: доходность`} />
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
          {[true, false].map((positive) => {
            const top = ranked(rows, period, mode, positive);
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
    </>
  );
}

export default function UiV2ReturnsAccountPage() {
  const displayNames = readDisplayNames();
  const [params, setParams] = useSearchParams();
  const [basketExpanded, setBasketExpanded] = useState(() => params.has("categories"));
  const navigate = useNavigate();
  const { hash } = useLocation();
  const queryClient = useQueryClient();
  const context = useQuery({
    queryKey: ["returns", "context"],
    queryFn: ({ signal }) => getContext(signal),
    staleTime: 0,
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
    staleTime: 0,
  });
  const busy = context.isFetching || (selectionValid && overview.isFetching);
  const error = context.isError || (selectionValid && overview.isError);
  const data = !busy && !error && selectionValid ? overview.data : undefined;
  const choose = (p: Period) => {
    const next = new URLSearchParams(params);
    next.set("start", p.start);
    next.set("end", p.end);
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
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["returns"] });
  return (
    <div className={styles.page}>
      <UiV2Shell
        active="returns"
        busy={busy}
        header={
          <div className={styles.titleRow}>
            <div>
              <p className={styles.eyebrow}>Инвестиции</p>
              <h1>Доходность</h1>
            </div>
            <button type="button" onClick={refresh} disabled={busy}>
              Обновить
            </button>
          </div>
        }
      >
        <p>
          <Link to="/v2/returns">В целом — вся доступная история</Link>
        </p>
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
                next.delete("isin");
                setParams(next);
              }}
            >
              <option value="" disabled>
                Выберите счёт
              </option>
              {[scope && !scope.startsWith("source:") ? "accepted" : "statements"].map((basis) => (
                <optgroup
                  key={basis}
                  label={basis === "statements" ? "По выпискам" : "Подтверждённые отчёты"}
                >
                  {context.data?.accounts
                    .filter((a) => a.basis === basis)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {displayNames[a.id] || a.label}
                      </option>
                    ))}
                </optgroup>
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
          <p role="status" className={styles.status}>
            Загружаем доходность…
          </p>
        ) : !selectionValid ? (
          <p className={styles.status}>
            Выберите счёт и корректный период.
            {!context.data?.default_period && " Закрытых месяцев пока нет."}
          </p>
        ) : null}
        {data && (
          <>
            <h2>
              Подробности по счёту:{" "}
              {displayNames[scope] || context.data?.accounts.find((a) => a.id === scope)?.label}
            </h2>
            <div className={styles.cards}>
              <section
                className={`${styles.card} ${styles.primaryCard}`}
                aria-label="Результат периода"
              >
                {data.selected.pnl.value === null && data.selected_available_months_total ? (
                  <ReturnsAvailable value={data.selected_available_months_total} />
                ) : (
                  <>
                    <h2>Результат периода</h2>
                    <div className={styles.mainValue}>
                      <Value metric={data.selected.pnl} label="Результат периода" signed />
                    </div>
                    <Value metric={data.selected.rate} label="Доходность периода" />
                    <small>{periodLabel(data.selected.period)}</small>
                  </>
                )}
              </section>
              <section
                className={styles.card}
                aria-label={data.available_months_total ? "За доступные месяцы" : "За всю историю"}
              >
                {data.available_months_total ? (
                  <ReturnsAvailable value={data.available_months_total} />
                ) : (
                  <>
                    <h2>За всю историю</h2>
                    <div className={styles.mainValue}>
                      <Value
                        metric={data.all_history?.pnl ?? unavailable}
                        label="Результат за историю"
                        signed
                      />
                    </div>
                    <small>
                      {data.all_history
                        ? periodLabel(data.all_history.period)
                        : "Границы истории не установлены"}
                    </small>
                  </>
                )}
              </section>
              <section className={styles.card} aria-label="Полученные купоны">
                <h2>Полученные купоны</h2>
                <div className={styles.mainValue}>
                  <Value metric={data.selected.coupons} label="Полученные купоны" />
                </div>
                <small>За выбранный период</small>
              </section>
              <section className={styles.card} aria-label="Полученные дивиденды">
                <h2>Полученные дивиденды</h2>
                <div className={styles.mainValue}>
                  <Value metric={data.selected.dividends} label="Полученные дивиденды" />
                </div>
                <small>За выбранный период</small>
              </section>
            </div>
            <ReturnsHistory
              key={`${scope}/${periodKey(period)}`}
              rows={data.history}
              selected={period}
              choose={choose}
            />
            <Instruments
              key={`${scope}/${periodKey(period)}/${overview.dataUpdatedAt}`}
              scope={scope}
              period={period}
              rows={data.instruments}
              revision={overview.dataUpdatedAt}
              reasonCodes={data.instrument_reason_codes}
              initialIsin={params.get("isin")}
            />
          </>
        )}
        {context.data?.accounts.some((a) => a.id === scope) && (
          <details className={styles.diagnostics}>
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
              <p>Подтверждение выписок устарело. Зависимые значения требуют повторной проверки.</p>
            )}
            {scope.startsWith("source:") && (
              <Link
                to={`/v2/capital/monthly-returns?diagnostics=1&source_account=${encodeURIComponent(scope.slice(7))}`}
              >
                Открыть диагностику выписок
              </Link>
            )}
          </details>
        )}
      </UiV2Shell>
    </div>
  );
}
