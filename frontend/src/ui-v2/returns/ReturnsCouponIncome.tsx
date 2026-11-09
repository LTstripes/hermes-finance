import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getIncome, type IncomeKind } from "./cards";
import layout from "./Dashboard.module.css";
import { readDisplayNames } from "./dashboard";
import { dateLabel, displayMetric, displayWhole, isPartialResult } from "./model";
import type { CouponIncome } from "./overall";
import styles from "./Returns.module.css";

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
    staleTime: 5 * 60 * 1000,
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
    .flatMap((r) =>
      r.accounts
        .filter((account) => included(account.scope))
        .map((account) => ({
          ...r,
          amount: account.amount,
          account,
        })),
    )
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
                <tr key={`${row.isin}:${row.account.scope}`}>
                  <th>
                    <button
                      type="button"
                      className={layout.linkButton}
                      onClick={() => openInstrument?.(row.isin)}
                    >
                      {row.name}
                    </button>
                    <small>
                      {names[row.account.scope] || row.account.label}
                      {row.account.period &&
                        ` · ${dateLabel(row.account.period.start)} — ${dateLabel(row.account.period.end)}`}
                    </small>
                    <details>
                      <summary>Показать выплаты</summary>
                      <ul>
                        {data.events
                          .filter((e) => e.isin === row.isin && e.scope === row.account.scope)
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
      className={compact ? `${layout.figure} ${open ? layout.figureOpen : ""}` : styles.panel}
      aria-label={titles[kind]}
    >
      <h2>{titles[kind]}</h2>
      <strong title={displayMetric(value.known_total)}>
        {compact ? displayWhole(value.known_total) : displayMetric(value.known_total)}
      </strong>
      {value.included_accounts < value.selected_accounts ? (
        <small>
          Учтены {value.included_accounts} из {value.selected_accounts} счетов, не полный итог
        </small>
      ) : (
        isPartialResult(value.known_total) && <small>По известным выплатам, не полный итог</small>
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
