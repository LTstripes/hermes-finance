import { rememberInstrumentScroll } from "./instrumentScroll";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, type MouseEvent, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { ConfirmDialog } from "../components/ui";
import { reasonCopy } from "../lib/reasonCopy";
import { shortInstrumentName } from "./instrumentName";
import sheet from "./ReportSheet.module.css";
import { positionRateMetric, positionRatePeriod } from "./returns/cards";
import layout from "./returns/Dashboard.module.css";
import {
  brokerageResult,
  compactQuantity,
  instrumentSummary,
  selectedAccounts,
  selectedIncome,
} from "./returns/dashboard";
import {
  compareDecimal,
  dateLabel,
  displayMetric,
  displayCompactRate,
  displayWhole,
  isPartialResult,
  periodLabel,
  tone,
  unavailable,
} from "./returns/model";
import { capitalGoldTarget, goldTargets } from "./returns/navigation";
import { accountHref, type GoldTarget, getOverall } from "./returns/overall";
import styles from "./returns/Returns.module.css";
import { ReturnsCouponIncome } from "./returns/ReturnsCouponIncome";
import { useAccountName } from "./returns/useAccountName";
import { useReturnsInvalidated } from "./returns/useReturnsInvalidated";
import { UiV2Shell } from "./UiV2Shell";
import { UiV2Skeleton } from "./UiV2StateBlocks";
import { UiV2Tabs } from "./UiV2Tabs";

const ReturnsGoldHistory = lazy(() =>
  import("./returns/ReturnsGoldHistory").then((m) => ({ default: m.ReturnsGoldHistory })),
);

const RETURNS_DATA_HREF = "/v2/returns/account?scope=portfolio&diagnostics=performance";

const accountCount = (count: number) =>
  `${count} ${count % 10 === 1 && count % 100 !== 11 ? "счёт" : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100) ? "счёта" : "счетов"}`;

function InstrumentIncome({
  account,
  kind,
}: {
  account: Pick<ReturnType<typeof instrumentSummary>, "coupons" | "dividends"> & {
    resultAvailable: boolean;
  };
  kind: string | null;
}) {
  if (!account.resultAvailable) return <>—</>;
  const income = (
    [
      ["Купоны", "куп.", account.coupons],
      ["Дивиденды", "див.", account.dividends],
    ] as const
  ).filter(
    ([label, , metric]) =>
      metric.value !== null &&
      !(
        metric.value === "0" &&
        ((kind === "stock" && label === "Купоны") || (kind === "bond" && label === "Дивиденды"))
      ),
  );
  return income.length ? (
    income.map(([label, short, metric]) => (
      <div key={label} title={`${label}: ${displayMetric(metric)}`}>
        {metric.value === "0" ? (
          <span className={layout.muted}>0</span>
        ) : (
          <>
            {displayWhole(metric)} <small className={layout.payoutLabel}>{short}</small>
          </>
        )}
      </div>
    ))
  ) : (
    <>—</>
  );
}

export default function UiV2ReturnsPage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const showAllInstruments = params.get("show") === "all";
  const [goldEditorTarget, setGoldEditorTarget] = useState<GoldTarget | null>(null);
  const [goldNavigation, setGoldNavigation] = useState({ dirty: false, pending: false });
  const [nextParams, setNextParams] = useState<URLSearchParams | null>(null);
  const [nextHref, setNextHref] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["returns", "overall", "summaries"],
    queryFn: ({ signal }) => getOverall(signal, true),
    staleTime: 5 * 60 * 1000,
  });
  const invalidated = useReturnsInvalidated(["returns", "overall", "summaries"]);
  const data = !invalidated && !query.isError ? query.data : undefined;
  const scope =
    params.getAll("accounts").length > 1 ? "invalid" : (params.get("accounts") ?? "all");
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "pnl-absolute";
  const kind = params.get("kind") ?? "all";
  const catalogueName = useAccountName(data?.source_accounts.map((a) => a.account_link) ?? []);
  const label = (scope: string, fallback: string) => {
    const account = data?.source_accounts.find((account) => account.scope === scope);
    return catalogueName(account?.account_link, fallback);
  };
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
  const incomeCaveat = data
    ? (["coupon", "dividend"] as const)
        .filter((kind) => selectedIncome(data, scope, kind).known_total.value !== null)
        .map(
          (kind) =>
            reasonCopy(
              kind === "coupon"
                ? "known_source_history_coupons_only"
                : "known_source_history_dividends_only",
              { surface: "returns" },
            ).message,
        )
        .join(" ")
    : "";
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
  const tableRows = rows.map((row) => {
    const accountRows = row.accounts.map((account) => ({
      ...row,
      name: shortInstrumentName({ name: row.name, isin: row.isin, ticker: null }),
      account,
      pnl: account.resultAvailable ? account.pnl : unavailable,
      simple:
        account.resultAvailable && account.simple_return
          ? positionRateMetric(account.simple_return)
          : { ...unavailable, unit: "fraction" as const },
      annual:
        account.resultAvailable && account.xirr
          ? positionRateMetric(account.xirr)
          : { ...unavailable, unit: "fraction" as const },
    }));
    const representative = [...accountRows].sort((a, b) => {
      const x = a.pnl.value;
      const y = b.pnl.value;
      if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
      return -compareDecimal(x.replace(/^-/, ""), y.replace(/^-/, ""));
    })[0];
    return {
      ...representative,
      ...row,
      name: shortInstrumentName({ name: row.name, isin: row.isin, ticker: null }),
      accountRows,
    };
  });
  tableRows.sort((a, b) => {
    if (sort === "name" || sort === "name-asc" || sort === "name-desc")
      return a.name.localeCompare(b.name, "ru") * (sort === "name-desc" ? -1 : 1);
    const field = sort.startsWith("rate-") ? "simple" : sort.startsWith("xirr-") ? "annual" : "pnl";
    const x = a[field].value;
    const y = b[field].value;
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return (
      compareDecimal(
        sort === "pnl-absolute" ? x.replace(/^-/, "") : x,
        sort === "pnl-absolute" ? y.replace(/^-/, "") : y,
      ) * (sort.endsWith("-asc") ? 1 : -1) || a.name.localeCompare(b.name, "ru")
    );
  });
  const annualReasons = new Map<string, number>();
  for (const row of tableRows.flatMap((row) => row.accountRows)) {
    if (row.annual.value !== null) continue;
    for (const code of new Set(row.account.xirr?.reason_codes ?? []))
      annualReasons.set(code, (annualReasons.get(code) ?? 0) + 1);
  }
  const annualReason = [...annualReasons].sort((a, b) => b[1] - a[1])[0]?.[0];
  const sortHeader = (field: string) =>
    change({
      sort: sort === `${field}-desc` ? `${field}-asc` : `${field}-desc`,
    });
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
    else {
      rememberInstrumentScroll();
      navigate(instrumentHref(isin), {
        state: { instrumentName: rows.find((r) => r.isin === isin)?.name },
      });
    }
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
            <span className={layout.chip}>
              Вся доступная история{singlePeriod ? ` · ${singlePeriod}` : ""}
            </span>
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
        <UiV2Tabs
          label="Разделы доходности"
          onNavigate={guardLink}
          tabs={[
            { label: "Обзор", to: "/v2/returns", active: true },
            { label: "По месяцам", to: "/v2/returns/account", active: false },
          ]}
        />
        {query.isError ? (
          <p role="alert">
            Не удалось загрузить доходность.{" "}
            <button type="button" onClick={() => void query.refetch()}>
              Повторить
            </button>
          </p>
        ) : query.isFetching && !data ? (
          <UiV2Skeleton label="Загружаем доходность…" expectedTime />
        ) : null}
        {query.isFetching && data && (
          <p role="status" className={layout.note}>
            Обновляем…
          </p>
        )}
        {data && (
          <>
            <div className={layout.toolbar}>
              {data.source_accounts.length <= 4 ? (
                <fieldset className={sheet.segmented} aria-label="Счета">
                  {[{ scope: "all", label: "Все счета" }, ...data.source_accounts].map(
                    (account) => (
                      <button
                        type="button"
                        key={account.scope}
                        aria-pressed={scope === account.scope}
                        title={
                          data.source_accounts.find((a) => a.scope === account.scope)?.account_link
                            ?.source_account_id
                        }
                        onClick={() =>
                          change({ accounts: account.scope === "all" ? null : account.scope })
                        }
                      >
                        {label(account.scope, account.label)}
                      </button>
                    ),
                  )}
                </fieldset>
              ) : (
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
                    {data.source_accounts.map((account) => (
                      <option
                        key={account.scope}
                        value={account.scope}
                        title={account.account_link?.source_account_id}
                      >
                        {label(account.scope, account.label)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            {accounts.length === 0 ? (
              <p role="alert">Выбранный счёт недоступен. Выберите другой счёт.</p>
            ) : (
              <>
                <div className={layout.lead}>
                  <div className={layout.leadMain}>
                    {result && result.amount.value !== null && (
                      <section className={layout.total} aria-label="Результат">
                        <h2 className={sheet.eyebrow}>Результат по бумагам</h2>
                        <strong className={sheet.hero} title={displayMetric(result.amount, true)}>
                          {displayWhole(result.amount, true)}
                        </strong>
                        <small className={sheet.muted}>
                          {accounts.length > 1 ? "По выбранным счетам" : "По счёту"}
                        </small>
                      </section>
                    )}
                    {(result?.partial || incomeCaveat) && (
                      <p className={layout.caveat}>
                        {result?.partial
                          ? reasonCopy(
                              result.amount.reason_codes[0] ?? "selected_components_incomplete",
                              { surface: "returns" },
                            ).message
                          : incomeCaveat}
                      </p>
                    )}
                    <div className={layout.figures}>
                      {accounts.length === 1 &&
                        accounts[0].result &&
                        accounts[0].result.rate.value !== null && (
                          <section className={layout.figure} aria-label="Доходность периода">
                            <h2>Modified Dietz за период</h2>
                            <strong data-tone={tone(accounts[0].result.rate)}>
                              {displayCompactRate(accounts[0].result.rate)}
                            </strong>
                            <small>не годовая</small>
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
                      {data.deposits.interest.value !== null && (
                        <section className={layout.figure} aria-label="Проценты по вкладам">
                          <h2>Проценты по вкладам</h2>
                          <strong title={displayMetric(data.deposits.interest)}>
                            {displayWhole(data.deposits.interest)}
                          </strong>
                          <small>вне бумаг</small>
                        </section>
                      )}
                    </div>
                  </div>
                  <ul className={layout.accounts} aria-label="Счета">
                    {accounts.map((a) => (
                      <li className={layout.account} key={a.scope}>
                        <Link
                          title={a.account_link?.source_account_id}
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
                          </strong>
                        ) : !a.result || a.result.pnl.value === null ? (
                          <p>Пока нет результата по сохранённым данным</p>
                        ) : null}
                        {accounts.length > 1 && a.result && a.result.rate.value !== null && (
                          <small className={layout.accountRate}>
                            Modified Dietz {displayCompactRate(a.result.rate)} за этот период
                          </small>
                        )}
                        {a.valuation_date && a.valuation_date !== a.period?.end && (
                          <small>Оценка на {dateLabel(a.valuation_date)}</small>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
                <details className={layout.note}>
                  <summary>Подробнее о расчёте</summary>
                  <p>
                    Комиссии и налоги не входят в результат бумаг, НКД учтён в сделках облигаций,
                    полученные выплаты уже включены.
                    {accounts.length > 1 &&
                      " Общий процент для разных периодов счетов не складывается."}
                  </p>
                </details>
                {leaders.length > 0 && resultPeriods.size === 1 && (
                  <section className={layout.section} aria-label="Вклад инструментов">
                    <div className={sheet.sectionHead}>
                      <div>
                        <p className={sheet.eyebrow}>Лидеры и отстающие</p>
                        <h2>Вклад бумаг в результат</h2>
                      </div>
                      <span className={sheet.muted}>
                        бумаг: в плюсе{" "}
                        {
                          rows.filter(
                            (r) =>
                              !isPartialResult(r.pnl) &&
                              r.pnl.value !== null &&
                              compareDecimal(r.pnl.value, "0") > 0,
                          ).length
                        }{" "}
                        · в минусе{" "}
                        {
                          rows.filter(
                            (r) =>
                              !isPartialResult(r.pnl) &&
                              r.pnl.value !== null &&
                              compareDecimal(r.pnl.value, "0") < 0,
                          ).length
                        }{" "}
                        · без итога{" "}
                        {rows.filter((r) => r.pnl.value === null || isPartialResult(r.pnl)).length}
                        {rows.some((r) => !isPartialResult(r.pnl) && r.pnl.value === "0") && (
                          <>
                            {" "}
                            · без изменения{" "}
                            {
                              rows.filter((r) => !isPartialResult(r.pnl) && r.pnl.value === "0")
                                .length
                            }
                          </>
                        )}
                      </span>
                    </div>
                    <ol className={layout.leaderList}>
                      {leaders.flatMap(({ positive, items }) =>
                        items.map((row) => {
                          const value = BigInt(row.pnl.value ?? "0");
                          return (
                            <li className={layout.leaderRow} key={row.isin}>
                              <Link
                                to={instrumentHref(row.isin)}
                                state={{ instrumentName: row.name }}
                                onClick={(e) => guardLink(e, instrumentHref(row.isin))}
                              >
                                {shortInstrumentName({
                                  name: row.name,
                                  isin: row.isin,
                                  ticker: null,
                                })}
                                {row.accounts.length > 1 && (
                                  <small className={layout.muted}>
                                    {" "}
                                    · {accountCount(row.accounts.length)}
                                  </small>
                                )}
                              </Link>
                              <span
                                className={layout.barTrack}
                                data-tone={positive ? "positive" : "negative"}
                                aria-hidden="true"
                              >
                                <span
                                  className={layout.bar}
                                  data-tone={positive ? "positive" : "negative"}
                                  style={{
                                    width: `${Number(((value < 0n ? -value : value) * 5000n) / maximum) / 100}%`,
                                  }}
                                />
                              </span>
                              <strong
                                className={layout.leaderAmount}
                                data-tone={tone(row.pnl)}
                                title={displayMetric(row.pnl, true)}
                              >
                                {displayWhole(row.pnl, true)}
                              </strong>
                            </li>
                          );
                        }),
                      )}
                    </ol>
                  </section>
                )}
                <section className={layout.section} aria-labelledby="returns-instruments">
                  <div className={sheet.sectionHead}>
                    <h2 id="returns-instruments">Все бумаги · {tableRows.length}</h2>
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
                  </div>
                  {tableRows.length > 0 ? (
                    <div className={styles.tableScroll}>
                      <table className={layout.list} aria-label="Все бумаги">
                        <colgroup>
                          <col />
                          <col />
                          <col />
                          <col />
                          <col />
                        </colgroup>
                        <thead>
                          <tr>
                            {[
                              ["name", "Бумага"],
                              ["pnl", "Результат, ₽"],
                              ["rate", "На вложенное"],
                              ["xirr", "Годовых"],
                            ].map(([field, title]) => (
                              <th
                                scope="col"
                                key={field}
                                aria-sort={
                                  sort.startsWith(field)
                                    ? sort.endsWith("-asc") || sort === "name"
                                      ? "ascending"
                                      : "descending"
                                    : "none"
                                }
                              >
                                <button
                                  type="button"
                                  title={
                                    field === "rate" || field === "xirr"
                                      ? "По значению счёта с наибольшим по модулю результатом бумаги; без значения — в конце"
                                      : undefined
                                  }
                                  onClick={() => sortHeader(field)}
                                >
                                  {title}
                                </button>
                              </th>
                            ))}
                            <th scope="col">Купоны и дивиденды, ₽</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(showAllInstruments ? tableRows : tableRows.slice(0, 10))
                            .flatMap((row) => [
                              { ...row, grouped: row.accounts.length > 1, child: false },
                              ...(row.accounts.length > 1
                                ? row.accountRows.map((accountRow) => ({
                                    ...accountRow,
                                    grouped: false,
                                    child: true,
                                  }))
                                : []),
                            ])
                            .map((row) => (
                              <tr
                                key={`${row.isin}/${row.child ? row.account.scope : "instrument"}`}
                                className={
                                  row.child
                                    ? layout.accountRow
                                    : row.grouped
                                      ? layout.instrumentRow
                                      : undefined
                                }
                              >
                                <th
                                  scope="row"
                                  title={
                                    row.child
                                      ? row.account.account_link?.source_account_id
                                      : `${row.name} · ${row.isin}`
                                  }
                                >
                                  {row.child ? (
                                    <>
                                      {label(row.account.scope, row.account.label)}
                                      {isPartialResult(row.pnl) && (
                                        <small className={layout.muted}>неполный</small>
                                      )}
                                    </>
                                  ) : (
                                    <>
                                      <div className={layout.instrumentTitle}>
                                        <Link
                                          to={instrumentHref(row.isin)}
                                          state={{ instrumentName: row.name }}
                                          onClick={(e) => guardLink(e, instrumentHref(row.isin))}
                                        >
                                          {row.name}
                                        </Link>
                                        {(isPartialResult(row.pnl) ||
                                          (row.grouped && row.pnl.value === null)) && (
                                          <span className={layout.muted}>неполный</span>
                                        )}
                                      </div>
                                      <small title={row.account.account_link?.source_account_id}>
                                        {row.kind === "bond"
                                          ? "Облигация"
                                          : row.kind === "stock"
                                            ? "Акция"
                                            : "Бумага"}{" "}
                                        ·{" "}
                                        {row.grouped
                                          ? accountCount(row.accounts.length)
                                          : label(row.account.scope, row.account.label)}
                                      </small>
                                    </>
                                  )}
                                </th>
                                <td
                                  data-label="Результат"
                                  title={displayMetric(row.pnl, true)}
                                  data-tone={tone(row.pnl)}
                                >
                                  {displayWhole(row.pnl, true)}
                                </td>
                                <td
                                  data-label="На вложенное"
                                  data-tone={row.grouped ? undefined : tone(row.simple)}
                                >
                                  {row.grouped ? (
                                    <span className={layout.muted}>по счетам</span>
                                  ) : (
                                    displayCompactRate(row.simple)
                                  )}
                                </td>
                                <td
                                  data-label="Годовых"
                                  title={
                                    row.grouped ? undefined : positionRatePeriod(row.account.xirr)
                                  }
                                  data-tone={row.grouped ? undefined : tone(row.annual)}
                                >
                                  {row.grouped ? (
                                    <span className={layout.muted}>по счетам</span>
                                  ) : (
                                    displayCompactRate(row.annual)
                                  )}
                                </td>
                                <td data-label="Купоны и дивиденды">
                                  <InstrumentIncome
                                    account={
                                      row.grouped ? { ...row, resultAvailable: true } : row.account
                                    }
                                    kind={row.kind}
                                  />
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                      {tableRows.some(
                        (row) =>
                          isPartialResult(row.pnl) ||
                          row.accountRows.some((account) => isPartialResult(account.pnl)),
                      ) && (
                        <p className={layout.note}>
                          Неполный результат включает только известные составляющие.
                        </p>
                      )}
                    </div>
                  ) : (
                    <p>Бумаги не найдены.</p>
                  )}
                  {annualReason && (
                    <p className={layout.note}>
                      {reasonCopy(annualReason, { surface: "returns" }).message}
                    </p>
                  )}
                  {tableRows.length > 10 && (
                    <button
                      type="button"
                      className={layout.more}
                      onClick={() => change({ show: showAllInstruments ? null : "all" })}
                    >
                      {showAllInstruments ? "Свернуть" : `Показать все ${tableRows.length}`}
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
