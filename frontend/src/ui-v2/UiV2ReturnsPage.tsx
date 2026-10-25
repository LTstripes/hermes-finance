import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { UiV2Shell } from "./UiV2Shell";
import { ReturnsDetail } from "./returns/ReturnsDetail";
import { ReturnsHistory } from "./returns/ReturnsHistory";
import { Explanation, Info, Value } from "./returns/ReturnsInfo";
import {
  compareDecimal,
  displayMetric,
  getContext,
  getOverview,
  periodKey,
  periodLabel,
  ranked,
  unavailable,
  validDate,
  type Instrument,
  type Period,
} from "./returns/model";
import styles from "./returns/Returns.module.css";

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
                        <span>{r.name}</span>
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

export default function UiV2ReturnsPage() {
  const [params, setParams] = useSearchParams();
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
    const next = new URLSearchParams(params);
    if (!params.has("scope") && context.data.accounts[0])
      next.set("scope", context.data.accounts[0].id);
    const sourcePeriods = context.data.source_periods[next.get("scope") ?? ""] ?? [];
    const defaultPeriod =
      params.get("period") === "history" ? sourcePeriods.at(-1) : context.data.default_period;
    if (!params.has("start") && !params.has("end") && defaultPeriod) {
      next.set("start", defaultPeriod.start);
      next.set("end", defaultPeriod.end);
      next.delete("period");
    }
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
  }, [context.data, context.isError, context.isFetching, params, setParams]);
  const overview = useQuery({
    queryKey: ["returns", "overview", scope, period.start, period.end],
    queryFn: ({ signal }) => getOverview(scope, period, signal),
    enabled: selectionValid && !context.isError && !context.isFetching,
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
    ...(context.data?.closed_periods ?? []),
    ...(context.data?.source_periods[scope] ?? []),
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
        <div className={styles.controls}>
          <label>
            Счёт
            <select
              aria-label="Счёт"
              value={scope}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("scope", e.target.value);
                setParams(next);
              }}
            >
              <option value="" disabled>
                Выберите счёт
              </option>
              {["statements", "accepted"].map((basis) => (
                <optgroup
                  key={basis}
                  label={basis === "statements" ? "По выпискам" : "Подтверждённые отчёты"}
                >
                  {context.data?.accounts
                    .filter((a) => a.basis === basis)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label}
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
            <div className={styles.cards}>
              <section
                className={`${styles.card} ${styles.primaryCard}`}
                aria-label="Результат периода"
              >
                <h2>Результат периода</h2>
                <div className={styles.mainValue}>
                  <Value metric={data.selected.pnl} label="Результат периода" signed />
                </div>
                <Value metric={data.selected.rate} label="Доходность периода" />
                <small>{periodLabel(data.selected.period)}</small>
              </section>
              <section className={styles.card} aria-label="За всю историю">
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
            <ReturnsHistory key={scope} rows={data.history} selected={period} choose={choose} />
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
