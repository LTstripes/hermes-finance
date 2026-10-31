import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getIncome, type IncomeKind } from "./cards";
import { dateLabel, displayMetric } from "./model";
import { knownMoney, readDisplayNames } from "./dashboard";
import type { CouponIncome } from "./overall";
import styles from "./Returns.module.css";
import layout from "./Dashboard.module.css";

const titles = { coupon: "Полученные купоны", dividend: "Полученные дивиденды" };
function Breakdown({
  kind,
  revision,
  scopes,
  openInstrument,
}: {
  kind: IncomeKind;
  revision: number;
  scopes?: string[];
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
  if (query.isFetching || !query.data) return <p role="status">Загружаем выплаты…</p>;
  const data = query.data;
  const names = readDisplayNames();
  const included = (s: string) => !scopes || scopes.includes(s);
  const rows = data.instruments
    .map((r) => ({
      ...r,
      amount: knownMoney(r.accounts.filter((a) => included(a.scope)).map((a) => a.amount)),
    }))
    .filter((r) => r.amount.value !== null && r.amount.value !== "0");
  const unresolved = data.events.filter((e) => included(e.scope) && !e.isin);
  return (
    <>
      {rows.length > 0 && (
        <div className={styles.tableScroll}>
          <table className={styles.instruments}>
            <thead>
              <tr>
                <th>Инструмент</th>
                <th>Получено</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.isin}>
                  <th>
                    <button type="button" onClick={() => openInstrument?.(row.isin)}>
                      {row.name}
                    </button>
                    <details>
                      <summary>Показать выплаты</summary>
                      <ul>
                        {data.events
                          .filter((e) => e.isin === row.isin && included(e.scope))
                          .map((event, index) => (
                            // biome-ignore lint/suspicious/noArrayIndexKey: No public event ID; preserve distinct identical-looking source occurrences.
                            <li key={`${event.scope}/${event.date}/${index}`}>
                              {dateLabel(event.date)} · {names[event.scope] || event.label} ·{" "}
                              {displayMetric(event.amount)}
                            </li>
                          ))}
                      </ul>
                    </details>
                  </th>
                  <td>{displayMetric(row.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {unresolved.length > 0 && (
        <details>
          <summary>Выплаты без установленного инструмента</summary>
          <ul>
            {unresolved.map((event, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: No public event ID; preserve distinct identical-looking source occurrences.
              <li key={`${event.scope}/${event.date}/${index}`}>
                {dateLabel(event.date)} · {names[event.scope] || event.label} ·{" "}
                {displayMetric(event.amount)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!rows.length && !unresolved.length && (
        <p className={layout.note}>
          Известная сумма показана выше; разбивка по бумагам пока не подтверждена.
        </p>
      )}
    </>
  );
}
export function ReturnsCouponIncome({
  value,
  kind = "coupon",
  revision = 0,
  openInstrument,
  scopes,
  compact = false,
}: {
  value: CouponIncome;
  kind?: IncomeKind;
  revision?: number;
  openInstrument?: (isin: string) => void;
  scopes?: string[];
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section
      className={compact ? styles.card : styles.panel}
      style={compact && open ? { gridColumn: "1 / -1" } : undefined}
      aria-label={titles[kind]}
    >
      <h2>{titles[kind]}</h2>
      <div className={layout.value}>{displayMetric(value.known_total)}</div>
      {value.included_accounts < value.selected_accounts && (
        <p className={layout.note}>
          Известная часть: {value.included_accounts} из {value.selected_accounts} счетов.
        </p>
      )}
      <details className={layout.income} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>По инструментам</summary>
        {open && (
          <Breakdown
            kind={kind}
            revision={revision}
            scopes={scopes}
            openInstrument={openInstrument}
          />
        )}
      </details>
    </section>
  );
}
