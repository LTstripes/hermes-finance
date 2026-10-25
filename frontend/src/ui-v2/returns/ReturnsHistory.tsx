import { useState } from "react";
import {
  displayMetric,
  monthLabel,
  periodKey,
  samePeriod,
  type Period,
  type Result,
} from "./model";
import { Value } from "./ReturnsInfo";
import styles from "./Returns.module.css";

export function ReturnsHistory({
  rows,
  selected,
  choose,
}: {
  rows: Result[];
  selected: Period;
  choose: (p: Period) => void;
}) {
  const [page, setPage] = useState(0);
  const end = Math.max(0, rows.length - page * 12);
  const visible = rows.slice(Math.max(0, end - 12), end);
  const values = visible.map((r) =>
    r.pnl.value !== null && /^-?\d+$/.test(r.pnl.value) ? BigInt(r.pnl.value) : null,
  );
  const maximum = values.reduce<bigint>(
    (m, v) => (v !== null && (v < 0n ? -v : v) > m ? (v < 0n ? -v : v) : m),
    1n,
  );
  return (
    <section className={styles.panel} aria-labelledby="returns-history">
      <div className={styles.sectionHead}>
        <h2 id="returns-history">Результат по месяцам</h2>
        <div className={styles.pager}>
          <button
            type="button"
            disabled={end <= 12}
            onClick={() => setPage(page + 1)}
            aria-label="Более ранние месяцы"
          >
            ←
          </button>
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
            aria-label="Более поздние месяцы"
          >
            →
          </button>
        </div>
      </div>
      {!rows.length ? (
        <p>Месячных результатов пока нет.</p>
      ) : (
        <>
          <fieldset className={styles.chart} aria-label="История результата в рублях">
            {visible.map((row, index) => {
              const value = values[index];
              const negative = value !== null && value < 0n;
              // The sole Number conversion is final pixel geometry, after exact scaling.
              const height =
                value === null
                  ? 0
                  : Math.max(
                      value === 0n ? 2 : 4,
                      Number(((negative ? -value : value) * 72n) / maximum),
                    );
              return (
                <button
                  type="button"
                  key={periodKey(row.period)}
                  className={styles.monthBar}
                  aria-pressed={samePeriod(row.period, selected)}
                  aria-label={`${monthLabel(row.period)}: ${displayMetric(row.pnl, true)}`}
                  title={displayMetric(row.pnl, true)}
                  onClick={() => choose(row.period)}
                >
                  <span className={styles.plot} aria-hidden="true">
                    <span className={negative ? styles.downBar : styles.upBar} style={{ height }} />
                    {value === null && <span className={styles.gap}>—</span>}
                  </span>
                  <span>
                    {value === null ? "—" : value > 0n ? "+" : value < 0n ? "−" : "0"}{" "}
                    {monthLabel(row.period)}
                  </span>
                </button>
              );
            })}
          </fieldset>
          <details className={styles.historyTable}>
            <summary>Месяцы таблицей</summary>
            <table>
              <thead>
                <tr>
                  <th>Месяц</th>
                  <th>Результат</th>
                  <th>Доходность</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={periodKey(r.period)}>
                    <th>
                      <button type="button" onClick={() => choose(r.period)}>
                        {monthLabel(r.period)}
                      </button>
                    </th>
                    <td>
                      <Value metric={r.pnl} label={`${monthLabel(r.period)}: результат`} signed />
                    </td>
                    <td>
                      <Value metric={r.rate} label={`${monthLabel(r.period)}: доходность`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}
