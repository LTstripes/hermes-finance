import { useState } from "react";
import layout from "./Dashboard.module.css";
import {
  compareDecimal,
  displayMetric,
  displayWhole,
  type Instrument,
  isPartialResult,
  type Period,
  periodLabel,
  ranked,
  tone,
} from "./model";
import { ReturnsDetail } from "./ReturnsDetail";
import { CompactValue, Explanation } from "./ReturnsInfo";
import styles from "./Returns.module.css";

export function ReturnsMonthInstruments({
  rows,
  period,
  scope,
  revision,
  reasonCodes,
  initialIsin,
}: {
  rows: Instrument[];
  period: Period;
  scope: string;
  revision: number;
  reasonCodes: string[];
  initialIsin: string | null;
}) {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState("pnl-desc");
  const [expanded, setExpanded] = useState(initialIsin);
  const [showAll, setShowAll] = useState(false);
  const filtered = rows.filter(
    (row) =>
      (kind === "all" || row.kind === kind) &&
      `${row.name} ${row.isin}`.toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru")),
  );
  const [field, direction] = sort.split("-");
  filtered.sort((a, b) => {
    const x = field === "name" ? a.name : a[field as "pnl" | "rate"].value;
    const y = field === "name" ? b.name : b[field as "pnl" | "rate"].value;
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return (
      (field === "name" ? x.localeCompare(y, "ru") : compareDecimal(x, y)) *
        (direction === "asc" ? 1 : -1) || a.isin.localeCompare(b.isin)
    );
  });
  // Match the overview: partial figures remain in the table, outside rankings.
  const full = rows.filter((row) => !isPartialResult(row.pnl));
  const leaders = [true, false].flatMap((positive) => ranked(full, period, "pnl", positive));
  const maximum = leaders.reduce((max, row) => {
    const value = BigInt(row.pnl.value ?? "0");
    const abs = value < 0n ? -value : value;
    return abs > max ? abs : max;
  }, 1n);
  const partial = rows.some((row) => isPartialResult(row.pnl));
  const missing = rows.some((row) => row.pnl.value === null || row.rate.value === null);
  return (
    <>
      <section className={styles.panel} aria-labelledby="returns-instruments">
        <div className={styles.sectionHead}>
          <h2 id="returns-instruments">По инструментам</h2>
          <span>{rows.length} бумаг</span>
        </div>
        <div className={layout.filters}>
          <label className={layout.search}>
            Поиск
            <input
              type="search"
              placeholder="Название или ISIN"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setShowAll(false);
              }}
            />
          </label>
          <label>
            Тип
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setShowAll(false);
              }}
            >
              <option value="all">Все бумаги</option>
              <option value="stock">Акции</option>
              <option value="bond">Облигации</option>
            </select>
          </label>
        </div>
        {(partial || missing) && (
          <p className={layout.caveat}>
            {partial && "Неполный результат — известная часть, без неподтверждённой оценки. "}
            {missing &&
              "Прочерк — нет подтверждённого значения; причины доступны в подробностях ниже."}
          </p>
        )}
        {!filtered.length ? (
          <p>Бумаги не найдены.</p>
        ) : (
          <table
            className={`${layout.list} ${styles.monthInstruments}`}
            aria-label="Бумаги за период"
          >
            <colgroup>
              <col />
              <col />
              <col />
              <col />
            </colgroup>
            <thead>
              <tr>
                {[
                  ["name", "Бумага"],
                  ["pnl", "Результат, ₽"],
                  ["rate", "За период"],
                ].map(([key, title]) => (
                  <th
                    key={key}
                    aria-sort={
                      field === key ? (direction === "asc" ? "ascending" : "descending") : "none"
                    }
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setSort(`${key}-${field === key && direction === "desc" ? "asc" : "desc"}`)
                      }
                    >
                      {title}
                    </button>
                  </th>
                ))}
                <th>Купоны и дивиденды, ₽</th>
              </tr>
            </thead>
            <tbody>
              {(showAll ? filtered : filtered.slice(0, 10)).map((row) => (
                <tr key={row.isin}>
                  <th scope="row" title={`${row.name} · ${row.isin}`}>
                    <button
                      type="button"
                      className={layout.linkButton}
                      onClick={() => setExpanded(row.isin)}
                    >
                      {row.name}
                    </button>
                    <small>
                      {row.name !== row.isin
                        ? row.isin
                        : row.kind === "bond"
                          ? "Облигация"
                          : "Акция"}
                      {isPartialResult(row.pnl) && " · неполный"}
                    </small>
                  </th>
                  <td>
                    <CompactValue metric={row.pnl} signed />
                  </td>
                  <td>
                    <CompactValue metric={row.rate} />
                  </td>
                  <td>
                    <span title="Купоны">
                      <CompactValue metric={row.coupons} />
                    </span>
                    <span className={layout.muted}> / </span>
                    <span title="Дивиденды">
                      <CompactValue metric={row.dividends} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {filtered.length > 10 && (
          <button type="button" className={layout.more} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Показать 10" : "Показать все"}
          </button>
        )}
        <details className={layout.footer}>
          <summary>Подробнее о бумагах</summary>
          <p>
            Процент — Modified Dietz за период, без пересчёта на год. Купоны / дивиденды показаны
            раздельно и уже включены в результат.
          </p>
          <Explanation codes={reasonCodes} />
          {rows
            .filter(
              (row) =>
                row.pnl.reason_codes.length ||
                row.rate.reason_codes.length ||
                row.name === row.isin,
            )
            .map((row) => (
              <div key={row.isin}>
                <strong>{row.name}</strong>
                {row.name === row.isin && <p>Название бумаги не найдено; показан ISIN.</p>}
                <Explanation
                  codes={[...new Set([...row.pnl.reason_codes, ...row.rate.reason_codes])]}
                />
              </div>
            ))}
        </details>
      </section>
      {leaders.length > 0 && (
        <section className={styles.panel} aria-labelledby="returns-leaders">
          <div className={styles.sectionHead}>
            <div>
              <h2 id="returns-leaders">Лидеры и отстающие</h2>
              <p>{periodLabel(period)}</p>
            </div>
          </div>
          <ol className={`${layout.leaderList} ${styles.monthLeaders}`}>
            {leaders.map((row) => {
              const value = BigInt(row.pnl.value ?? "0");
              return (
                <li key={row.isin} className={layout.leaderRow}>
                  <button
                    type="button"
                    className={layout.linkButton}
                    onClick={() => setExpanded(row.isin)}
                  >
                    {row.name}
                  </button>
                  <span className={layout.barTrack} data-tone={tone(row.pnl)} aria-hidden="true">
                    <span
                      className={layout.bar}
                      data-tone={tone(row.pnl)}
                      style={{
                        width: `${Number(((value < 0n ? -value : value) * 5000n) / maximum) / 100}%`,
                      }}
                    />
                  </span>
                  <strong
                    className={layout.leaderAmount}
                    data-tone={tone(row.pnl)}
                    title={displayMetric(row.pnl, true)}
                  >
                    {displayWhole(row.pnl, true)}
                  </strong>
                </li>
              );
            })}
          </ol>
        </section>
      )}
      {expanded && (
        <section className={styles.panel} aria-label="Выбранная бумага">
          <div className={styles.sectionHead}>
            <h2>Подробности бумаги</h2>
            <button type="button" onClick={() => setExpanded(null)}>
              Закрыть подробности
            </button>
          </div>
          <ReturnsDetail
            key={expanded}
            scope={scope}
            period={period}
            isin={expanded}
            revision={revision}
          />
        </section>
      )}
    </>
  );
}
