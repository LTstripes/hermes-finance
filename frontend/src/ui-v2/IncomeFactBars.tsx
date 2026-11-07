import type { MoneyValue, PassiveIncomeHistoryPoint } from "../api/types";
import { axisMoney } from "../lib/chartData";
import { formatMonth } from "../lib/format";
import styles from "./IncomeFactBars.module.css";
import { moneyText } from "./valueFormat";

const SHORT_MONTHS = [
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
];

/** Geometry only: bar heights never feed a shown amount. */
function coordinate(value: MoneyValue | null | undefined): number | null {
  if (!value) return null;
  const number = Number(value.amount);
  return Number.isFinite(number) ? number : null;
}

/** Label over the selected bar: one decimal for thousands, so 17 500 reads 17,5 тыс. */
function barLabel(value: number): string {
  if (Math.abs(value) >= 1_000 && Math.abs(value) < 100_000) {
    return `${(value / 1_000).toFixed(1).replace(".", ",").replace(/,0$/, "")} тыс`;
  }
  return axisMoney(value);
}

/** Axis step of 1, 2 or 5 × 10^n, about four steps over the range. */
function niceStep(range: number): number {
  if (range <= 0) return 1;
  const raw = range / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 5, 10].find((candidate) => candidate * power >= raw) ?? 10) * power;
}

/**
 * Closed-month passive income as bars (#1079 stage 4): the selected month in
 * accent, the rest muted, the average as a solid line and the goal as a dashed
 * reference line (P 1.4). Each bar is a button that selects the month below.
 */
export function IncomeFactBars({
  points,
  selectedId,
  average,
  goal,
  onSelect,
}: {
  /** Oldest first, as the API returns them. */
  points: PassiveIncomeHistoryPoint[];
  selectedId: number | null;
  /** Null when no closed month is measured yet: no line is drawn. */
  average: MoneyValue | null;
  goal: MoneyValue | null;
  onSelect: (monthId: number) => void;
}) {
  const values = points.map((point) => coordinate(point.passive_income_actual));
  const averageValue = coordinate(average);
  const goalValue = coordinate(goal);
  const known = [...values, averageValue, goalValue].filter(
    (value): value is number => value !== null,
  );
  const low = Math.min(0, ...known);
  const high = Math.max(0, ...known);
  const step = niceStep(high - low);
  const min = Math.floor(low / step) * step;
  const top = Math.max(Math.ceil(high / step) * step, min + step);
  const span = top - min;
  const percent = (value: number) => `${((value - min) / span) * 100}%`;
  const ticks = Array.from(
    { length: Math.round(span / step) + 1 },
    (_, index) => min + step * index,
  );
  const outsideWindow = points.some((point) => !point.included_in_average_window);

  return (
    <div className={styles.chart}>
      <div className={styles.plot}>
        <div aria-hidden="true" className={styles.grid}>
          {ticks.map((tick) => (
            <span key={tick} style={{ bottom: percent(tick) }}>
              <small>{axisMoney(tick)}</small>
            </span>
          ))}
        </div>
        <section
          aria-label="История фактического пассивного дохода"
          className={styles.bars}
          style={{ gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))` }}
        >
          {points.map((point, index) => {
            const value = values[index];
            const selected = point.reporting_month_id === selectedId;
            const negative = value !== null && value < 0;
            return (
              <button
                aria-label={`${formatMonth(point.year, point.month)}: ${moneyText(point.passive_income_actual)}${point.included_in_average_window ? "" : ", не входит в среднее"}`}
                aria-pressed={selected}
                className={styles.bar}
                data-outside={point.included_in_average_window ? undefined : "true"}
                data-selected={selected}
                data-testid={`income-history-${point.reporting_month_id}`}
                key={point.reporting_month_id}
                onClick={() => onSelect(point.reporting_month_id)}
                type="button"
              >
                {value === null ? null : (
                  <span
                    className={styles.fill}
                    data-negative={negative || undefined}
                    style={{
                      bottom: percent(Math.min(0, value)),
                      height: `${(Math.abs(value) / span) * 100}%`,
                    }}
                  >
                    {selected ? <span className={styles.value}>{barLabel(value)}</span> : null}
                  </span>
                )}
              </button>
            );
          })}
        </section>
        {averageValue !== null ? (
          <span
            aria-hidden="true"
            className={styles.average}
            style={{ bottom: percent(averageValue) }}
          />
        ) : null}
        {goalValue !== null && goalValue > 0 ? (
          <span aria-hidden="true" className={styles.goal} style={{ bottom: percent(goalValue) }}>
            <small>цель {axisMoney(goalValue)}</small>
          </span>
        ) : null}
      </div>
      <div
        aria-hidden="true"
        className={styles.labels}
        style={{ gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))` }}
      >
        {points.map((point, index) => (
          <span
            data-selected={point.reporting_month_id === selectedId}
            key={point.reporting_month_id}
          >
            {SHORT_MONTHS[point.month - 1]}
            {index === 0 || point.month === 1 ? <small>{point.year}</small> : null}
          </span>
        ))}
      </div>
      <ul aria-hidden="true" className={styles.key}>
        <li>
          <i className={styles.keyFact} />
          Факт
        </li>
        {averageValue !== null ? (
          <li>
            <i className={styles.keyAverage} />
            Среднее
          </li>
        ) : null}
        {goalValue !== null && goalValue > 0 ? (
          <li>
            <i className={styles.keyGoal} />
            Цель
          </li>
        ) : null}
        {outsideWindow ? (
          <li>
            <i className={styles.keyOutside} />
            Не входит в среднее
          </li>
        ) : null}
      </ul>
    </div>
  );
}
