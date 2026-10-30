import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { formatQuantity } from "../../lib/format";
import { money } from "../SourceInstrumentDetail";
import { getInstrumentCard } from "./cards";
import { dateLabel, periodLabel } from "./model";
import { canonicalId, validDetailPeriod } from "./navigation";
import { accountHref } from "./overall";
import styles from "./Returns.module.css";
import { MissingName } from "./ReturnsAvailable";
import { ReturnsDetailBody } from "./ReturnsDetail";
import { Explanation, Value } from "./ReturnsInfo";

export function ReturnsInstrumentCard({
  isin,
  revision,
  capitalAccount,
  capitalRequested = false,
  selectedScope,
  selectedStart,
  selectedEnd,
  close,
}: {
  isin: string;
  revision: number;
  capitalAccount: string | null;
  capitalRequested?: boolean;
  selectedScope?: string | null;
  selectedStart?: string | null;
  selectedEnd?: string | null;
  close: () => void;
}) {
  const query = useQuery({
    queryKey: ["returns", "instrument-card", isin, revision],
    queryFn: ({ signal }) => getInstrumentCard(isin, signal),
    staleTime: 0,
  });
  const data = !query.isFetching && !query.isError ? query.data : undefined;
  const id = canonicalId(capitalAccount);
  const matches =
    data?.accounts.filter((account) => id !== null && account.canonical_account_id === id) ?? [];
  return (
    <section className={styles.detail} aria-label={`Карточка инструмента ${isin}`}>
      <button type="button" onClick={close}>
        К списку инструментов
      </button>
      {query.isError ? (
        <p role="alert">
          Не удалось загрузить карточку инструмента.{" "}
          <button type="button" onClick={() => void query.refetch()}>
            Повторить карточку
          </button>
        </p>
      ) : query.isFetching ? (
        <p role="status">Загружаем карточку по всем счетам…</p>
      ) : null}
      {data && (
        <>
          <header>
            <h3>
              {data.name} <MissingName name={data.name} isin={data.isin} />
            </h3>
            <p>
              {data.isin} ·{" "}
              {data.kind === "bond"
                ? "Облигация"
                : data.kind === "stock"
                  ? "Акция"
                  : data.kind === "gold"
                    ? "Золото"
                    : "Инструмент"}{" "}
              · все счета и доступная история
            </p>
          </header>
          {capitalRequested && (
            <p>
              {matches.length === 1
                ? "Переход из Капитала: соответствующий счёт отмечен; карточка показывает все счета."
                : "Контекст счёта из Капитала не подтверждён однозначно; карточка показывает все счета без выбора по названию."}
            </p>
          )}
          <div className={styles.cards}>
            <section className={styles.card} aria-label="Известное количество инструмента">
              <h4>Известное количество по отчётам</h4>
              <strong>{formatQuantity(data.summary.quantity.value)}</strong>
              <Explanation codes={data.summary.quantity.reason_codes} />
            </section>
            <section className={styles.card}>
              <h4>Известная стоимость по отчётам</h4>
              <Value metric={data.summary.reported_value} label="Известная отчётная стоимость" />
            </section>
            <section className={styles.card}>
              <h4>Известный P&amp;L</h4>
              <Value metric={data.summary.pnl} label="Известный P&L инструмента" signed />
            </section>
            <section className={styles.card}>
              <h4>Полученные выплаты</h4>Купоны{" "}
              <Value metric={data.summary.coupons} label="Купоны инструмента" />
              Дивиденды <Value metric={data.summary.dividends} label="Дивиденды инструмента" />
            </section>
          </div>
          <p>
            Частичное покрытие. Количество и стоимость сообщены на даты сохранённых отчётов:{" "}
            {data.summary.valuation_dates.length
              ? data.summary.valuation_dates.map(dateLabel).join(", ")
              : "даты не подтверждены"}
            . Это не единая текущая оценка. Проценты приведены отдельно по счетам и их периодам.
          </p>
          <details className={styles.diagnostics}>
            <summary>Компоненты результата и ограничения</summary>
            <div className={styles.cards}>
              {(
                [
                  ["Переоценка и торговый результат", data.summary.valuation_and_trades],
                  ["Купоны", data.summary.coupons],
                  ["Дивиденды", data.summary.dividends],
                  ["Погашения", data.summary.redemption],
                  ["Комиссии", data.summary.costs],
                  ["Налоги", data.summary.taxes],
                ] as const
              ).map(([label, metric]) => (
                <section key={label}>
                  <h4>{label}</h4>
                  <Value metric={metric} label={label} />
                </section>
              ))}
            </div>
            <p>
              Переоценка и торговый результат не являются чистым изменением цены. Комиссии и налоги
              уже учтены в P&amp;L и приведены справочно; повторного вычитания нет. При пробелах
              компоненты не подгоняются к итогу.
            </p>
            <Explanation codes={[...data.summary.reason_codes, ...data.reason_codes]} />
            <code>
              {[...new Set([...data.summary.reason_codes, ...data.reason_codes])].join(", ")}
            </code>
          </details>
          <h4>Все счета этого ISIN</h4>
          {!data.accounts.length ? (
            <p>Нет доступной истории по счетам для этого точного ISIN.</p>
          ) : (
            <div className={styles.tableScroll}>
              <table className={styles.instruments}>
                <thead>
                  <tr>
                    <th>Счёт / период</th>
                    <th>Количество / отчётная стоимость</th>
                    <th>P&amp;L</th>
                    <th>Доходность счёта</th>
                    <th>Купоны / дивиденды</th>
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
                      <th>
                        {account.label}
                        <small>
                          {account.period ? periodLabel(account.period) : "Интервал не подтверждён"}
                        </small>
                        <Link to={accountHref(account.scope, account.period)}>История счёта</Link>
                        <small>
                          {account.included
                            ? "Включён в известную часть"
                            : "Не включён в известную часть"}{" "}
                          · {account.proof_status}
                        </small>
                        <Explanation codes={account.reason_codes} />
                        {account.exclusion_reason && <code>{account.exclusion_reason}</code>}
                      </th>
                      {account.detail ? (
                        <>
                          <td>
                            {formatQuantity(account.detail.closing_quantity)}
                            <br />
                            {money(account.detail.analysis.closing.reported_value_kopecks)}
                            <small>на {dateLabel(account.detail.analysis.closing.date)}</small>
                          </td>
                          <td>
                            <Value
                              metric={account.detail.pnl}
                              label={`${account.label}: P&L`}
                              signed
                            />
                          </td>
                          <td>
                            <Value
                              metric={account.detail.rate}
                              label={`${account.label}: доходность`}
                            />
                          </td>
                          <td>
                            <Value
                              metric={account.detail.coupons}
                              label={`${account.label}: купоны`}
                            />
                            <span> / </span>
                            <Value
                              metric={account.detail.dividends}
                              label={`${account.label}: дивиденды`}
                            />
                          </td>
                        </>
                      ) : (
                        <td colSpan={4}>
                          Актуальный разбор недоступен. Старые числовые значения не подставляются.
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.accounts.map((account) =>
            account.detail && validDetailPeriod(account.period) ? (
              <details
                key={account.scope}
                className={styles.diagnostics}
                open={
                  (selectedScope === account.scope &&
                    selectedStart === account.period?.start &&
                    selectedEnd === account.period?.end) ||
                  undefined
                }
              >
                <summary>Операции и расчёт: {account.label}</summary>
                <p>
                  {periodLabel(account.period)} · {account.scope}
                </p>
                <ReturnsDetailBody detail={account.detail} />
              </details>
            ) : null,
          )}
        </>
      )}
    </section>
  );
}
