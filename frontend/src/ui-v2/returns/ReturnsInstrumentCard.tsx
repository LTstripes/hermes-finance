import { useAccountName } from "./useAccountName";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { formatQuantity } from "../../lib/format";
import { reasonCopy } from "../../lib/reasonCopy";
import { shortInstrumentName } from "../instrumentName";
import { UiV2Skeleton } from "../UiV2StateBlocks";
import sheet from "../ReportSheet.module.css";
import { money } from "../SourceInstrumentDetail";
import { cardOperations, cardQuantityStatus, nonzeroAmount } from "./cardPresentation";
import {
  cleanMetric,
  getInstrumentCard,
  type InstrumentCard,
  positionRateMetric,
  positionRatePeriod,
  selectCardScope,
} from "./cards";
import styles from "./InstrumentCard.module.css";
import {
  compareDecimal,
  dateLabel,
  displayMetric,
  displayWhole,
  displayCompactRate,
  isPartialResult,
  type Metric,
  tone,
  unavailable,
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
import { useReturnsInvalidated } from "./useReturnsInvalidated";

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
  initialName,
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
  initialName?: string;
}) {
  const queryClient = useQueryClient();
  const fetching = useIsFetching();
  const [expandedPurchases, setExpandedPurchases] = useState<string[]>([]);
  const query = useQuery({
    queryKey: ["returns", "instrument-card", isin, revision],
    queryFn: ({ signal }) => getInstrumentCard(isin, signal),
    staleTime: 5 * 60 * 1000,
  });
  const selection = query.data
    ? selectCardScope(query.data, selectedScope, selectedStart, selectedEnd)
    : null;
  const invalidated = useReturnsInvalidated(["returns", "instrument-card", isin, revision]);
  const card = !query.isError && !invalidated ? selection?.card : undefined;
  const data = card?.aggregate
    ? {
        ...card,
        summary: {
          ...card.summary,
          pnl: cleanMetric(card.aggregate.pnl),
          reported_value: cleanMetric(card.aggregate.current_value),
        },
      }
    : card;
  const catalogueName = useAccountName(data?.accounts.map((a) => a.account_link) ?? []);
  const accountName = (scope: string, fallback: string) => {
    const link = data?.accounts.find((account) => account.scope === scope)?.account_link;
    return catalogueName(link, accountLabels[scope] ?? fallback);
  };
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
  // Positions are compared by the simple return on invested and, after a capital-weighted
  // year, by annual XIRR. The server owns the combined account cash flows.
  const onlyClean =
    data?.aggregate ?? (data?.accounts.length === 1 ? data.accounts[0].clean : null);
  const simpleRate =
    onlyClean?.simple_return && onlyClean.simple_return.value !== null
      ? positionRateMetric(onlyClean.simple_return)
      : null;
  const annualRate =
    onlyClean?.xirr && onlyClean.xirr.value !== null ? positionRateMetric(onlyClean.xirr) : null;
  // Equality is drawn only for a complete bridge: all three values known, none partial
  // (one producer-owned account set), and the parts adding up to the total exactly.
  // Matching numbers alone do not prove that parts and total cover the same data.
  const bridge = data
    ? [data.summary.valuation_and_trades, data.summary.payouts, data.summary.pnl].map(exactKopecks)
    : [];
  const bridgeKnown = bridge.length === 3 && bridge.every((value) => value !== null);
  const bridgeSums =
    bridgeKnown && (bridge[0] as bigint) + (bridge[1] as bigint) === (bridge[2] as bigint);
  const bridgeAdds = bridgeSums && !partialTotal;
  const unattributedPurchases = !!data?.accounts.some((account) =>
    account.purchases?.some((purchase) =>
      purchase.reason_codes.includes("account_money_unattributed"),
    ),
  );
  const purchaseMoney = (value: string | null, signed = false) =>
    displayWhole({ ...unavailable, value }, signed);
  const showAnnual = data?.accounts.some((account) => account.clean?.xirr?.value != null);
  const primaryCaveats =
    data?.summary.pnl.reason_codes.filter(
      (code) =>
        !["clean_partial_result", "selected_components_incomplete", "income_assumed"].includes(
          code,
        ),
    ) ?? [];
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
        <>
          {initialName && (
            <Heading>{shortInstrumentName({ name: initialName, isin, ticker: null })}</Heading>
          )}
          <UiV2Skeleton label="Загружаем инструмент…" expectedTime />
        </>
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
              {kindLabel(data.kind)} · {data.isin} · {data.name}
            </p>
            <div className={styles.titleRow}>
              <Heading>
                {shortInstrumentName({
                  name: initialName?.trim() || data.name,
                  isin: data.isin,
                  ticker: null,
                })}{" "}
                <MissingName name={data.name} isin={data.isin} />
              </Heading>
              <button
                type="button"
                className={styles.refresh}
                disabled={fetching > 0}
                onClick={() => void queryClient.invalidateQueries()}
              >
                Обновить
              </button>
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
                <h2 className={sheet.eyebrow}>Результат за всю историю</h2>
                <strong className={sheet.hero} title={displayMetric(data.summary.pnl, true)}>
                  {displayWhole(data.summary.pnl, true)}
                </strong>
                {data.aggregate && (
                  <dl className={styles.resultSplit}>
                    {(
                      [
                        [
                          "Зафиксировано",
                          data.aggregate.realized_result,
                          "Результат продаж и погашений за вычетом FIFO-стоимости выбывших лотов, плюс полученные купоны и дивиденды. НКД учтён в стоимости сделок; комиссии и налоги исключены.",
                        ],
                        [
                          "В цене",
                          data.aggregate.unrealized_result,
                          "Текущая оценка открытых лотов минус их FIFO-стоимость. Для закрытой позиции — ноль.",
                        ],
                      ] as const
                    ).map(([label, value, explanation]) => (
                      <div key={label}>
                        <dt>
                          {label}{" "}
                          <Info label={label}>
                            <p>{explanation}</p>
                            <Explanation codes={[...value.reason_codes, ...value.assumptions]} />
                          </Info>
                        </dt>
                        <dd title={displayMetric(cleanMetric(value), true)}>
                          {displayWhole(cleanMetric(value), true)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                <div className={styles.totalMeta}>
                  {partialTotal && data.summary.pnl.value !== null && (
                    <span className={styles.estimate}>по доступным данным</span>
                  )}
                  {data.summary.pnl.value !== null &&
                    data.summary.pnl.estimate &&
                    !isPartialResult(data.summary.pnl) &&
                    !primaryCaveats.length && <span className={styles.estimate}>Оценка</span>}
                  {simpleRate && (
                    <span className={sheet.delta} data-tone={tone(simpleRate)}>
                      {displayCompactRate(simpleRate)}
                    </span>
                  )}
                  {simpleRate && (
                    <span className={sheet.muted}>
                      на вложенное
                      {annualRate ? ` · ${displayCompactRate(annualRate)} годовых` : ""}{" "}
                      <Info label="Процент">
                        <p>
                          Процент на вложенное — итог позиции, делённый на сумму покупок. Он не
                          пересчитан на год.
                        </p>
                        <p>
                          Годовая доходность (XIRR) учитывает даты и суммы покупок, продаж и выплат.
                          Её показываем, когда деньги в среднем пролежали в позиции не меньше года,
                          иначе годовой процент вводит в заблуждение.
                        </p>
                      </Info>
                    </span>
                  )}
                  {annualRate && (
                    <small className={sheet.muted}>{positionRatePeriod(onlyClean?.xirr)}</small>
                  )}
                  {simpleRate &&
                    !annualRate &&
                    onlyClean?.xirr?.reason_codes.includes("short_holding") && (
                      <small className={sheet.muted}>
                        Годовая не считается: деньги в среднем были в позиции меньше года
                      </small>
                    )}
                </div>
                {partialTotal && !primaryCaveats.length && (
                  <p className={styles.caveat}>
                    В сумму входят только рассчитанные составляющие. Это не полный итог.
                  </p>
                )}
                <div className={styles.caveatGroup}>
                  {data.summary.pnl.value === null && (
                    <MissingMetricNote metrics={summaryMetrics} />
                  )}
                  <ResultNote
                    metric={{ ...data.summary.pnl, reason_codes: primaryCaveats.slice(0, 1) }}
                  />
                  {data.summary.pnl.reason_codes.some(
                    (code) =>
                      !primaryCaveats.slice(0, 1).includes(code) &&
                      !["clean_partial_result", "selected_components_incomplete"].includes(code),
                  ) && (
                    <Info label="Оговорки результата">
                      <Explanation
                        codes={data.summary.pnl.reason_codes.filter(
                          (code) =>
                            !primaryCaveats.slice(0, 1).includes(code) &&
                            !["clean_partial_result", "selected_components_incomplete"].includes(
                              code,
                            ),
                        )}
                      />
                    </Info>
                  )}
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
                    <strong title={displayMetric(data.summary.reported_value)}>
                      {displayWhole(data.summary.reported_value)}
                    </strong>
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
              {bridgeKnown && !partialTotal && !bridgeSums && (
                <p className={styles.caveat}>
                  Части и итог посчитаны по разным наборам данных, поэтому их сумма не равна итогу.
                </p>
              )}
              <p className={sheet.muted}>
                Комиссии и налоги не входят в расчёт. НКД учтён в сделках, стоимости и купонах.
              </p>
            </div>
          </section>
          {!!data.accounts.length && (
            <section className={styles.section} aria-label="Позиции и результат по счетам">
              <h2>По счетам</h2>
              <div className={styles.scroll}>
                <table
                  aria-label="Инструмент по счетам"
                  className={`${styles.table} ${styles.accountsTable}`}
                >
                  <colgroup>
                    <col />
                    <col />
                    <col />
                    <col />
                    <col />
                    {showAnnual && <col />}
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Счёт</th>
                      <th scope="col">Количество</th>
                      <th scope="col">Стоимость</th>
                      <th scope="col">Результат</th>
                      <th scope="col">На вложенное</th>
                      {showAnnual && <th scope="col">Годовых</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {data.accounts.map((account) => {
                      const clean = account.clean;
                      const pnl = clean
                        ? cleanMetric(clean.pnl.value !== null ? clean.pnl : clean.known_result)
                        : unavailable;
                      const simple = clean?.simple_return
                        ? positionRateMetric(clean.simple_return)
                        : unavailable;
                      const annual = clean?.xirr ? positionRateMetric(clean.xirr) : unavailable;
                      return (
                        <tr
                          key={account.scope}
                          data-capital-context={
                            matches.length === 1 && matches[0] === account ? "true" : undefined
                          }
                        >
                          <th scope="row">
                            <Link
                              to={accountHref(account.scope, account.period)}
                              title={account.account_link?.source_account_id}
                            >
                              {accountName(account.scope, account.label)}
                            </Link>
                          </th>
                          <td>
                            {account.detail?.closing_quantity != null
                              ? formatQuantity(account.detail.closing_quantity)
                              : "—"}
                          </td>
                          <td title={clean ? money(clean.closing_value.value) : undefined}>
                            {clean ? displayWhole(cleanMetric(clean.closing_value)) : "—"}
                          </td>
                          <td data-tone={tone(pnl)} title={displayMetric(pnl, true)}>
                            {displayWhole(pnl, true)}
                          </td>
                          <td data-tone={tone(simple)}>{displayCompactRate(simple)}</td>
                          {showAnnual && (
                            <td data-tone={tone(annual)} title={positionRatePeriod(clean?.xirr)}>
                              {displayCompactRate(annual)}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <details className={styles.details}>
                <summary>Подробнее о расчёте по счетам</summary>
                {data.accounts.map((account) => (
                  <section key={account.scope}>
                    <h3>{accountName(account.scope, account.label)}</h3>
                    {account.ai_account_ref && <small>В отчёте AI: {account.ai_account_ref}</small>}
                    <ReturnsResultMeta
                      period={account.period}
                      valuationDate={account.valuation_date}
                      accountLink={
                        account.account_link
                          ? {
                              ...account.account_link,
                              label: accountName(account.scope, account.label),
                            }
                          : null
                      }
                    />
                    {!account.included && <small>Не включён в общий результат</small>}
                    <ReturnsInstrumentResult
                      result={
                        account.clean
                          ? {
                              pnl: cleanMetric(
                                account.clean.pnl.value !== null
                                  ? account.clean.pnl
                                  : account.clean.known_result,
                              ),
                              rate: cleanMetric(account.clean.modified_dietz, true),
                            }
                          : null
                      }
                      positionRates={
                        account.clean?.simple_return
                          ? {
                              simple: account.clean.simple_return,
                              xirr: account.clean.xirr ?? null,
                            }
                          : null
                      }
                      reasonCodes={account.reason_codes.filter((code) => !shownCaveats.has(code))}
                    />
                    {account.clean && (
                      <div>
                        <h4>Составляющие результата</h4>
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
                              {part.status === "partial" && " · включены не все операции"}
                            </p>
                          ))}
                      </div>
                    )}
                  </section>
                ))}
                <p>
                  «На вложенное» — результат позиции к сумме покупок, без пересчёта на год. Годовая
                  — XIRR по датам покупок, продаж и выплат; показывается после среднего срока
                  вложения не меньше года.
                </p>
              </details>
            </section>
          )}
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
                    {!selectedScope && <strong>{accountName(account.scope, account.label)}</strong>}
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
                      <span>{accountName(account.scope, account.label)}</span>
                      {account.period && (
                        <span className={sheet.muted}>
                          {" "}
                          · {dateLabel(account.period.start)} – {dateLabel(account.period.end)}
                        </span>
                      )}
                    </h3>
                    <table
                      aria-label="Покупки инструмента"
                      className={`${styles.table} ${styles.lots}`}
                    >
                      <thead>
                        <tr>
                          <th scope="col">Дата покупки</th>
                          <th scope="col">Куплено / осталось</th>
                          <th scope="col">Вложено</th>
                          <th scope="col">Продажи / остаток</th>
                          <th scope="col">Результат без выплат</th>
                          <th scope="col">К первоначальной стоимости</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(expandedPurchases.includes(account.scope)
                          ? account.purchases
                          : account.purchases.slice(0, 5)
                        ).map((purchase) => (
                          <tr key={purchase.id}>
                            <td>{dateLabel(purchase.date)}</td>
                            <td>
                              {formatQuantity(purchase.quantity)} /{" "}
                              {purchase.remaining_quantity === null
                                ? "—"
                                : formatQuantity(purchase.remaining_quantity)}
                            </td>
                            <td title={money(purchase.cost_kopecks)}>
                              {purchaseMoney(purchase.cost_kopecks)}
                            </td>
                            <td>
                              {purchase.sale_proceeds_kopecks !== "0" && (
                                <span title={money(purchase.sale_proceeds_kopecks)}>
                                  {purchaseMoney(purchase.sale_proceeds_kopecks)}
                                  <small>продажи</small>
                                </span>
                              )}
                              {purchase.value_kopecks !== "0" && (
                                <span title={money(purchase.value_kopecks)}>
                                  {purchaseMoney(purchase.value_kopecks)}
                                  <small>остаток</small>
                                </span>
                              )}
                              {purchase.sale_proceeds_kopecks === "0" &&
                              purchase.value_kopecks === "0"
                                ? purchaseMoney("0")
                                : null}
                            </td>
                            <td
                              data-tone={amountTone(purchase.price_result_kopecks)}
                              title={money(purchase.price_result_kopecks)}
                            >
                              {purchaseMoney(purchase.price_result_kopecks, true)}
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
                                displayCompactRate({
                                  ...unavailable,
                                  value: purchase.return_fraction,
                                  unit: "fraction",
                                })
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {account.purchases.length > 5 && (
                      <button
                        className={styles.more}
                        type="button"
                        onClick={() =>
                          setExpandedPurchases((shown) =>
                            shown.includes(account.scope)
                              ? shown.filter((scope) => scope !== account.scope)
                              : [...shown, account.scope],
                          )
                        }
                      >
                        {expandedPurchases.includes(account.scope)
                          ? "Свернуть покупки"
                          : `Показать все ${account.purchases.length}`}
                      </button>
                    )}
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
          {operations.length > 0 && (
            <details
              className={`${styles.section} ${styles.details}`}
              aria-label="Покупки и продажи"
            >
              <summary>Сделки · {operations.length}</summary>
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
                  <table
                    aria-label="Операции инструмента"
                    className={`${styles.table} ${styles.operations}`}
                  >
                    <thead>
                      <tr>
                        <th scope="col">Дата</th>
                        <th scope="col">Операция</th>
                        {data.accounts.length > 1 && <th scope="col">Счёт</th>}
                        <th scope="col">Количество</th>
                        <th scope="col">Сумма сделки</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.slice(0, visibleOperations).map((row) => (
                        <tr key={row.key}>
                          <td>{dateLabel(row.date)}</td>
                          <td>{row.side === "BUY" ? "Покупка" : "Продажа"}</td>
                          {data.accounts.length > 1 && (
                            <td>{accountName(row.scope, row.account)}</td>
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
            </details>
          )}
          {payouts.length > 0 && (
            <details className={`${styles.section} ${styles.details}`}>
              <summary>
                Выплаты · {payouts.length}
                {data.summary.payouts.value !== null && ` · ${displayWhole(data.summary.payouts)}`}
              </summary>
              <div className={styles.scroll}>
                <table
                  aria-label="Выплаты инструмента"
                  className={`${styles.table} ${styles.operations}`}
                >
                  <thead>
                    <tr>
                      <th scope="col">Дата</th>
                      <th scope="col">Выплата</th>
                      {data.accounts.length > 1 && <th scope="col">Счёт</th>}
                      <th scope="col">Получено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payouts.map(({ account, scope, event }) => (
                      <tr key={`${scope}/${event.event_key}`}>
                        <td>{dateLabel(event.event_date as string)}</td>
                        <td>{event.kind === "COUPON" ? "Купон" : "Дивиденд"}</td>
                        {data.accounts.length > 1 && <td>{accountName(scope, account)}</td>}
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
                  <h3>{accountName(account.scope, account.label)}</h3>
                  <Explanation
                    context={{
                      account: accountName(account.scope, account.label),
                      instrument: data.name,
                    }}
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
