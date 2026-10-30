import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { getIncome, type IncomeKind } from "./cards";
import { dateLabel, periodLabel } from "./model";
import { validIsin } from "./navigation";
import { accountHref, type CouponIncome } from "./overall";
import styles from "./Returns.module.css";
import { Explanation, Value } from "./ReturnsInfo";
const labels = {
  coupon: { title: "Полученные купоны", noun: "купонов" },
  dividend: { title: "Полученные дивиденды", noun: "дивидендов" },
};
const statusLabels = {
  current: "проверка актуальна",
  stale: "проверка устарела",
  absent: "проверки нет",
  conflict: "конфликт данных",
};
function IncomeBreakdown({
  kind,
  revision,
  openInstrument,
}: {
  kind: IncomeKind;
  revision: number;
  openInstrument?: (isin: string) => void;
}) {
  const query = useQuery({
    queryKey: ["returns", "income", kind, revision],
    queryFn: ({ signal }) => getIncome(kind, signal),
    staleTime: 0,
  });
  if (query.isError)
    return (
      <p role="alert">
        Не удалось загрузить выплаты.{" "}
        <button type="button" onClick={() => void query.refetch()}>
          Повторить выплаты
        </button>
      </p>
    );
  if (query.isFetching || !query.data) return <p role="status">Загружаем полученные выплаты…</p>;
  const data = query.data;
  return (
    <>
      <Explanation codes={data.reason_codes} />
      <h3>По счетам и периодам</h3>
      {!data.summary.accounts.length ? (
        <p>Нет подтверждённой истории выплат по счетам.</p>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.instruments}>
            <thead>
              <tr>
                <th>Счёт / период</th>
                <th>Полученные выплаты</th>
                <th>Покрытие</th>
              </tr>
            </thead>
            <tbody>
              {data.summary.accounts.map((account) => (
                <tr key={account.scope}>
                  <th>
                    <Link to={accountHref(account.scope, account.period)}>{account.label}</Link>
                    <small>
                      {account.period ? periodLabel(account.period) : "Интервал не подтверждён"}
                    </small>
                    <code>{account.scope}</code>
                  </th>
                  <td>
                    <Value
                      metric={account.amount}
                      label={`${account.label}: ${labels[kind].noun}`}
                    />
                  </td>
                  <td>
                    {statusLabels[account.proof_status]} ·{" "}
                    {account.included ? "включён" : "не включён"}
                    <Explanation codes={account.reason_codes} />
                    {account.exclusion_reason && <code>{account.exclusion_reason}</code>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>По ISIN</h3>
      <p>
        Неотнесённые к бумаге выплаты остаются в известном итоге счёта; они не распределяются по
        названию или сумме.
      </p>
      {!data.instruments.length ? (
        <p>Нет подтверждённой разбивки по ISIN.</p>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.instruments}>
            <thead>
              <tr>
                <th>Инструмент</th>
                <th>Получено</th>
                <th>Счета и периоды</th>
              </tr>
            </thead>
            <tbody>
              {data.instruments.map((instrument) => (
                <tr key={instrument.isin}>
                  <th>
                    {openInstrument && validIsin(instrument.isin) ? (
                      <button type="button" onClick={() => openInstrument(instrument.isin)}>
                        {instrument.name}
                      </button>
                    ) : (
                      instrument.name
                    )}
                    <small>{instrument.isin}</small>
                  </th>
                  <td>
                    <Value
                      metric={instrument.amount}
                      label={`${instrument.name}: ${labels[kind].noun}`}
                    />
                  </td>
                  <td>
                    {instrument.accounts.map((account) => (
                      <p key={account.scope}>
                        {account.label} ·{" "}
                        {account.period ? periodLabel(account.period) : "Интервал не подтверждён"}
                        <Value
                          metric={account.amount}
                          label={`${instrument.name}, ${account.label}: выплаты`}
                        />
                      </p>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>Фактически полученные выплаты</h3>
      {!data.events.length ? (
        <p>Нет доступных подтверждённых событий выплат.</p>
      ) : (
        <div className={styles.tableScroll}>
          <table className={styles.instruments}>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Счёт / инструмент</th>
                <th>Получено</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((event, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: This DTO has no event ID; preserve distinct equal-looking occurrences without financial deduplication.
                <tr key={`${event.scope}/${event.isin}/${event.date}/${index}`}>
                  <td>{event.date ? dateLabel(event.date) : "Дата не подтверждена"}</td>
                  <th>
                    {event.label}
                    <small>
                      {event.name ?? "Инструмент не установлен"} ·{" "}
                      {event.isin ?? "ISIN не подтверждён"}
                    </small>
                  </th>
                  <td>
                    <Value
                      metric={event.amount}
                      label={`${event.label}, ${event.date ?? "дата неизвестна"}: выплата`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className={styles.diagnostics}>
        <summary>Причины и ограничения выплат</summary>
        <code>{[...new Set([...data.reason_codes, ...data.summary.reason_codes])].join(", ")}</code>
      </details>
    </>
  );
}
export function ReturnsCouponIncome({
  value,
  kind = "coupon",
  revision = 0,
  openInstrument,
}: {
  value: CouponIncome;
  kind?: IncomeKind;
  revision?: number;
  openInstrument?: (isin: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className={styles.panel} aria-label={labels[kind].title}>
      <h2>{labels[kind].title} за доступную историю</h2>
      <section className={styles.mainValue} aria-label={`Известная сумма ${labels[kind].noun}`}>
        <Value metric={value.known_total} label={`${labels[kind].title} за доступную историю`} />
      </section>
      <p>
        Частичное покрытие: включено счетов {value.included_accounts} из {value.selected_accounts}.
        Только известная сохранённая история по выпискам; полнота за всё время, налоговый учёт и
        будущие выплаты не подтверждены.
      </p>
      <p>
        Выплаты уже входят в соответствующий результат счёта. Эта справочная сумма повторно не
        прибавляется к известному результату.
      </p>
      <details
        className={styles.diagnostics}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>Счета, периоды и покрытие {labels[kind].noun}</summary>
        {open && (
          <IncomeBreakdown kind={kind} revision={revision} openInstrument={openInstrument} />
        )}
      </details>
    </section>
  );
}
