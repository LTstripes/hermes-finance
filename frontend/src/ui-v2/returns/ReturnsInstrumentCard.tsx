import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { formatQuantity } from "../../lib/format";
import { reasonCopy } from "../../lib/reasonCopy";
import { money, rate } from "../SourceInstrumentDetail";
import { cardOperations, cardQuantityStatus, nonzeroAmount } from "./cardPresentation";
import { cleanMetric, getInstrumentCard, selectCardScope } from "./cards";
import styles from "./InstrumentCard.module.css";
import resultStyles from "./InstrumentResult.module.css";
import { dateLabel, displayMetric, isPartialResult } from "./model";
import { canonicalId } from "./navigation";
import { accountHref } from "./overall";
import { MissingName } from "./ReturnsAvailable";
import { Explanation, MissingMetricNote, ResultNote, visibleReturnReasons } from "./ReturnsInfo";
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
  const accountsWithKnownTrades =
    data?.accounts.filter(
      (account) =>
        account.clean &&
        (data.summary.pnl.value === null ||
          account.clean.pnl.value === null ||
          account.clean.pnl.status === "partial") &&
        (account.clean.buys.value !== null || account.clean.sells.value !== null),
    ) ?? [];
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
          <section className={styles.panel} aria-label="Разложение результата">
            <h2>Из чего сложился результат</h2>
            <p>Комиссии и налоги не входят в расчёт. НКД учтён в сделках, стоимости и купонах.</p>
            {[data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl].some(
              isPartialResult,
            ) && <p>В сумму входят только рассчитанные составляющие.</p>}
            <div className={styles.facts}>
              {(
                [
                  ["Стоимость и сделки", data.summary.valuation_and_trades],
                  ["Полученные выплаты", data.summary.payouts],
                  ["Сумма по данным", data.summary.pnl],
                ] as const
              ).map(([label, value]) => (
                <section
                  className={`${styles.fact} ${label === "Сумма по данным" ? styles.primary : ""}`}
                  key={label}
                >
                  <h3>{label}</h3>
                  <strong>{displayMetric(value, true)}</strong>
                  {value.value !== null && value.estimate && !isPartialResult(value) && (
                    <small>Оценка</small>
                  )}
                </section>
              ))}
            </div>
            <MissingMetricNote
              metrics={[data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl]}
            />
            <ResultNote metric={data.summary.pnl} />
            {accountsWithKnownTrades.length > 0 && (
              <section aria-label="Известные суммы сделок">
                <h3>Известные суммы сделок</h3>
                <p>Эти суммы сами по себе не являются доходностью.</p>
                {accountsWithKnownTrades.some(
                  (account) =>
                    account.clean?.buys.status === "partial" ||
                    account.clean?.sells.status === "partial",
                ) && <p>Включены не все операции.</p>}
                {accountsWithKnownTrades.map((account) => {
                  const clean = account.clean;
                  if (!clean || (clean.buys.value === null && clean.sells.value === null))
                    return null;
                  return (
                    <div key={account.scope}>
                      {!selectedScope && (
                        <strong>{accountLabels[account.scope] ?? account.label}</strong>
                      )}
                      {account.period && (
                        <p>
                          {dateLabel(account.period.start)} – {dateLabel(account.period.end)}
                        </p>
                      )}
                      {(
                        [
                          ["Покупки", clean.buys],
                          ["Продажи", clean.sells],
                        ] as const
                      )
                        .filter(([, value]) => value.value !== null)
                        .map(([label, value]) => (
                          <p key={label}>
                            {label}
                            {value.status === "provisional" ? " · оценка" : ""}:{" "}
                            {displayMetric(cleanMetric(value))}
                            {value.assumptions.length > 0 && (
                              <small>
                                {" "}
                                · {reasonCopy(value.assumptions[0], { surface: "returns" }).message}
                              </small>
                            )}
                          </p>
                        ))}
                    </div>
                  );
                })}
              </section>
            )}
            <details>
              <summary>Купоны и дивиденды</summary>
              {(
                [
                  ["Купоны", data.summary.coupons],
                  ["Дивиденды", data.summary.dividends],
                ] as const
              ).map(([label, value]) => (
                <p key={label}>
                  {label}: {displayMetric(value, true)}
                </p>
              ))}
            </details>
            {nonzeroAmount(data.summary.redemption) && (
              <p>
                Погашение включено в стоимость и сделки:{" "}
                {displayMetric(data.summary.redemption, true)}
              </p>
            )}
          </section>
          <div className={styles.facts}>
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
          </div>
          {quantityStatus?.partial && (
            <p className={styles.notice}>
              Не по всем счетам подтверждён остаток. Показанное известное количество не означает,
              что позиция полностью продана.
            </p>
          )}
          {data.accounts.some(
            (account) =>
              account.purchases != null ||
              (account.clean?.buys.value != null && account.clean.buys.value !== "0"),
          ) && (
            <section className={styles.panel} aria-label="Результат сохранённых покупок">
              <h2>Результат покупок</h2>
              <p>
                Показан результат стоимости и продаж с НКД, без выплат, комиссий и налогов. При
                продаже первыми считаются проданными самые ранние покупки (FIFO). Это аналитика
                Hermes, не налоговый учёт брокера. Процент от первоначальной стоимости покупки, без
                годового пересчёта. Выплаты показаны выше по инструменту.
              </p>
              {data.accounts.map((account) =>
                account.purchases ? (
                  <div className={styles.scroll} key={account.scope}>
                    <h3>{accountLabels[account.scope] ?? account.label}</h3>
                    {account.period && (
                      <p>
                        {dateLabel(account.period.start)} – {dateLabel(account.period.end)}
                      </p>
                    )}
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Дата покупки</th>
                          <th>Куплено / осталось</th>
                          <th>Вложено</th>
                          <th>Выручка / стоимость остатка</th>
                          <th>Результат без выплат</th>
                          <th>К первоначальной стоимости</th>
                        </tr>
                      </thead>
                      <tbody>
                        {account.purchases.map((purchase) => (
                          <tr key={purchase.id}>
                            <td>{dateLabel(purchase.date)}</td>
                            <td>
                              {formatQuantity(purchase.quantity)} /{" "}
                              {purchase.remaining_quantity === null
                                ? "—"
                                : formatQuantity(purchase.remaining_quantity)}
                            </td>
                            <td>{money(purchase.cost_kopecks)}</td>
                            <td>
                              {money(purchase.sale_proceeds_kopecks)} /{" "}
                              {money(purchase.value_kopecks)}
                            </td>
                            <td>
                              {money(purchase.price_result_kopecks)}
                              {purchase.status === "partial" &&
                                purchase.reason_codes.join() !== "account_money_unattributed" && (
                                  <small>Данные неполные</small>
                                )}
                              {purchase.reason_codes.includes("source_nkd_conflict") && (
                                <small>Расхождение по НКД</small>
                              )}
                            </td>
                            <td>
                              {purchase.return_fraction === null ? (
                                <span>
                                  —{" "}
                                  <small>
                                    {purchase.cost_kopecks === "0"
                                      ? "Нулевая стоимость покупки"
                                      : "Недостаточно данных"}
                                  </small>
                                </span>
                              ) : (
                                rate(purchase.return_fraction)
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null,
              )}
              {data.accounts.some((account) => account.clean && account.purchases == null) && (
                <p>
                  Если история, порядок сделок или остаток не подтверждены, отдельный результат пока
                  недоступен.
                </p>
              )}
            </section>
          )}
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
                          {account.ai_account_ref && (
                            <small>В отчёте AI: {account.ai_account_ref}</small>
                          )}
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
                                <summary>Составляющие результата</summary>
                                {[
                                  account.clean.buys,
                                  account.clean.sells,
                                  account.clean.coupons,
                                  account.clean.dividends,
                                  account.clean.redemption,
                                ].some((part) => part.status === "partial") && (
                                  <p>Включены не все операции.</p>
                                )}
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
                                      {label}: {displayMetric(cleanMetric(part))}
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
              {data.accounts.some((account) => account.ai_account_ref) && (
                <p className={styles.muted}>
                  Номера счетов в отчёте AI относятся к текущему составу счетов.
                </p>
              )}
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
