import { lazy, type MouseEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { ConfirmDialog } from "../components/ui";
import { UiV2Shell } from "./UiV2Shell";
import { getOverall, accountHref, type GoldTarget } from "./returns/overall";
import { compareDecimal, dateLabel, displayMetric, periodLabel } from "./returns/model";
import {
  brokerageResult,
  compactQuantity,
  instrumentSummary,
  readDisplayNames,
  saveDisplayNames,
  selectedAccounts,
  selectedIncome,
} from "./returns/dashboard";
import { capitalGoldTarget, goldTargets } from "./returns/navigation";
import { ReturnsCouponIncome } from "./returns/ReturnsCouponIncome";
import styles from "./returns/Returns.module.css";
import layout from "./returns/Dashboard.module.css";

const ReturnsGoldHistory = lazy(() =>
  import("./returns/ReturnsGoldHistory").then((m) => ({ default: m.ReturnsGoldHistory })),
);

export default function UiV2ReturnsPage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [names, setNames] = useState(readDisplayNames);
  const [goldEditorTarget, setGoldEditorTarget] = useState<GoldTarget | null>(null);
  const [goldNavigation, setGoldNavigation] = useState({ dirty: false, pending: false });
  const [nextParams, setNextParams] = useState<URLSearchParams | null>(null);
  const [nextHref, setNextHref] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["returns", "overall", "summaries"],
    queryFn: ({ signal }) => getOverall(signal, true),
    staleTime: 0,
  });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  const scope =
    params.getAll("accounts").length > 1 ? "invalid" : (params.get("accounts") ?? "all");
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "pnl-desc";
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
          ? a.isin.localeCompare(b.isin)
          : a.pnl.value === null
            ? 1
            : -1
        : compareDecimal(a.pnl.value, b.pnl.value) * (sort === "pnl-asc" ? 1 : -1),
  );
  const instrumentHref = (isin: string) =>
    `/v2/returns/instrument/${isin}?${new URLSearchParams({ back: `${location.pathname}${location.search}` })}`;
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
  const chartRows = rows
    .flatMap((r) =>
      r.pnl.value !== null && r.pnl.value !== "0" ? [{ ...r, cash: BigInt(r.pnl.value) }] : [],
    )
    .sort(
      (a, b) =>
        compareDecimal(
          (a.cash < 0n ? -a.cash : a.cash).toString(),
          (b.cash < 0n ? -b.cash : b.cash).toString(),
        ) * -1,
    )
    .slice(0, 6);
  const maximum = chartRows.reduce((m, r) => {
    const v = r.cash;
    const abs = v < 0n ? -v : v;
    return abs > m ? abs : m;
  }, 1n);
  return (
    <div className={styles.page}>
      <UiV2Shell
        active="returns"
        busy={query.isFetching}
        header={
          <div className={styles.titleRow}>
            <div>
              <p className={styles.eyebrow}>Инвестиции</p>
              <h1>Доходность</h1>
            </div>
            <button
              type="button"
              disabled={query.isFetching}
              onClick={() => void queryClient.invalidateQueries({ queryKey: ["returns"] })}
            >
              Обновить
            </button>
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
              <label>
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
              <span className={layout.note}>Вся доступная история · проданные бумаги включены</span>
            </div>
            <details className={layout.names}>
              <summary>Названия счетов</summary>
              <p className={layout.note}>Только для отображения в этом браузере.</p>
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
            </details>
            {accounts.length === 0 ? (
              <p role="alert">Выбранный счёт недоступен. Выберите другой счёт.</p>
            ) : (
              <>
                {(result?.partial ||
                  (["coupon", "dividend"] as const).some(
                    (k) => selectedIncome(data, scope, k).included_accounts < accounts.length,
                  )) && (
                  <p className={layout.notice} role="status">
                    Часть истории не подтверждена. Ниже показаны известные суммы; они не являются
                    полным результатом.
                  </p>
                )}
                <div className={styles.cards}>
                  {result && result.amount.value !== null && (
                    <section
                      className={`${styles.card} ${styles.primaryCard}`}
                      aria-label="Результат"
                    >
                      <h2>Результат за доступную историю</h2>
                      <div className={layout.value}>{displayMetric(result.amount, true)}</div>
                      <small>По выбранным брокерским счетам</small>
                    </section>
                  )}
                  {(["coupon", "dividend"] as const).map((incomeKind) => {
                    const income = selectedIncome(data, scope, incomeKind);
                    return income.known_total.value !== null && income.known_total.value !== "0" ? (
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
                  {accounts.length === 1 &&
                    accounts[0].result &&
                    accounts[0].result.rate.value !== null && (
                      <section className={styles.card} aria-label="Доходность периода">
                        <h2>Modified Dietz за период</h2>
                        <div className={layout.value}>{displayMetric(accounts[0].result.rate)}</div>
                        <small>
                          {accounts[0].period && periodLabel(accounts[0].period)} · не годовая
                        </small>
                      </section>
                    )}
                </div>
                <div className={layout.accounts}>
                  {accounts.map((a) => (
                    <div className={layout.account} key={a.scope}>
                      <Link
                        to={accountHref(a.scope, a.period)}
                        onClick={(e) => guardLink(e, accountHref(a.scope, a.period))}
                      >
                        {label(a.scope, a.label)}
                      </Link>
                      {a.result && a.result.pnl.value !== null ? (
                        <strong>{displayMetric(a.result.pnl, true)}</strong>
                      ) : (
                        <p>
                          {a.proof_status === "stale"
                            ? "Нужно заново подтвердить выписки"
                            : "Результат пока не подтверждён"}
                        </p>
                      )}
                      <small>{a.period && periodLabel(a.period)}</small>
                      {accounts.length > 1 && a.result && a.result.rate.value !== null && (
                        <small>Modified Dietz {displayMetric(a.result.rate)} за этот период</small>
                      )}
                    </div>
                  ))}
                </div>
                <p className={layout.note}>
                  Расчёт по сохранённым выпискам. Общий процент для разных периодов счетов не
                  складывается; выплаты уже входят в результат.
                </p>
                {chartRows.length > 0 && (
                  <section className={styles.panel} aria-label="Вклад инструментов">
                    <div className={layout.heading}>
                      <h2>Вклад инструментов</h2>
                      <span className={layout.note}>Результат в рублях за доступную историю</span>
                    </div>
                    <div className={layout.plot}>
                      {chartRows.map((r) => {
                        const v = r.cash;
                        return (
                          <div className={layout.barRow} key={r.isin}>
                            <Link
                              to={instrumentHref(r.isin)}
                              onClick={(e) => guardLink(e, instrumentHref(r.isin))}
                            >
                              {r.name}
                            </Link>
                            <div className={layout.barTrack} aria-hidden="true">
                              <div
                                className={`${layout.bar} ${v < 0n ? layout.negative : ""}`}
                                style={{
                                  width: `${Number(((v < 0n ? -v : v) * 10000n) / maximum) / 100}%`,
                                }}
                              />
                            </div>
                            <strong>{displayMetric(r.pnl, true)}</strong>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}
                <section className={styles.panel} aria-labelledby="returns-instruments">
                  <div className={layout.heading}>
                    <h2 id="returns-instruments">По инструментам</h2>
                    <span className={layout.note}>{rows.length} бумаг</span>
                  </div>
                  <div className={styles.filters}>
                    <label>
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
                        <option value="pnl-desc">Результат: больше</option>
                        <option value="pnl-asc">Результат: меньше</option>
                        <option value="name">Название</option>
                      </select>
                    </label>
                  </div>
                  {rows.length > 0 ? (
                    <div className={styles.tableScroll}>
                      <table className={`${styles.instruments} ${layout.list}`}>
                        <thead>
                          <tr>
                            <th>Инструмент</th>
                            <th>Результат</th>
                            <th>Полученный доход</th>
                            {accounts.length === 1 && <th>Modified Dietz</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((r) => (
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
                                {r.pnl.value !== null ? (
                                  <>
                                    {displayMetric(r.pnl, true)}
                                    {r.partial && (
                                      <small className={layout.muted}>Известная часть</small>
                                    )}
                                  </>
                                ) : (
                                  <span className={layout.muted}>Нужна проверка данных</span>
                                )}
                              </td>
                              <td>
                                {r.coupons.value !== null && r.coupons.value !== "0" && (
                                  <div>Купоны {displayMetric(r.coupons)}</div>
                                )}
                                {r.dividends.value !== null && r.dividends.value !== "0" && (
                                  <div>Дивиденды {displayMetric(r.dividends)}</div>
                                )}
                              </td>
                              {accounts.length === 1 && (
                                <td>
                                  {r.rate.value !== null && (
                                    <>
                                      {displayMetric(r.rate)}
                                      <small className={layout.muted}>За период, не годовой</small>
                                    </>
                                  )}
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p>Бумаги не найдены.</p>
                  )}
                </section>
                {rows.some((r) => r.pnl.value !== null && r.pnl.value !== "0") && (
                  <section className={styles.panel} aria-label="Лидеры и отстающие">
                    <h2>Лидеры и отстающие</h2>
                    <div className={styles.cards}>
                      {([true, false] as const)
                        .filter((positive) =>
                          rows.some(
                            (r) =>
                              r.pnl.value !== null &&
                              compareDecimal(r.pnl.value, "0") === (positive ? 1 : -1),
                          ),
                        )
                        .map((positive) => (
                          <div key={String(positive)}>
                            <h3>{positive ? "Наибольший доход" : "Наибольший убыток"}</h3>
                            <ol>
                              {rows
                                .filter(
                                  (r) =>
                                    r.pnl.value !== null &&
                                    compareDecimal(r.pnl.value, "0") === (positive ? 1 : -1),
                                )
                                .sort(
                                  (a, b) =>
                                    compareDecimal(a.pnl.value ?? "0", b.pnl.value ?? "0") *
                                    (positive ? -1 : 1),
                                )
                                .slice(0, 5)
                                .map((r) => (
                                  <li key={r.isin}>
                                    <Link
                                      to={instrumentHref(r.isin)}
                                      onClick={(e) => guardLink(e, instrumentHref(r.isin))}
                                    >
                                      {r.name}
                                    </Link>{" "}
                                    {displayMetric(r.pnl, true)}
                                  </li>
                                ))}
                            </ol>
                          </div>
                        ))}
                    </div>
                  </section>
                )}
              </>
            )}
            {goldTargets(data).length > 0 && (
              <section className={styles.panel} id="returns-gold" aria-label="Золото">
                <h2>Золото</h2>
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
                      </dl>
                      {!history && (
                        <p className={layout.note}>
                          Для результата с учётом продаж нужна история операций. Оценка остатка
                          показана отдельно и не добавлена к брокерскому результату.
                        </p>
                      )}
                      <button
                        type="button"
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
        {goldEditorTarget && (
          <Suspense fallback={<p role="status">Открываем историю золота…</p>}>
            <ReturnsGoldHistory
              key={`${goldEditorTarget.account_id}/${goldEditorTarget.instrument_id}`}
              accountId={goldEditorTarget.account_id}
              instrumentId={goldEditorTarget.instrument_id}
              targetLabel={goldEditorTarget.label}
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
