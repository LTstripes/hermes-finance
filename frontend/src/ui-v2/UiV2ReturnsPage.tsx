import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, type MouseEvent, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { ConfirmDialog } from "../components/ui";
import sheet from "./ReportSheet.module.css";
import { positionRateMetric } from "./returns/cards";
import layout from "./returns/Dashboard.module.css";
import {
  brokerageResult,
  compactQuantity,
  instrumentSummary,
  readDisplayNames,
  saveDisplayNames,
  selectedAccounts,
  selectedIncome,
} from "./returns/dashboard";
import resultStyles from "./returns/InstrumentResult.module.css";
import {
  compareDecimal,
  dateLabel,
  displayMetric,
  displayWhole,
  isPartialResult,
  periodLabel,
  tone,
} from "./returns/model";
import { capitalGoldTarget, goldTargets } from "./returns/navigation";
import { accountHref, type GoldTarget, getOverall } from "./returns/overall";
import styles from "./returns/Returns.module.css";
import { ReturnsCouponIncome } from "./returns/ReturnsCouponIncome";
import { MissingMetricNote } from "./returns/ReturnsInfo";
import { ReturnsInstrumentResult } from "./returns/ReturnsInstrumentResult";
import { ReturnsResultMeta } from "./returns/ReturnsResultMeta";
import { UiV2Shell } from "./UiV2Shell";

const ReturnsGoldHistory = lazy(() =>
  import("./returns/ReturnsGoldHistory").then((m) => ({ default: m.ReturnsGoldHistory })),
);

const RETURNS_DATA_HREF = "/v2/returns/account?scope=portfolio&diagnostics=performance";

export default function UiV2ReturnsPage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [names, setNames] = useState(readDisplayNames);
  const [showAllInstruments, setShowAllInstruments] = useState(false);
  const [goldEditorTarget, setGoldEditorTarget] = useState<GoldTarget | null>(null);
  const [goldNavigation, setGoldNavigation] = useState({ dirty: false, pending: false });
  const [nextParams, setNextParams] = useState<URLSearchParams | null>(null);
  const [nextHref, setNextHref] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["returns", "overall", "summaries"],
    queryFn: ({ signal }) => getOverall(signal, true),
    staleTime: 5 * 60 * 1000,
  });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  const scope =
    params.getAll("accounts").length > 1 ? "invalid" : (params.get("accounts") ?? "all");
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "pnl-absolute";
  const kind = params.get("kind") ?? "all";
  const label = (s: string, fallback: string) => names[s] || fallback;
  const change = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(updates)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    if (goldNavigation.dirty || goldNavigation.pending) {
      setNextParams(next);
      return;
    }
    setParams(next);
  };
  const target = useMemo(() => (data ? capitalGoldTarget(data, params) : null), [data, params]);
  useEffect(() => {
    if (goldNavigation.dirty || goldNavigation.pending) return;
    if (target) setGoldEditorTarget(target);
    else if (data) setGoldEditorTarget(null);
  }, [target, data, goldNavigation.dirty, goldNavigation.pending]);
  const accounts = data ? selectedAccounts(data, scope) : [];
  const result = data ? brokerageResult(data, scope) : null;
  const rows = data
    ? data.instruments
        .map((r) => instrumentSummary(data, r, scope))
        .filter(
          (r) =>
            r.accounts.length &&
            (kind === "all" || r.kind === kind) &&
            `${r.name} ${r.isin}`.toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru")),
        )
    : [];
  rows.sort((a, b) =>
    sort === "name"
      ? a.name.localeCompare(b.name, "ru")
      : a.pnl.value === null || b.pnl.value === null
        ? a.pnl.value === b.pnl.value
          ? a.name.localeCompare(b.name, "ru")
          : a.pnl.value === null
            ? 1
            : -1
        : sort === "pnl-absolute"
          ? compareDecimal(a.pnl.value.replace(/^-/, ""), b.pnl.value.replace(/^-/, "")) * -1 ||
            a.name.localeCompare(b.name, "ru")
          : compareDecimal(a.pnl.value, b.pnl.value) * (sort === "pnl-asc" ? 1 : -1),
  );
  const instrumentHref = (isin: string) => {
    const next = new URLSearchParams({ back: `${location.pathname}${location.search}` });
    if (scope !== "all") {
      next.set("detail_scope", scope);
      const period = rows
        .find((row) => row.isin === isin)
        ?.accounts.find((a) => a.scope === scope)?.period;
      if (period) {
        next.set("detail_start", period.start);
        next.set("detail_end", period.end);
      } else {
        // A missing overview period is not authority to substitute another interval.
        next.set("detail_start", "unavailable");
        next.set("detail_end", "unavailable");
      }
    }
    return `/v2/returns/instrument/${isin}?${next}`;
  };
  const summaryAccountHref = (accountScope: string) => {
    const next = new URLSearchParams(params);
    next.set("accounts", accountScope);
    return `/v2/returns?${next}`;
  };
  const openInstrument = (isin: string) => {
    if (goldNavigation.dirty || goldNavigation.pending) setNextHref(instrumentHref(isin));
    else navigate(instrumentHref(isin));
  };
  const guardLink = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    if (goldNavigation.dirty || goldNavigation.pending) {
      event.preventDefault();
      setNextHref(href);
    }
  };
  // Leaders and laggards share one chart: only full results are ranked, partial ones stay in the table.
  const ranked = rows.filter(
    (r) => !isPartialResult(r.pnl) && r.pnl.value !== null && r.pnl.value !== "0",
  );
  const leaders = [true, false]
    .map((positive) => ({
      positive,
      items: ranked
        .filter((r) => compareDecimal(r.pnl.value ?? "0", "0") === (positive ? 1 : -1))
        .sort(
          (a, b) => compareDecimal(a.pnl.value ?? "0", b.pnl.value ?? "0") * (positive ? -1 : 1),
        )
        .slice(0, 5),
    }))
    .filter((group) => group.items.length > 0);
  const unranked = rows.filter((r) => isPartialResult(r.pnl)).length;
  const resultPeriods = new Set(
    rows
      .filter((row) => row.pnl.value !== null)
      .flatMap((row) =>
        row.accounts
          .filter((account) => account.resultAvailable && account.period)
          .map((account) => `${account.period?.start}/${account.period?.end}`),
      ),
  );
  const maximum = leaders
    .flatMap((group) => group.items)
    .reduce((m, r) => {
      const v = BigInt(r.pnl.value ?? "0");
      const abs = v < 0n ? -v : v;
      return abs > m ? abs : m;
    }, 1n);
  const accountPeriods = new Set(
    accounts.filter((a) => a.period).map((a) => `${a.period?.start}/${a.period?.end}`),
  );
  const singlePeriod =
    accountPeriods.size === 1 && accounts[0]?.period ? periodLabel(accounts[0].period) : null;
  return (
    <div className={styles.page}>
      <UiV2Shell
        showRefresh={false}
        active="returns"
        busy={query.isFetching}
        header={
          <div className={sheet.titleRow}>
            <h1>Доходность</h1>
            <span className={layout.chip}>Вся доступная история · проданные бумаги включены</span>
            <span className={sheet.titleLinks}>
              <button
                type="button"
                className={layout.quiet}
                disabled={query.isFetching}
                onClick={() => void queryClient.invalidateQueries({ queryKey: ["returns"] })}
              >
                Обновить
              </button>
            </span>
          </div>
        }
      >
        {query.isError ? (
          <p role="alert">
            Не удалось загрузить доходность.{" "}
            <button type="button" onClick={() => void query.refetch()}>
              Повторить
            </button>
          </p>
        ) : query.isFetching ? (
          <p role="status">Загружаем доходность…</p>
        ) : null}
        {data && (
          <>
            <div className={layout.toolbar}>
              <label className={sheet.select}>
                Счета
                <select
                  aria-label="Счета"
                  value={scope}
                  onChange={(e) =>
                    change({ accounts: e.target.value === "all" ? null : e.target.value })
                  }
                >
                  <option value="all">Все счета</option>
                  {data.source_accounts.map((a) => (
                    <option key={a.scope} value={a.scope}>
                      {label(a.scope, a.label)}
                    </option>
                  ))}
                </select>
              </label>
              <details className={layout.names}>
                <summary>Названия счетов</summary>
                <div className={layout.namesPanel}>
                  <p className={sheet.muted}>Только для отображения в этом браузере.</p>
                  {data.source_accounts.map((a) => (
                    <label key={a.scope}>
                      {a.label}
                      <input
                        aria-label={`Название: ${a.label}`}
                        maxLength={80}
                        value={names[a.scope] ?? ""}
                        placeholder={a.label}
                        onChange={(e) => {
                          const next = { ...names, [a.scope]: e.target.value };
                          setNames(next);
                          saveDisplayNames(next);
                        }}
                      />
                    </label>
                  ))}
                </div>
              </details>
            </div>
            {accounts.length === 0 ? (
              <p role="alert">Выбранный счёт недоступен. Выберите другой счёт.</p>
            ) : (
              <>
                <div className={layout.lead}>
                  <div className={layout.leadMain}>
                    {result && result.amount.value !== null && (
                      <section className={layout.total} aria-label="Результат">
                        <h2 className={sheet.eyebrow}>Сумма по бумагам за доступную историю</h2>
                        <strong className={sheet.hero} title={displayMetric(result.amount, true)}>
                          {displayWhole(result.amount, true)}
                        </strong>
                        <small className={sheet.muted}>
                          {accounts.length > 1 ? "По выбранным счетам" : "По счёту"}
                          {singlePeriod ? ` · ${singlePeriod}` : " за совпадающий период"}
                        </small>
                        {result.partial && (
                          <p className={layout.caveat}>Учтены не все составляющие результата</p>
                        )}
                      </section>
                    )}
                    <div className={layout.figures}>
                      {accounts.length === 1 &&
                        accounts[0].result &&
                        accounts[0].result.rate.value !== null && (
                          <section className={layout.figure} aria-label="Доходность периода">
                            <h2>Modified Dietz за период</h2>
                            <strong data-tone={tone(accounts[0].result.rate)}>
                              {displayMetric(accounts[0].result.rate)}
                            </strong>
                            <small>
                              {accounts[0].period && periodLabel(accounts[0].period)} · не годовая
                            </small>
                          </section>
                        )}
                      {(["coupon", "dividend"] as const).map((incomeKind) => {
                        const income = selectedIncome(data, scope, incomeKind);
                        return income.known_total.value !== null &&
                          income.known_total.value !== "0" ? (
                          <ReturnsCouponIncome
                            key={incomeKind}
                            compact
                            value={income}
                            kind={incomeKind}
                            revision={query.dataUpdatedAt}
                            scopes={accounts.map((a) => a.scope)}
                            openInstrument={openInstrument}
                          />
                        ) : null;
                      })}
                    </div>
                  </div>
                  <ul className={layout.accounts} aria-label="Счета">
                    {accounts.map((a) => (
                      <li className={layout.account} key={a.scope}>
                        <Link
                          to={
                            accounts.length > 1
                              ? summaryAccountHref(a.scope)
                              : accountHref(a.scope, a.period)
                          }
                          onClick={(e) =>
                            guardLink(
                              e,
                              accounts.length > 1
                                ? summaryAccountHref(a.scope)
                                : accountHref(a.scope, a.period),
                            )
                          }
                        >
                          {accounts.length > 1 ? label(a.scope, a.label) : "Результаты по месяцам"}
                        </Link>
                        {accounts.length > 1 && a.result && a.result.pnl.value !== null ? (
                          <strong
                            title={displayMetric(a.result.pnl, true)}
                            data-tone={tone(a.result.pnl)}
                          >
                            {displayWhole(a.result.pnl, true)}
                            {isPartialResult(a.result.pnl) && (
                              <>
                                <sup aria-hidden="true">*</sup>
                                <span className={sheet.visuallyHidden}>
                                  {" "}
                                  (известная часть, не полный итог)
                                </span>
                              </>
                            )}
                          </strong>
                        ) : !a.result || a.result.pnl.value === null ? (
                          <p>Пока нет результата по сохранённым данным</p>
                        ) : null}
                        {accounts.length > 1 && a.result && a.result.rate.value !== null && (
                          <small className={layout.accountRate}>
                            Modified Dietz {displayMetric(a.result.rate)} за этот период
                          </small>
                        )}
                        <ReturnsResultMeta
                          period={a.period}
                          valuationDate={a.valuation_date}
                          accountLink={a.account_link}
                        />
                      </li>
                    ))}
                    {accounts.length > 1 &&
                      accounts.some((a) => a.result && isPartialResult(a.result.pnl)) && (
                        <li className={layout.accountNote}>
                          * Сумма известных результатов бумаг счёта, не полный итог.
                        </li>
                      )}
                  </ul>
                </div>
                <p className={layout.note}>
                  Комиссии и налоги не входят в результат бумаг, НКД учтён в сделках облигаций,
                  полученные выплаты уже включены.
                  {accounts.length > 1 &&
                    " Общий процент для разных периодов счетов не складывается."}
                </p>
                {leaders.length > 0 && resultPeriods.size === 1 && (
                  <section className={layout.section} aria-label="Вклад инструментов">
                    <div className={sheet.sectionHead}>
                      <div>
                        <p className={sheet.eyebrow}>Лидеры и отстающие</p>
                        <h2>Вклад бумаг в результат</h2>
                      </div>
                      <span className={sheet.muted}>В рублях за доступную историю</span>
                    </div>
                    <div className={layout.leaders}>
                      {leaders.map(({ positive, items }) => (
                        <div className={layout.leaderGroup} key={String(positive)}>
                          <h3>{positive ? "Наибольший доход" : "Наибольший убыток"}</h3>
                          <ol className={layout.leaderList}>
                            {items.map((r, index) => {
                              const v = BigInt(r.pnl.value ?? "0");
                              return (
                                <li className={layout.leaderRow} key={r.isin}>
                                  <span className={layout.leaderRank} aria-hidden="true">
                                    {index + 1}
                                  </span>
                                  <Link
                                    to={instrumentHref(r.isin)}
                                    onClick={(e) => guardLink(e, instrumentHref(r.isin))}
                                  >
                                    {r.name}
                                  </Link>
                                  <span className={layout.barTrack} aria-hidden="true">
                                    <span
                                      className={layout.bar}
                                      data-tone={positive ? "positive" : "negative"}
                                      style={{
                                        width: `${Number(((v < 0n ? -v : v) * 10000n) / maximum) / 100}%`,
                                      }}
                                    />
                                  </span>
                                  <strong
                                    className={layout.leaderAmount}
                                    title={displayMetric(r.pnl, true)}
                                  >
                                    {displayWhole(r.pnl, true)}
                                  </strong>
                                </li>
                              );
                            })}
                          </ol>
                        </div>
                      ))}
                    </div>
                    {unranked > 0 && (
                      <p className={layout.note}>
                        Бумаги с неполным итогом ({unranked}) не ранжируются, они есть в таблице
                        ниже.
                      </p>
                    )}
                  </section>
                )}
                <section className={layout.section} aria-labelledby="returns-instruments">
                  <div className={sheet.sectionHead}>
                    <h2 id="returns-instruments">Доходность по инструментам ({rows.length})</h2>
                  </div>
                  <div className={layout.filters}>
                    <label className={layout.search}>
                      Поиск
                      <input
                        type="search"
                        value={search}
                        placeholder="Название или ISIN"
                        onChange={(e) => change({ q: e.target.value || null })}
                      />
                    </label>
                    <label>
                      Тип
                      <select
                        value={kind}
                        onChange={(e) =>
                          change({ kind: e.target.value === "all" ? null : e.target.value })
                        }
                      >
                        <option value="all">Все бумаги</option>
                        <option value="stock">Акции</option>
                        <option value="bond">Облигации</option>
                      </select>
                    </label>
                    <label>
                      Сортировка
                      <select value={sort} onChange={(e) => change({ sort: e.target.value })}>
                        <option value="pnl-absolute">Результат: по величине</option>
                        <option value="pnl-desc">Результат: больше</option>
                        <option value="pnl-asc">Результат: меньше</option>
                        <option value="name">Название</option>
                      </select>
                    </label>
                  </div>
                  {rows.length > 0 ? (
                    <div className={styles.tableScroll}>
                      <table
                        className={`${styles.instruments} ${layout.list} ${resultStyles.list}`}
                      >
                        <thead>
                          <tr>
                            <th>Инструмент</th>
                            <th>Сумма по данным</th>
                            <th>Полученный доход</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(showAllInstruments ? rows : rows.slice(0, 5)).map((r) => (
                            <tr key={r.isin}>
                              <th>
                                <Link
                                  to={instrumentHref(r.isin)}
                                  onClick={(e) => guardLink(e, instrumentHref(r.isin))}
                                >
                                  {r.name}
                                </Link>
                                <small>
                                  {r.kind === "bond"
                                    ? "Облигация"
                                    : r.kind === "stock"
                                      ? "Акция"
                                      : r.isin}
                                </small>
                              </th>
                              <td>
                                {r.accounts.map((a) => (
                                  <section
                                    className={layout.instrumentAccount}
                                    key={a.scope}
                                    aria-label={label(a.scope, a.label)}
                                  >
                                    <details>
                                      <summary>
                                        {scope === "all" && (
                                          <>
                                            <span className={layout.instrumentAccountName}>
                                              {label(a.scope, a.label)}
                                            </span>{" "}
                                            ·{" "}
                                          </>
                                        )}
                                        {a.resultAvailable ? (
                                          <>
                                            <strong
                                              title={displayMetric(a.pnl, true)}
                                              data-tone={tone(a.pnl)}
                                            >
                                              {displayWhole(a.pnl, true)}
                                              {isPartialResult(a.pnl) && (
                                                <>
                                                  <sup aria-hidden="true">*</sup>
                                                  <span className={sheet.visuallyHidden}>
                                                    {" "}
                                                    (известная часть, не полный итог)
                                                  </span>
                                                </>
                                              )}
                                            </strong>{" "}
                                            <span className={layout.rate}>
                                              ·{" "}
                                              {a.simple_return
                                                ? displayMetric(positionRateMetric(a.simple_return))
                                                : displayMetric(a.rate)}
                                              {a.xirr?.value != null &&
                                                ` · ${displayMetric(positionRateMetric(a.xirr))} годовых`}
                                            </span>
                                          </>
                                        ) : (
                                          "Нет доступного результата"
                                        )}
                                      </summary>
                                      <ReturnsInstrumentResult
                                        showMissingNote={false}
                                        result={a.resultAvailable ? a : null}
                                        positionRates={
                                          a.resultAvailable && a.simple_return
                                            ? { simple: a.simple_return, xirr: a.xirr ?? null }
                                            : null
                                        }
                                        reasonCodes={
                                          a.resultAvailable
                                            ? r.reason_codes
                                            : [
                                                ...(data.source_accounts.find(
                                                  (source) => source.scope === a.scope,
                                                )?.reason_codes ?? []),
                                                "all_history_source_proof_unavailable",
                                              ]
                                        }
                                      />
                                      <ReturnsResultMeta
                                        period={a.period}
                                        valuationDate={a.valuation_date}
                                        accountLink={a.account_link}
                                      />
                                    </details>
                                    {a.resultAvailable && (
                                      <MissingMetricNote
                                        metrics={[
                                          a.pnl,
                                          a.simple_return
                                            ? positionRateMetric(a.simple_return)
                                            : a.rate,
                                        ]}
                                      />
                                    )}
                                  </section>
                                ))}
                              </td>
                              <td>
                                {r.coupons.value !== null && r.coupons.value !== "0" && (
                                  <div>
                                    Купоны{" "}
                                    <span title={displayMetric(r.coupons)}>
                                      {displayWhole(r.coupons)}
                                    </span>
                                  </div>
                                )}
                                {r.dividends.value !== null && r.dividends.value !== "0" && (
                                  <div>
                                    Дивиденды{" "}
                                    <span title={displayMetric(r.dividends)}>
                                      {displayWhole(r.dividends)}
                                    </span>
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {rows.some((r) => r.accounts.some((a) => isPartialResult(a.pnl))) && (
                        <p className={layout.note}>* Учтены не все составляющие результата.</p>
                      )}
                    </div>
                  ) : (
                    <p>Бумаги не найдены.</p>
                  )}
                  {rows.length > 5 && (
                    <button
                      type="button"
                      className={layout.more}
                      onClick={() => setShowAllInstruments((shown) => !shown)}
                    >
                      {showAllInstruments ? "Свернуть" : "Показать все"}
                    </button>
                  )}
                </section>
              </>
            )}
            {goldTargets(data).length > 0 && (
              <section className={layout.section} id="returns-gold" aria-label="Золото">
                <div className={sheet.sectionHead}>
                  <div>
                    <p className={sheet.eyebrow}>Отдельно от бумаг</p>
                    <h2>Золото</h2>
                  </div>
                </div>
                {goldTargets(data).map((item) => {
                  const snapshot = data.gold.snapshots.find(
                    (s) =>
                      s.account_id === item.account_id && s.instrument_id === item.instrument_id,
                  );
                  const history = data.gold.histories?.find(
                    (s) =>
                      s.account_id === item.account_id && s.instrument_id === item.instrument_id,
                  );
                  return (
                    <div key={`${item.account_id}/${item.instrument_id}`}>
                      {goldTargets(data).length > 1 && <h3>{item.label}</h3>}
                      <dl className={layout.compact}>
                        {snapshot && (
                          <>
                            <div>
                              <dt>Количество</dt>
                              <dd>{compactQuantity(snapshot.quantity)} г</dd>
                            </div>
                            <div>
                              <dt>Стоимость на {dateLabel(snapshot.date)}</dt>
                              <dd>{displayMetric(snapshot.market_value)}</dd>
                            </div>
                          </>
                        )}
                        {history?.total_result.value != null ? (
                          <div>
                            <dt>Общий результат</dt>
                            <dd>{displayMetric(history.total_result, true)}</dd>
                          </div>
                        ) : (
                          snapshot?.unrealized_result.value != null && (
                            <div>
                              <dt>Рост стоимости остатка</dt>
                              <dd>{displayMetric(snapshot.unrealized_result, true)}</dd>
                            </div>
                          )
                        )}
                        {history?.realized_result.value != null && (
                          <div>
                            <dt>Результат продаж</dt>
                            <dd>{displayMetric(history.realized_result, true)}</dd>
                          </div>
                        )}
                        {history?.total_result.value != null &&
                          history.unrealized_result.value != null && (
                            <div>
                              <dt>Рост стоимости остатка</dt>
                              <dd>{displayMetric(history.unrealized_result, true)}</dd>
                            </div>
                          )}
                        {!history && snapshot?.cost_return.value != null && (
                          <div>
                            <dt>К затратам по снимку</dt>
                            <dd>{displayMetric(snapshot.cost_return)}</dd>
                          </div>
                        )}
                      </dl>
                      {!history && (
                        <p className={layout.note}>
                          Для результата с учётом продаж нужна история операций. Оценка остатка
                          показана отдельно и не добавлена к брокерскому результату.
                        </p>
                      )}
                      <button
                        type="button"
                        className={layout.more}
                        disabled={goldNavigation.pending}
                        onClick={() =>
                          change({
                            capital_account: String(item.account_id),
                            gold_instrument: String(item.instrument_id),
                          })
                        }
                      >
                        История покупок и продаж
                      </button>
                    </div>
                  );
                })}
              </section>
            )}
          </>
        )}
        <details className={layout.footer}>
          <summary>Подробнее о данных</summary>
          <Link to={RETURNS_DATA_HREF} onClick={(event) => guardLink(event, RETURNS_DATA_HREF)}>
            Проверить данные расчёта
          </Link>
        </details>
        {goldEditorTarget && (
          <Suspense fallback={<p role="status">Открываем историю золота…</p>}>
            <ReturnsGoldHistory
              key={`${goldEditorTarget.account_id}/${goldEditorTarget.instrument_id}`}
              accountId={goldEditorTarget.account_id}
              instrumentId={goldEditorTarget.instrument_id}
              targetLabel={goldEditorTarget.label}
              cleanResult={
                data?.gold.histories?.find(
                  (history) =>
                    history.account_id === goldEditorTarget.account_id &&
                    history.instrument_id === goldEditorTarget.instrument_id,
                )?.total_result
              }
              onNavigationStateChange={setGoldNavigation}
              refreshing={query.isFetching || query.isError}
              revision={query.dataUpdatedAt}
              onConfirmed={async () => {
                await queryClient.invalidateQueries({ queryKey: ["returns"] });
              }}
            />
          </Suspense>
        )}
        <ConfirmDialog
          open={nextParams !== null || nextHref !== null}
          title="История золота"
          description={
            goldNavigation.pending
              ? "Подтверждение отправлено. Дождитесь результата."
              : "Есть несохранённые изменения. Уйти и потерять их?"
          }
          cancelLabel="Остаться"
          confirmLabel={goldNavigation.pending ? "Остаться в форме" : "Уйти без сохранения"}
          onCancel={() => {
            setNextParams(null);
            setNextHref(null);
          }}
          onConfirm={() => {
            if (!goldNavigation.pending && (nextParams || nextHref)) {
              setGoldEditorTarget(null);
              setGoldNavigation({ dirty: false, pending: false });
              if (nextParams) setParams(nextParams);
              else if (nextHref) navigate(nextHref);
            }
            setNextParams(null);
            setNextHref(null);
          }}
        />
      </UiV2Shell>
    </div>
  );
}
