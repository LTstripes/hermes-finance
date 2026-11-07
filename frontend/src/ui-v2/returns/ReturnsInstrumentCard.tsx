import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { formatQuantity } from "../../lib/format";
import { reasonCopy } from "../../lib/reasonCopy";
import sheet from "../ReportSheet.module.css";
import { money, rate } from "../SourceInstrumentDetail";
import { cardOperations, cardQuantityStatus, nonzeroAmount } from "./cardPresentation";
import { cleanMetric, getInstrumentCard, type InstrumentCard, selectCardScope } from "./cards";
import styles from "./InstrumentCard.module.css";
import resultStyles from "./InstrumentResult.module.css";
import {
  compareDecimal,
  dateLabel,
  displayMetric,
  displaySignedRate,
  isPartialResult,
  type Metric,
  tone,
} from "./model";
import { canonicalId } from "./navigation";
import { accountHref } from "./overall";
import { MissingName } from "./ReturnsAvailable";
import {
  Explanation,
  Info,
  MissingMetricNote,
  ResultNote,
  visibleReturnReasons,
} from "./ReturnsInfo";
import { ReturnsInstrumentResult } from "./ReturnsInstrumentResult";
import { ReturnsResultMeta } from "./ReturnsResultMeta";

const kindLabel = (kind: string | null) =>
  kind === "bond"
    ? "Облигация"
    : kind === "stock"
      ? "Акция"
      : kind === "gold"
        ? "Золото"
        : "Ценная бумага";

/** Sign colour for an exact kopeck string; geometry and arithmetic stay elsewhere. */
const amountTone = (value: string | null) =>
  value === null || !/^-?\d+$/.test(value)
    ? undefined
    : compareDecimal(value, "0") > 0
      ? "positive"
      : compareDecimal(value, "0") < 0
        ? "negative"
        : undefined;

/** Exact kopecks for an equality check only; never a displayed or derived amount. */
const exactKopecks = (metric: Metric) =>
  metric.unit === "kopecks" && metric.value !== null && /^-?\d+$/.test(metric.value)
    ? BigInt(metric.value)
    : null;

/** One period chip for the whole card when every account shares it. */
function periodText(card: InstrumentCard, selected: boolean) {
  const first = card.accounts[0]?.period;
  if (selected && first)
    return `Выбранный счёт · ${dateLabel(first.start)} – ${dateLabel(first.end)}`;
  const periods = new Set(
    card.accounts.map((a) => (a.period ? `${a.period.start}/${a.period.end}` : "")),
  );
  return periods.size === 1 && first
    ? `Вся доступная история · ${dateLabel(first.start)} – ${dateLabel(first.end)}`
    : "Вся доступная история по сохранённым выпискам";
}

function Figure({
  label,
  metric,
  children,
}: {
  label: string;
  metric: Metric;
  children?: ReactNode;
}) {
  return (
    <section className={styles.term}>
      <h3>{label}</h3>
      <strong data-tone={tone(metric)}>{displayMetric(metric, true)}</strong>
      {children}
    </section>
  );
}

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
  // Caveats of the shown total are explained once beside it; rows below do not repeat them.
  const shownCaveats = new Set(data?.summary.pnl.reason_codes ?? []);
  const partialTotal = data
    ? [data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl].some(
        isPartialResult,
      )
    : false;
  const summaryMetrics = data
    ? [data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl]
    : [];
  // Equality is drawn only when the shown parts add up to the shown total exactly;
  // parts and total may come from different account sets when a result is partial.
  const bridge = data
    ? [data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl].map(exactKopecks)
    : [];
  const bridgeKnown = bridge.length === 3 && bridge.every((value) => value !== null);
  const bridgeAdds =
    bridgeKnown && (bridge[0] as bigint) + (bridge[1] as bigint) === (bridge[2] as bigint);
  const unattributedPurchases = !!data?.accounts.some((account) =>
    account.purchases?.some((purchase) =>
      purchase.reason_codes.includes("account_money_unattributed"),
    ),
  );
  const Heading = standalone ? "h1" : "h2";
  return (
    <section className={styles.page} aria-label={`Карточка инструмента ${isin}`}>
      <button className={styles.back} type="button" onClick={close}>
        <span aria-hidden="true">← </span>
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
            <p className={sheet.eyebrow}>
              {kindLabel(data.kind)} · {data.isin}
            </p>
            <div className={styles.titleRow}>
              <Heading>
                {data.name} <MissingName name={data.name} isin={data.isin} />
              </Heading>
              <span className={styles.periodChip}>{periodText(data, !!selectedScope)}</span>
            </div>
          </header>
          {capitalRequested && matches.length !== 1 && (
            <p className={styles.notice}>
              Связь с выбранным счётом капитала не подтверждена. Показана доступная история этой
              бумаги по всем счетам.
            </p>
          )}
          <section className={styles.summary} aria-label="Разложение результата">
            <div className={styles.lead}>
              <section className={styles.total}>
                <h2 className={sheet.eyebrow}>Сумма по данным</h2>
                <strong className={sheet.hero}>{displayMetric(data.summary.pnl, true)}</strong>
                <div className={styles.totalMeta}>
                  {partialTotal && data.summary.pnl.value !== null && (
                    <span className={styles.estimate}>по доступным данным</span>
                  )}
                  {data.summary.pnl.value !== null &&
                    data.summary.pnl.estimate &&
                    !isPartialResult(data.summary.pnl) &&
                    !visibleReturnReasons(data.summary.pnl.reason_codes).length && (
                      <span className={styles.estimate}>Оценка</span>
                    )}
                  {data.summary.rate.value !== null && (
                    <span className={sheet.delta} data-tone={tone(data.summary.rate)}>
                      {displaySignedRate(data.summary.rate)}
                    </span>
                  )}
                  {data.summary.rate.value !== null ? (
                    <span className={sheet.muted}>
                      за период, не годовая{" "}
                      <Info label="Процент">
                        <p>
                          Modified Dietz учитывает суммы и даты покупок и продаж за указанный
                          период. Это не годовая ставка и не прибыль, делённая на сумму покупок.
                        </p>
                      </Info>
                    </span>
                  ) : (
                    data.accounts.length > 1 &&
                    data.accounts.some((a) => a.clean?.modified_dietz.value != null) && (
                      <span className={sheet.muted}>Процент — по каждому счёту ниже</span>
                    )
                  )}
                </div>
                {partialTotal && (
                  <p className={styles.caveat}>
                    В сумму входят только рассчитанные составляющие. Это не полный итог.
                  </p>
                )}
                <div className={styles.caveatGroup}>
                  <MissingMetricNote metrics={summaryMetrics} />
                  <ResultNote metric={data.summary.pnl} />
                </div>
              </section>
              <dl className={styles.position}>
                {data.summary.quantity.value !== null && (
                  <section aria-label="Известное количество инструмента">
                    <h3>{quantityStatus?.sold ? "Позиция продана" : "Количество"}</h3>
                    <strong>{formatQuantity(data.summary.quantity.value)}</strong>
                    {!!data.summary.valuation_dates.length && (
                      <small>На {data.summary.valuation_dates.map(dateLabel).join(", ")}</small>
                    )}
                  </section>
                )}
                {nonzeroAmount(data.summary.reported_value) && (
                  <section>
                    <h3>Стоимость позиции</h3>
                    <strong>{displayMetric(data.summary.reported_value)}</strong>
                    {!!data.summary.valuation_dates.length && (
                      <small>
                        Оценки на {data.summary.valuation_dates.map(dateLabel).join(", ")}
                      </small>
                    )}
                  </section>
                )}
              </dl>
            </div>
            {quantityStatus?.partial && (
              <p className={styles.caveat}>
                Не по всем счетам подтверждён остаток. Показанное известное количество не означает,
                что позиция полностью продана.
              </p>
            )}
            <div className={styles.bridge}>
              <h3 className={styles.bridgeTitle}>Из чего сложился результат</h3>
              <div className={styles.equation}>
                <Figure label="Стоимость и сделки" metric={data.summary.valuation_and_trades}>
                  <small>
                    {nonzeroAmount(data.summary.redemption)
                      ? `Погашение включено в стоимость и сделки: ${displayMetric(data.summary.redemption, true)}`
                      : "покупки, продажи и стоимость сейчас"}
                  </small>
                </Figure>
                {bridgeAdds && (
                  <span className={styles.operator} aria-hidden="true">
                    +
                  </span>
                )}
                <Figure label="Полученные выплаты" metric={data.summary.payouts}>
                  {[
                    ["купоны", data.summary.coupons],
                    ["дивиденды", data.summary.dividends],
                  ].some(([, value]) => nonzeroAmount(value as Metric)) && (
                    <small>
                      {(
                        [
                          ["Купоны", data.summary.coupons],
                          ["Дивиденды", data.summary.dividends],
                        ] as const
                      )
                        .filter(([, value]) => nonzeroAmount(value))
                        .map(([label, value]) => `${label}: ${displayMetric(value, true)}`)
                        .join(" · ")}
                    </small>
                  )}
                </Figure>
                {bridgeAdds && (
                  <>
                    <span className={styles.operator} aria-hidden="true">
                      =
                    </span>
                    <div className={styles.term} aria-hidden="true">
                      <span className={styles.termLabel}>Итог</span>
                      <strong data-tone={tone(data.summary.pnl)}>
                        {displayMetric(data.summary.pnl, true)}
                      </strong>
                    </div>
                  </>
                )}
              </div>
              {bridgeKnown && !bridgeAdds && (
                <p className={styles.caveat}>
                  Части и итог посчитаны по разным наборам данных, поэтому их сумма не равна итогу.
                </p>
              )}
              <p className={sheet.muted}>
                Комиссии и налоги не входят в расчёт. НКД учтён в сделках, стоимости и купонах.
              </p>
            </div>
            {accountsWithKnownTrades.length > 0 && (
              <section className={styles.knownTrades} aria-label="Известные суммы сделок">
                <h3>Известные суммы сделок</h3>
                <p className={sheet.muted}>Эти суммы сами по себе не являются доходностью.</p>
                {accountsWithKnownTrades.some(
                  (account) =>
                    account.clean?.buys.status === "partial" ||
                    account.clean?.sells.status === "partial",
                ) && <p className={sheet.muted}>Включены не все операции.</p>}
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
                        <p className={sheet.muted}>
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
                        .map(([label, value]) => {
                          const assumption = value.assumptions.find(
                            (code) => !shownCaveats.has(code),
                          );
                          return (
                            <p key={label}>
                              {label}
                              {value.status === "provisional" ? " · оценка" : ""}:{" "}
                              <span className={styles.amount}>
                                {displayMetric(cleanMetric(value))}
                              </span>
                              {assumption && (
                                <small>
                                  {" "}
                                  · {reasonCopy(assumption, { surface: "returns" }).message}
                                </small>
                              )}
                            </p>
                          );
                        })}
                    </div>
                  );
                })}
              </section>
            )}
          </section>
          {data.accounts.some(
            (account) =>
              account.purchases != null ||
              (account.clean?.buys.value != null && account.clean.buys.value !== "0"),
          ) && (
            <section className={styles.section} aria-label="Результат сохранённых покупок">
              <div className={styles.sectionHead}>
                <div>
                  <p className={sheet.eyebrow}>Без выплат · FIFO</p>
                  <h2>
                    Результат покупок{" "}
                    <Info label="Результат покупок">
                      <p>
                        Это аналитика Hermes, не налоговый учёт брокера. Процент от первоначальной
                        стоимости покупки, без годового пересчёта. Выплаты показаны выше по
                        инструменту.
                      </p>
                    </Info>
                  </h2>
                </div>
              </div>
              <p className={sheet.muted}>
                Стоимость и продажи с НКД, без выплат, комиссий и налогов. При продаже первыми
                считаются проданными самые ранние покупки (FIFO).
              </p>
              {unattributedPurchases && (
                <p role="note" className={styles.caveat}>
                  {reasonCopy("account_money_unattributed", { surface: "returns" }).message}
                </p>
              )}
              {data.accounts.map((account) =>
                account.purchases ? (
                  <div className={styles.scroll} key={account.scope}>
                    <h3 className={styles.tableTitle}>
                      <span>{accountLabels[account.scope] ?? account.label}</span>
                      {account.period && (
                        <span className={sheet.muted}>
                          {" "}
                          · {dateLabel(account.period.start)} – {dateLabel(account.period.end)}
                        </span>
                      )}
                    </h3>
                    <table className={`${styles.table} ${styles.lots}`}>
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
                            <td data-tone={amountTone(purchase.price_result_kopecks)}>
                              {money(purchase.price_result_kopecks)}
                              {purchase.status === "partial" &&
                                purchase.reason_codes.join() !== "account_money_unattributed" && (
                                  <small>Данные неполные</small>
                                )}
                              {purchase.reason_codes.includes("source_nkd_conflict") && (
                                <small>Расхождение по НКД</small>
                              )}
                            </td>
                            <td data-tone={amountTone(purchase.price_result_kopecks)}>
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
                <p className={sheet.muted}>
                  Если история, порядок сделок или остаток не подтверждены, отдельный результат пока
                  недоступен.
                </p>
              )}
            </section>
          )}
          {!!data.accounts.length && (
            <section className={styles.section} aria-label="Позиции и результат по счетам">
              <div className={styles.sectionHead}>
                <div>
                  <p className={sheet.eyebrow}>Подробности</p>
                  <h2>По счетам</h2>
                </div>
              </div>
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
                                reasonCodes={account.reason_codes.filter(
                                  (code) => !shownCaveats.has(code),
                                )}
                              />
                              <details className={styles.parts}>
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
                <p className={sheet.muted}>
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
            <section className={styles.section} aria-label="Покупки и продажи">
              <div className={styles.sectionHead}>
                <h2>Покупки и продажи</h2>
                <fieldset className={sheet.segmented} aria-label="Какие операции показать">
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
                </fieldset>
              </div>
              {filtered.length > 0 ? (
                <div className={styles.scroll}>
                  <table className={`${styles.table} ${styles.operations}`}>
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
                <p className={sheet.muted}>Таких операций нет в доступной истории.</p>
              )}
              {filtered.length > visibleOperations && (
                <button
                  className={styles.more}
                  type="button"
                  onClick={() => setVisibleOperations((n) => n + 20)}
                >
                  Ещё операции
                </button>
              )}
            </section>
          )}
          {payouts.length > 0 && (
            <details className={`${styles.section} ${styles.details}`}>
              <summary>Выплаты · {payouts.length}</summary>
              <div className={styles.scroll}>
                <table className={`${styles.table} ${styles.operations}`}>
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
              className={`${styles.section} ${styles.details}`}
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
