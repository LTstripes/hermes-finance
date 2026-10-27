import { type AvailableMonths, periodLabel } from "./model";
import { Explanation, Info, Value } from "./ReturnsInfo";
import styles from "./Returns.module.css";

export function MissingName({ name, isin }: { name: string; isin: string }) {
  return name === isin ? (
    <Info label={`Название ${isin}`}>
      <p>Название отсутствует в выписке и локальном каталоге. Показан ISIN.</p>
    </Info>
  ) : null;
}

export function ReturnsAvailable({ value }: { value: AvailableMonths }) {
  return (
    <>
      <h2>
        За доступные месяцы · {value.covered_months} из {value.total_months}
      </h2>
      <div className={styles.mainValue}>
        <Value metric={value.pnl} label="За доступные месяцы" signed />
      </div>
      <small>{periodLabel(value.period)}</small>
      <Info label="Покрытие доступных месяцев">
        <p>Частичный итог одного счёта в рублях. Выплаты уже включены. Процент не рассчитан.</p>
        {value.included.map((p) => (
          <p key={p.start}>Учтён: {periodLabel(p)}</p>
        ))}
        {value.missing.map((m) => (
          <div key={m.period.start}>
            <p>Не учтён: {periodLabel(m.period)}</p>
            <Explanation codes={m.reason_codes} />
          </div>
        ))}
        <p>Полный результат за этот интервал недоступен.</p>
      </Info>
    </>
  );
}
