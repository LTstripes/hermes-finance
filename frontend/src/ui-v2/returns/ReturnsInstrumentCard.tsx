import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { formatQuantity } from "../../lib/format";
import { money } from "../SourceInstrumentDetail";
import { cardOperations, cardQuantityStatus, hasAmount, nonzeroAmount } from "./cardPresentation";
import { cleanMetric, getInstrumentCard, selectCardScope } from "./cards";
import styles from "./InstrumentCard.module.css";
import resultStyles from "./InstrumentResult.module.css";
import { dateLabel, displayMetric } from "./model";
import { canonicalId } from "./navigation";
import { accountHref } from "./overall";
import { MissingName } from "./ReturnsAvailable";
import { Explanation, visibleReturnReasons } from "./ReturnsInfo";
import { ReturnsInstrumentResult } from "./ReturnsInstrumentResult";
import { ReturnsResultMeta } from "./ReturnsResultMeta";

export function ReturnsInstrumentCard({
  isin,
  revision,
  capitalAccount,
  capitalRequested = false,
  selectedScope,
  selectedStart,
  selectedEnd,
  close,
  standalone = false,
  accountLabels = {},
  backLabel = "К списку инструментов",
}: {
  isin: string;
  revision: number;
  capitalAccount: string | null;
  capitalRequested?: boolean;
  selectedScope?: string | null;
  selectedStart?: string | null;
  selectedEnd?: string | null;
  close: () => void;
  standalone?: boolean;
  accountLabels?: Record<string, string>;
  backLabel?: string;
}) {
  const query = useQuery({
    queryKey: ["returns", "instrument-card", isin, revision],
    queryFn: ({ signal }) => getInstrumentCard(isin, signal),
    staleTime: 0,
  });
  const selection = query.data
    ? selectCardScope(query.data, selectedScope, selectedStart, selectedEnd)
    : null;
  const data = !query.isError ? selection?.card : undefined;
  const limitedAccounts =
    data?.accounts
      .map((account) => ({
        account,
        codes: visibleReturnReasons([
          ...new Set([
            ...account.reason_codes,
            ...(account.detail?.pnl.value === null ? account.detail.pnl.reason_codes : []),
            ...(account.detail?.rate.value === null ? account.detail.rate.reason_codes : []),
          ]),
        ]),
      }))
      .filter(({ account }) => !account.clean && (!account.included || !account.detail)) ?? [];
  const id = canonicalId(capitalAccount);
  const matches =
    data?.accounts.filter((account) => id !== null && account.canonical_account_id === id) ?? [];
  const [operationFilter, setOperationFilter] = useState<"all" | "BUY" | "SELL">("all");
  const [visibleOperations, setVisibleOperations] = useState(20);
  const operations = useMemo(() => cardOperations(data?.accounts ?? []), [data]);
  const filtered = operations.filter(
    (row) => operationFilter === "all" || row.side === operationFilter,
  );
  const quantityStatus = data ? cardQuantityStatus(data) : null;
  const payouts =
    data?.accounts
      .flatMap((account) =>
        (account.detail?.analysis.events ?? [])
          .filter(
            (event) =>
              event.current &&
              event.counted &&
              (event.kind === "COUPON" || event.kind === "DIVIDEND") &&
              event.event_date !== null &&
              event.net_payout_kopecks !== null,
          )
          .map((event) => ({ account: account.label, scope: account.scope, event })),
      )
      .sort((a, b) => (b.event.event_date ?? "").localeCompare(a.event.event_date ?? "")) ?? [];
  const Heading = standalone ? "h1" : "h2";
  return (
    <section className={styles.page} aria-label={`Карточка инструмента ${isin}`}>
      <button className={styles.back} type="button" onClick={close}>
        {backLabel}
      </button>
      {query.isError ? (
        <p role="alert">
          Не удалось загрузить инструмент.{" "}
          <button type="button" onClick={() => void query.refetch()}>
            Повторить
          </button>
        </p>
      ) : query.isFetching && !data ? (
        <p role="status">Загружаем инструмент…</p>
      ) : null}
      {selection?.mismatch && !query.isFetching && (
        <p role="alert">
          Счёт или период изменились с момента открытия списка. Вернитесь к доходности и выберите их
          снова.
        </p>
      )}
      {query.isFetching && data ? <p role="status">Обновляем данные…</p> : null}
      {data && (
        <>
          <header className={styles.header}>
            <Heading>
              {data.name} <MissingName name={data.name} isin={data.isin} />
            </Heading>
            <span className={styles.muted}>
              {data.kind === "bond"
                ? "Облигация"
                : data.kind === "stock"
                  ? "Акция"
                  : data.kind === "gold"
                    ? "Золото"
                    : "Ценная бумага"}{" "}
              · {data.isin}
            </span>
            <p className={styles.muted}>
              {selectedScope && data.accounts[0]?.period
                ? `Выбранный счёт · ${dateLabel(data.accounts[0].period.start)} – ${dateLabel(data.accounts[0].period.end)}`
                : "По сохранённым выпискам, за доступную историю."}
            </p>
          </header>
          {capitalRequested && matches.length !== 1 && (
            <p className={styles.notice}>
              Связь с выбранным счётом капитала не подтверждена. Показана доступная история этой
              бумаги по всем счетам.
            </p>
          )}
          <div className={styles.facts}>
            {hasAmount(data.summary.pnl) && (
              <section className={`${styles.fact} ${styles.primary}`}>
                <h3>Известный результат</h3>
                <strong>{displayMetric(data.summary.pnl, true)}</strong>
                <small>{selectedScope ? "За указанный период" : "За доступную историю"}</small>
              </section>
            )}
            {data.summary.quantity.value !== null && (
              <section className={styles.fact} aria-label="Известное количество инструмента">
                <h3>{quantityStatus?.sold ? "Позиция продана" : "Количество"}</h3>
                <strong>{formatQuantity(data.summary.quantity.value)}</strong>
                {!!data.summary.valuation_dates.length && (
                  <small>На {data.summary.valuation_dates.map(dateLabel).join(", ")}</small>
                )}
              </section>
            )}
            {nonzeroAmount(data.summary.reported_value) && (
              <section className={styles.fact}>
                <h3>Стоимость позиции</h3>
                <strong>{displayMetric(data.summary.reported_value)}</strong>
                {!!data.summary.valuation_dates.length && (
                  <small>Оценки на {data.summary.valuation_dates.map(dateLabel).join(", ")}</small>
                )}
              </section>
            )}
            {nonzeroAmount(data.summary.coupons) && (
              <section className={styles.fact}>
                <h3>Полученные купоны</h3>
                <strong>{displayMetric(data.summary.coupons)}</strong>
              </section>
            )}
            {nonzeroAmount(data.summary.dividends) && (
              <section className={styles.fact}>
                <h3>Полученные дивиденды</h3>
                <strong>{displayMetric(data.summary.dividends)}</strong>
              </section>
            )}
          </div>
          {quantityStatus?.partial && (
            <p className={styles.notice}>
              Не по всем счетам подтверждён остаток. Показанное известное количество не означает,
              что позиция полностью продана.
            </p>
          )}
          <section className={styles.panel} aria-label="Разложение результата">
            <h2>Из чего сложился результат</h2>
            <p>Показаны известные составляющие; комиссии, налоги и НКД не входят в расчёт.</p>
            {(
              [
                ["Цена и сделки", data.summary.valuation_and_trades],
                ["Купоны", data.summary.coupons],
                ["Дивиденды", data.summary.dividends],
                ["Погашение", data.summary.redemption],
                ["Известный результат", data.summary.pnl],
              ] as const
            )
              .filter(([, value]) => value.value !== null)
              .map(([label, value]) => (
                <p key={label}>
                  {label}: {displayMetric(value, true)}
                </p>
              ))}
          </section>
          {!!data.accounts.length && (
            <section className={styles.panel} aria-label="Позиции и результат по счетам">
              <h2>По счетам</h2>
              <div className={styles.scroll}>
                <table className={`${styles.table} ${resultStyles.list}`}>
                  <thead>
                    <tr>
                      <th>Счёт</th>
                      <th>Позиция</th>
                      <th colSpan={2}>Результат и доходность за период</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.accounts.map((account) => (
                      <tr
                        key={account.scope}
                        data-capital-context={
                          matches.length === 1 && matches[0] === account ? "true" : undefined
                        }
                      >
                        <td>
                          <Link to={accountHref(account.scope, account.period)}>
                            {accountLabels[account.scope] ?? account.label}
                          </Link>
                          <ReturnsResultMeta
                            period={account.period}
                            valuationDate={account.valuation_date}
                            accountLink={account.account_link}
                          />
                          {!account.included && <small>Не включён в общий результат</small>}
                        </td>
                        {account.clean ? (
                          <>
                            <td>
                              {account.detail?.closing_quantity != null && (
                                <span>{formatQuantity(account.detail.closing_quantity)} шт.</span>
                              )}
                              {account.clean.closing_value.value !== null && (
                                <small>{money(account.clean.closing_value.value)}</small>
                              )}
                            </td>
                            <td colSpan={2}>
                              <ReturnsInstrumentResult
                                result={{
                                  pnl: cleanMetric(
                                    account.clean.pnl.value !== null
                                      ? account.clean.pnl
                                      : account.clean.known_result,
                                  ),
                                  rate: cleanMetric(account.clean.modified_dietz, true),
                                }}
                                reasonCodes={account.reason_codes}
                              />
                              <details>
                                <summary>Известные составляющие</summary>
                                {(
                                  [
                                    ["Покупки", account.clean.buys],
                                    ["Продажи", account.clean.sells],
                                    ["Купоны", account.clean.coupons],
                                    ["Дивиденды", account.clean.dividends],
                                    ["Погашение", account.clean.redemption],
                                  ] as const
                                )
                                  .filter(([, part]) => part.value !== null)
                                  .map(([label, part]) => (
                                    <p key={label}>
                                      {label}
                                      {part.status === "partial" ? " · известная часть" : ""}:{" "}
                                      {displayMetric(cleanMetric(part))}
                                    </p>
                                  ))}
                              </details>
                            </td>
                          </>
                        ) : (
                          <td colSpan={3}>
                            <ReturnsInstrumentResult
                              result={null}
                              reasonCodes={account.reason_codes}
                            />
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data.accounts.some((account) => account.clean?.modified_dietz.value != null) && (
                <details className={styles.details}>
                  <summary>Как читать процент</summary>
                  <p>
                    Modified Dietz учитывает суммы и даты покупок и продаж за указанный период. Если
                    позицию уже продали, длинный период и небольшой взвешенный капитал могут дать
                    высокий процент даже при умеренной прибыли в рублях. Это не годовая ставка и не
                    прибыль, делённая на сумму покупок.
                  </p>
                </details>
              )}
            </section>
          )}
          {operations.length > 0 && (
            <section className={styles.panel} aria-label="Покупки и продажи">
              <h2>Покупки и продажи</h2>
              <div className={styles.filters}>
                {(
                  [
                    ["all", "Все"],
                    ["BUY", "Покупки"],
                    ["SELL", "Продажи"],
                  ] as const
                ).map(([kind, label]) => (
                  <button
                    type="button"
                    key={kind}
                    aria-pressed={operationFilter === kind}
                    onClick={() => {
                      setOperationFilter(kind);
                      setVisibleOperations(20);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {filtered.length > 0 ? (
                <div className={styles.scroll}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Дата</th>
                        <th>Операция</th>
                        {data.accounts.length > 1 && <th>Счёт</th>}
                        <th>Количество</th>
                        <th>Сумма сделки</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.slice(0, visibleOperations).map((row) => (
                        <tr key={row.key}>
                          <td>{dateLabel(row.date)}</td>
                          <td>{row.side === "BUY" ? "Покупка" : "Продажа"}</td>
                          {data.accounts.length > 1 && (
                            <td>{accountLabels[row.scope] ?? row.account}</td>
                          )}
                          <td>{formatQuantity(row.quantity)}</td>
                          <td>{money(row.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>Таких операций нет в доступной истории.</p>
              )}
              {filtered.length > visibleOperations && (
                <button type="button" onClick={() => setVisibleOperations((n) => n + 20)}>
                  Ещё операции
                </button>
              )}
            </section>
          )}
          {payouts.length > 0 && (
            <details className={`${styles.panel} ${styles.details}`}>
              <summary>Выплаты · {payouts.length}</summary>
              <div className={styles.scroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Выплата</th>
                      {data.accounts.length > 1 && <th>Счёт</th>}
                      <th>Получено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payouts.map(({ account, scope, event }) => (
                      <tr key={`${scope}/${event.event_key}`}>
                        <td>{dateLabel(event.event_date as string)}</td>
                        <td>{event.kind === "COUPON" ? "Купон" : "Дивиденд"}</td>
                        {data.accounts.length > 1 && <td>{accountLabels[scope] ?? account}</td>}
                        <td>{money(event.net_payout_kopecks)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {limitedAccounts.length > 0 && (
            <details
              className={`${styles.panel} ${styles.details}`}
              open={!!selectedScope || undefined}
            >
              <summary>Что ограничивает расчёт</summary>
              {limitedAccounts.map(({ account, codes }) => (
                <section key={account.scope}>
                  <h3>{accountLabels[account.scope] ?? account.label}</h3>
                  <Explanation
                    context={{ account: account.label, instrument: data.name }}
                    codes={codes.length ? codes : ["all_history_source_proof_unavailable"]}
                  />
                </section>
              ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}
