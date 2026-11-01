import { breakdownMatches, breakdownRows, type ReturnBreakdown } from "./breakdown";
import { displayMetric, type Metric, unavailable } from "./model";
import styles from "./Returns.module.css";

export function ReturnsBreakdown({ value, total }: { value: ReturnBreakdown; total: Metric }) {
  const complete = breakdownMatches(value, total);
  return (
    <section className={styles.panel} aria-label="Разложение результата">
      <h2>Из чего сложился результат</h2>
      {!complete && (
        <p className={styles.basisNote}>Данных для полного разложения пока недостаточно.</p>
      )}
      <dl className={styles.breakdown}>
        {breakdownRows(value).map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{displayMetric({ ...unavailable, value: row.value }, true)}</dd>
          </div>
        ))}
        <div className={styles.breakdownTotal}>
          <dt>Итог</dt>
          <dd>{displayMetric(total, true)}</dd>
        </div>
      </dl>
    </section>
  );
}
