import { type AcceptedIncome, displayMetric, unavailable } from "./model";
import styles from "./Returns.module.css";

const money = (value: string | null) => displayMetric({ ...unavailable, value });

export function ReturnsAcceptedIncome({ value }: { value: AcceptedIncome }) {
  return (
    <section className={styles.panel} aria-label="Разложение выплат">
      <h2>Выплаты (купоны + дивиденды)</h2>
      <p className={styles.mainValue}>{money(value.net_kopecks)}</p>
      <p className={styles.basisNote}>
        Известные принятые выплаты: покрытие периода частичное. Суммы точные, после удержаний; налог
        повторно не вычитается. К результату выплаты повторно не прибавляются.
      </p>
      <table>
        <thead>
          <tr>
            <th scope="col">Инструмент / счёт</th>
            <th scope="col">Купоны</th>
            <th scope="col">Дивиденды</th>
            <th scope="col">До удержаний</th>
            <th scope="col">Удержанный налог</th>
          </tr>
        </thead>
        <tbody>
          {value.instruments.map((row) => (
            <tr key={row.id}>
              <th scope="row">
                {row.name} {row.isin} · {row.account}
              </th>
              <td>{money(row.coupons_kopecks)}</td>
              <td>{money(row.dividends_kopecks)}</td>
              <td>{money(row.gross_kopecks)}</td>
              <td>{money(row.tax_kopecks)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
