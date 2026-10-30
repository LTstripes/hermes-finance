import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { dateLabel, periodKey, periodLabel } from "./returns/model";
import {
  capitalGoldSnapshot,
  capitalInstrumentAccount,
  validDetailPeriod,
} from "./returns/navigation";
import { ReturnsCouponIncome } from "./returns/ReturnsCouponIncome";
import { accountHref, getOverall } from "./returns/overall";
import styles from "./returns/Returns.module.css";
import { MissingName } from "./returns/ReturnsAvailable";
import { ReturnsDetail } from "./returns/ReturnsDetail";
import { Explanation, Value } from "./returns/ReturnsInfo";
import { UiV2Shell } from "./UiV2Shell";

function Diagnostics({ codes }: { codes: string[] }) {
  if (!codes.length) return null;
  return (
    <details className={styles.diagnostics}>
      <summary>Основа и покрытие</summary>
      <Explanation codes={codes} />
      <ul>
        {[...new Set(codes)].map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ul>
    </details>
  );
}
const proofLabels = {
  current: "проверка актуальна",
  stale: "проверка устарела",
  absent: "проверки нет",
  conflict: "конфликт данных",
};

export default function UiV2ReturnsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const goldRef = useRef<HTMLTableRowElement>(null);
  const query = useQuery({
    queryKey: ["returns", "overall"],
    queryFn: ({ signal }) => getOverall(signal),
    staleTime: 0,
  });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  const search = params.get("q") ?? "";
  const expanded = params.getAll("isin").length === 1 ? params.get("isin") : null;
  const change = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    if ("isin" in updates || "detail_scope" in updates) {
      next.delete("capital_account");
      next.delete("gold_instrument");
    }
    for (const [key, value] of Object.entries(updates)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };
  const rows =
    data?.instruments.filter((row) =>
      `${row.name} ${row.isin}`.toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru")),
    ) ?? [];
  const capitalRequested = params.has("capital_account");
  const capitalAccount = data && capitalRequested ? capitalInstrumentAccount(data, params) : null;
  const goldSnapshot = data && capitalRequested ? capitalGoldSnapshot(data, params) : null;
  useEffect(() => {
    if (!data || !capitalAccount || !validDetailPeriod(capitalAccount.period)) return;
    const next = new URLSearchParams(params);
    next.delete("capital_account");
    next.set("detail_scope", capitalAccount.scope);
    next.set("detail_start", capitalAccount.period.start);
    next.set("detail_end", capitalAccount.period.end);
    navigate(
      { search: next.toString(), hash: location.hash || "#returns-instruments" },
      { replace: true },
    );
  }, [data, capitalAccount, params, navigate, location.hash]);
  useEffect(() => {
    if (!goldSnapshot) return;
    goldRef.current?.focus({ preventScroll: true });
    goldRef.current?.scrollIntoView?.({ block: "center" });
  }, [goldSnapshot]);
  const detailRequested = ["detail_scope", "detail_start", "detail_end"].some((key) =>
    params.has(key),
  );
  const detailAvailable =
    !capitalRequested &&
    data?.instruments.some(
      (row) =>
        row.isin === expanded &&
        row.accounts.some(
          (account) =>
            validDetailPeriod(account.period) &&
            params.getAll("detail_scope").length === 1 &&
            params.getAll("detail_start").length === 1 &&
            params.getAll("detail_end").length === 1 &&
            account.scope === params.get("detail_scope") &&
            account.period.start === params.get("detail_start") &&
            account.period.end === params.get("detail_end"),
        ),
    );
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
            <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>
              Обновить
            </button>
          </div>
        }
      >
        <h2>В целом</h2>
        <p className={styles.basisNote}>
          Вся доступная история. У каждого счёта свой подтверждённый интервал. Проданные бумаги
          включены, если они есть в актуальном расчёте по выпискам.
        </p>
        {query.isError ? (
          <p role="alert">
            Не удалось загрузить доходность.{" "}
            <button type="button" onClick={() => void query.refetch()}>
              Повторить
            </button>
          </p>
        ) : query.isFetching ? (
          <p role="status">Загружаем доступную историю…</p>
        ) : null}
        {data && (
          <>
            <section className={styles.panel} aria-label="Известный результат">
              <h2>Известный результат за доступную историю</h2>
              <section className={styles.mainValue} aria-label="Известная сумма результата">
                <Value
                  metric={data.mixed_result.known_result}
                  label="Известный результат за доступную историю"
                  signed
                />
              </section>
              <p>
                Известная часть результата по включённым компонентам в рублях, а не полный P&amp;L
                портфеля. Полный результат может быть выше или ниже: недостающие компоненты могут
                быть убыточными. Общая процентная доходность не рассчитана.
              </p>
              <p>
                Выбрано компонентов: {data.mixed_result.selected_component_count}. Доступно:{" "}
                {data.mixed_result.available_component_count}. Включено:{" "}
                {data.mixed_result.included_component_count}.
              </p>
              <Diagnostics
                codes={[
                  ...data.mixed_result.reason_codes,
                  ...data.mixed_result.known_result.reason_codes,
                ]}
              />
              <details className={styles.diagnostics}>
                <summary>Общий результат портфеля и общая доходность</summary>
                <p>Полный результат портфеля и единая процентная доходность не подтверждены.</p>
                <Value metric={data.overall.pnl} label="Полный результат портфеля" signed />
                <Value metric={data.overall.rate} label="Единая доходность портфеля" />
                <Diagnostics codes={data.overall.reason_codes} />
              </details>
              <h3>Состав известного результата</h3>
              {!data.mixed_result.components.length ? (
                <p>Нет подтверждённых компонентов для известного результата.</p>
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.instruments}>
                    <thead>
                      <tr>
                        <th>Компонент и основа</th>
                        <th>Известная сумма</th>
                        <th>Интервал / снимок</th>
                        <th>Участие в результате</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.mixed_result.components.map((component) => (
                        <tr key={component.id}>
                          <th>
                            {component.label}
                            <small>
                              {component.category === "brokerage"
                                ? "Брокерский счёт"
                                : component.category === "deposits"
                                  ? "Депозиты"
                                  : "Золото"}{" "}
                              ·{" "}
                              {component.authority === "source_only"
                                ? "по выпискам, оценка"
                                : "сохранённый снимок закрытого месяца"}
                            </small>
                            <details className={styles.diagnostics}>
                              <summary>Метод и покрытие</summary>
                              <p>
                                Метод: <code>{component.method}</code>. Покрытие:{" "}
                                <code>{component.coverage.status}</code>.
                              </p>
                              <Explanation codes={component.coverage.reason_codes} />
                              <ul>
                                {component.coverage.reason_codes.map((code) => (
                                  <li key={code}>
                                    <code>{code}</code>
                                  </li>
                                ))}
                              </ul>
                              {component.exclusion_reason && (
                                <p>
                                  Причина исключения: <code>{component.exclusion_reason}</code>
                                </p>
                              )}
                            </details>
                          </th>
                          <td>
                            <Value
                              metric={component.amount}
                              label={`${component.label}: известная сумма`}
                              signed
                            />
                          </td>
                          <td>
                            {component.interval && <p>{periodLabel(component.interval)}</p>}
                            {component.valuation_date && (
                              <p>Снимок на {dateLabel(component.valuation_date)}</p>
                            )}
                            {!component.interval &&
                              !component.valuation_date &&
                              "Границы не подтверждены"}
                          </td>
                          <td>
                            {component.included
                              ? "Включён"
                              : !component.selected
                                ? "Не выбран"
                                : component.coverage.status === "conflict"
                                  ? "Конфликт данных — не включён"
                                  : component.available
                                    ? "Доступен отдельно — не включён"
                                    : "Недоступен — не включён"}
                            {component.available && !component.included && component.selected && (
                              <p>
                                Включение этого компонента не подтверждено; сумма остаётся видимой
                                отдельно.
                              </p>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <ReturnsCouponIncome value={data.coupon_income} />
            {capitalRequested && !capitalAccount && !goldSnapshot && (
              <p role="status">
                Для этого точного счёта и инструмента нет единственного подтверждённого
                соответствия. Выберите доступный счёт бумаги; автоматический разбор не открыт.
              </p>
            )}
            <section className={styles.panel} aria-labelledby="overall-accounts">
              <h2 id="overall-accounts">По счетам</h2>
              <p className={styles.basisNote}>
                Основа — сохранённые брокерские выписки. Это оценка по каждому счёту; наличие
                выписки не означает принятие данных месяца.
              </p>
              {!data.source_accounts.length ? (
                <p>Доступных счетов по выпискам пока нет.</p>
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.instruments}>
                    <thead>
                      <tr>
                        <th>Счёт и интервал</th>
                        <th>Прибыль</th>
                        <th>Доходность</th>
                        <th>Выплаты</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.source_accounts.map((account) => (
                        <tr key={account.scope}>
                          <th>
                            <Link to={accountHref(account.scope, account.period)}>
                              {account.label}
                            </Link>
                            <small>
                              {account.period
                                ? periodLabel(account.period)
                                : "Интервал не подтверждён"}{" "}
                              · {proofLabels[account.proof_status]} · {account.instrument_count}{" "}
                              бумаг
                            </small>
                            <Diagnostics codes={account.reason_codes} />
                          </th>
                          {account.result ? (
                            <>
                              <td>
                                <Value
                                  metric={account.result.pnl}
                                  label={`${account.label}: прибыль`}
                                  signed
                                />
                              </td>
                              <td>
                                <Value
                                  metric={account.result.rate}
                                  label={`${account.label}: доходность`}
                                />
                              </td>
                              <td>
                                Купоны{" "}
                                <Value
                                  metric={account.result.coupons}
                                  label={`${account.label}: купоны`}
                                />
                                Дивиденды{" "}
                                <Value
                                  metric={account.result.dividends}
                                  label={`${account.label}: дивиденды`}
                                />
                              </td>
                            </>
                          ) : (
                            <td colSpan={3}>Нет подтверждённых числовых значений.</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <section className={styles.panel} aria-labelledby="returns-instruments">
              <div className={styles.sectionHead}>
                <h2 id="returns-instruments">По инструментам</h2>
                <span>{data.instruments.length} ISIN</span>
              </div>
              <label className={styles.overallSearch}>
                Поиск по названию или ISIN
                <input
                  type="search"
                  value={search}
                  onChange={(event) => change({ q: event.target.value || null })}
                />
              </label>
              <p className={styles.basisNote}>
                Один ISIN объединяет навигацию. Денежные результаты и проценты остаются отдельными
                для каждого счёта и интервала.
              </p>
              {detailRequested && !detailAvailable && (
                <p role="status">
                  Выбранный разбор недоступен для этого точного счёта и интервала. Выберите
                  доступный счёт бумаги.
                </p>
              )}
              {!rows.length ? (
                <p>
                  {data.instruments.length
                    ? "Бумаги не найдены."
                    : "Нет доступных расчётов по инструментам."}
                </p>
              ) : (
                rows.map((row) => (
                  <article key={row.isin} className={styles.overallInstrument}>
                    <h3>
                      <button
                        type="button"
                        className={styles.instrumentName}
                        aria-expanded={expanded === row.isin}
                        onClick={() =>
                          change({
                            isin: expanded === row.isin ? null : row.isin,
                            detail_scope: null,
                            detail_start: null,
                            detail_end: null,
                          })
                        }
                      >
                        {row.name}
                      </button>{" "}
                      <MissingName name={row.name} isin={row.isin} />
                    </h3>
                    <small>
                      {row.isin} ·{" "}
                      {row.kind === "bond"
                        ? "Облигация"
                        : row.kind === "stock"
                          ? "Акция"
                          : "Бумага"}{" "}
                      · {row.accounts.length} счетов
                    </small>
                    {expanded === row.isin && (
                      <>
                        <div className={styles.tableScroll}>
                          <table className={styles.instruments}>
                            <thead>
                              <tr>
                                <th>Счёт и интервал</th>
                                <th>Прибыль</th>
                                <th>Доходность</th>
                                <th>Купоны / дивиденды</th>
                              </tr>
                            </thead>
                            <tbody>
                              {row.accounts.map((account) => (
                                <tr
                                  key={`${account.scope}/${account.period ? periodKey(account.period) : "unavailable"}`}
                                >
                                  <th>
                                    <button
                                      type="button"
                                      disabled={!validDetailPeriod(account.period)}
                                      aria-pressed={
                                        validDetailPeriod(account.period) &&
                                        params.get("detail_scope") === account.scope &&
                                        params.get("detail_start") === account.period.start &&
                                        params.get("detail_end") === account.period.end
                                      }
                                      onClick={() => {
                                        if (validDetailPeriod(account.period))
                                          change({
                                            detail_scope: account.scope,
                                            detail_start: account.period.start,
                                            detail_end: account.period.end,
                                          });
                                      }}
                                    >
                                      Разбор: {account.label}
                                    </button>
                                    <small>
                                      {account.period
                                        ? periodLabel(account.period)
                                        : "Интервал не подтверждён"}
                                    </small>
                                    <Link to={accountHref(account.scope, account.period)}>
                                      История счёта
                                    </Link>
                                  </th>
                                  <td>
                                    <Value
                                      metric={account.pnl}
                                      label={`${row.name}, ${account.label}: прибыль`}
                                      signed
                                    />
                                  </td>
                                  <td>
                                    <Value
                                      metric={account.rate}
                                      label={`${row.name}, ${account.label}: доходность`}
                                    />
                                  </td>
                                  <td>
                                    <Value
                                      metric={account.coupons}
                                      label={`${row.name}, ${account.label}: купоны`}
                                    />
                                    <span> / </span>
                                    <Value
                                      metric={account.dividends}
                                      label={`${row.name}, ${account.label}: дивиденды`}
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {row.accounts.map((account) => {
                          const period = account.period;
                          if (
                            capitalRequested ||
                            !validDetailPeriod(period) ||
                            params.getAll("detail_scope").length !== 1 ||
                            params.getAll("detail_start").length !== 1 ||
                            params.getAll("detail_end").length !== 1 ||
                            params.get("detail_scope") !== account.scope ||
                            params.get("detail_start") !== period.start ||
                            params.get("detail_end") !== period.end
                          )
                            return null;
                          return (
                            <div key={`${row.isin}/${account.scope}/${periodKey(period)}`}>
                              <p>
                                {account.label} · {periodLabel(period)}
                              </p>
                              <button
                                type="button"
                                onClick={() =>
                                  change({
                                    detail_scope: null,
                                    detail_start: null,
                                    detail_end: null,
                                  })
                                }
                              >
                                К списку счетов этой бумаги
                              </button>
                              <ReturnsDetail
                                isin={row.isin}
                                scope={account.scope}
                                period={period}
                                revision={query.dataUpdatedAt}
                              />
                            </div>
                          );
                        })}
                        <Diagnostics codes={row.reason_codes} />
                      </>
                    )}
                  </article>
                ))
              )}
            </section>
            <section className={styles.panel} aria-label="Депозиты">
              <h2>Депозиты</h2>
              <h3>Известные полученные проценты</h3>
              <Value metric={data.deposits.interest} label="Полученные проценты по депозитам" />
              <p>
                Частичное покрытие: только фактически полученные проценты в сохранённых закрытых
                месяцах. Капитальная база и процентная доходность не рассчитаны.
              </p>
              {data.deposits.periods.length ? (
                <details className={styles.diagnostics}>
                  <summary>Покрытие истории депозитов</summary>
                  <ul>
                    {data.deposits.periods.map((entry) => (
                      <li key={`${periodKey(entry.period)}/${entry.status}`}>
                        {periodLabel(entry.period)} · {entry.status} · {entry.rows} строк
                      </li>
                    ))}
                  </ul>
                </details>
              ) : (
                <p>История депозитов не подтверждена.</p>
              )}
              <Diagnostics codes={data.deposits.reason_codes} />
            </section>
            <section id="returns-gold" className={styles.panel} aria-label="Золото">
              <h2>Золото</h2>
              {goldSnapshot && (
                <p>
                  Выбран сохранённый снимок по точным идентификаторам из Капитала. Это не разбор
                  сделок по ISIN.
                </p>
              )}
              <p>
                Последние сохранённые снимки закрытых месяцев. Классификация «золото» взята из
                текущего справочника и не подтверждает исторический класс.
              </p>
              {!data.gold.snapshots.length ? (
                <p>Нет доступных сохранённых снимков золота.</p>
              ) : (
                <div className={styles.tableScroll}>
                  <table className={styles.instruments}>
                    <thead>
                      <tr>
                        <th>Снимок</th>
                        <th>Стоимость / затраты</th>
                        <th>Нереализованный результат</th>
                        <th>К затратам, без приведения к году</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.gold.snapshots.map((snapshot) => (
                        <tr
                          key={`${snapshot.account_id}/${snapshot.instrument_id}`}
                          ref={goldSnapshot === snapshot ? goldRef : undefined}
                          tabIndex={goldSnapshot === snapshot ? -1 : undefined}
                          data-capital-selected={goldSnapshot === snapshot ? "true" : undefined}
                        >
                          <th>
                            {snapshot.label}
                            <small>
                              {dateLabel(snapshot.date)} · количество: {snapshot.quantity}
                            </small>
                          </th>
                          <td>
                            <Value
                              metric={snapshot.market_value}
                              label={`${snapshot.label}: стоимость`}
                            />
                            <span> / </span>
                            <Value
                              metric={snapshot.cost_basis}
                              label={`${snapshot.label}: затраты`}
                            />
                          </td>
                          <td>
                            <Value
                              metric={snapshot.unrealized_result}
                              label={`${snapshot.label}: нереализованный результат`}
                              signed
                            />
                          </td>
                          <td>
                            <Value
                              metric={snapshot.cost_return}
                              label={`${snapshot.label}: результат к затратам`}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p>Результат за период</p>
              <Value metric={data.gold.period_result} label="Золото: результат периода" />
              <p>Снимки не подтверждают реализованный результат или историю сделок.</p>
              <Diagnostics codes={data.gold.reason_codes} />
            </section>
            <Diagnostics codes={data.reason_codes} />
            <p>
              Для истории и периодов выберите счёт выше.{" "}
              <Link to="/v2/capital/performance">TWRR / XIRR и диагностика принятого портфеля</Link>
            </p>
          </>
        )}
      </UiV2Shell>
    </div>
  );
}
