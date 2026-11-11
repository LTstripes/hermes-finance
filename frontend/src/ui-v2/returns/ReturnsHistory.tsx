import { useState, type ReactNode } from "react";
import {
  displayMetric,
  isPartialResult,
  monthLabel,
  type Period,
  periodKey,
  type Result,
  samePeriod,
} from "./model";
import styles from "./Returns.module.css";
import { CompactValue } from "./ReturnsInfo";
import layout from "./Dashboard.module.css";

export function ReturnsHistory({
  rows,
  selected,
  choose,
  summary,
}: {
  rows: Result[];
  selected: Period;
  choose: (p: Period) => void;
  summary?: ReactNode;
}) {
  const [page, setPage] = useState(() => {
    const selectedIndex = rows.findIndex((row) => samePeriod(row.period, selected));
    return selectedIndex < 0 ? 0 : Math.floor((rows.length - 1 - selectedIndex) / 12);
  });
  const end = Math.max(0, rows.length - page * 12);
  const visible = rows.slice(Math.max(0, end - 12), end);
  const values = visible.map((r) =>
    r.pnl.value !== null && /^-?\d+$/.test(r.pnl.value) ? BigInt(r.pnl.value) : null,
  );
  const maximum = values.reduce<bigint>(
    (m, v) => (v !== null && (v < 0n ? -v : v) > m ? (v < 0n ? -v : v) : m),
    1n,
  );
  const partial = rows.some((row) => isPartialResult(row.pnl));
  const coupons = rows.some((row) => row.coupons.value !== null && row.coupons.value !== "0");
  const dividends = rows.some((row) => row.dividends.value !== null && row.dividends.value !== "0");
  return (
    <section className={styles.panel} aria-labelledby="returns-history">
      {!rows.length ? (
        <p>Месячных результатов пока нет.</p>
      ) : (
        <>
          <div className={summary ? styles.monthLead : undefined}>
            {summary && <div>{summary}</div>}
            <div>
              <div className={styles.sectionHead}>
                <h2 id="returns-history">
                  {partial ? "Известная часть по месяцам" : "Результат по месяцам"}
                </h2>
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
              {values.some((value) => value !== null) && (
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
                        aria-label={`${monthLabel(row.period)}: ${partial ? "известная часть: " : ""}${displayMetric(row.pnl, true)}`}
                        title={displayMetric(row.pnl, true)}
                        onClick={() => choose(row.period)}
                      >
                        <span className={styles.plot} aria-hidden="true">
                          <span
                            className={negative ? styles.downBar : styles.upBar}
                            style={{ height }}
                          />
                          {value === null && <span className={styles.gap}>—</span>}
                        </span>
                        <span>
                          {
                            [
                              "янв",
                              "фев",
                              "мар",
                              "апр",
                              "май",
                              "июн",
                              "июл",
                              "авг",
                              "сен",
                              "окт",
                              "ноя",
                              "дек",
                            ][Number(row.period.end.slice(5, 7)) - 1]
                          }
                        </span>
                      </button>
                    );
                  })}
                </fieldset>
              )}
            </div>
          </div>
          <div className={styles.historyTable}>
            <p className={layout.note}>
              {partial
                ? "Известная часть — подтверждённые составляющие без полной оценки счёта. "
                : ""}
              Прочерк означает отсутствие подтверждённого значения.
            </p>
            <table className={`${layout.list} ${styles.monthTable}`}>
              <thead>
                <tr>
                  <th>Месяц</th>
                  <th>{partial ? "Известная часть, ₽" : "Результат, ₽"}</th>
                  <th>За месяц</th>
                  {coupons && <th>Купоны, ₽</th>}
                  {dividends && <th>Дивиденды, ₽</th>}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={periodKey(r.period)}
                    data-selected={samePeriod(r.period, selected) || undefined}
                  >
                    <th>
                      <button
                        type="button"
                        className={layout.quiet}
                        aria-pressed={samePeriod(r.period, selected)}
                        onClick={() => choose(r.period)}
                      >
                        {monthLabel(r.period)}
                      </button>
                    </th>
                    <td>
                      <CompactValue metric={r.pnl} signed />
                    </td>
                    <td>
                      <CompactValue metric={r.rate} />
                    </td>
                    {coupons && (
                      <td>
                        <CompactValue metric={r.coupons} />
                      </td>
                    )}
                    {dividends && (
                      <td>
                        <CompactValue metric={r.dividends} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
