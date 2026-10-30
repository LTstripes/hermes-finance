import { Link } from "react-router";
import { periodLabel } from "./model";
import { accountHref, type CouponIncome } from "./overall";
import styles from "./Returns.module.css";
import { Explanation, Value } from "./ReturnsInfo";

const statusLabels = {
  current: "проверка актуальна",
  stale: "проверка устарела",
  absent: "проверки нет",
  conflict: "конфликт данных",
};
export function ReturnsCouponIncome({ value }: { value: CouponIncome }) {
  return (
    <section className={styles.panel} aria-label="Полученные купоны">
      <h2>Полученные купоны за доступную историю</h2>
      <section className={styles.mainValue} aria-label="Известная сумма купонов">
        <Value metric={value.known_total} label="Полученные купоны за доступную историю" />
      </section>
      <p>
        Частичное покрытие: включено счетов {value.included_accounts} из {value.selected_accounts}.
        Только известная сохранённая история по выпискам; полнота за всё время, налоговый учёт и
        будущие выплаты не подтверждены.
      </p>
      <p>
        Купоны уже входят в соответствующий результат счёта. Эта справочная сумма повторно не
        прибавляется к известному результату.
      </p>
      <details className={styles.diagnostics}>
        <summary>Счета, периоды и покрытие купонов</summary>
        <Explanation codes={value.reason_codes} />
        <ul>
          {value.reason_codes.map((code) => (
            <li key={code}>
              <code>{code}</code>
            </li>
          ))}
        </ul>
        {!value.accounts.length ? (
          <p>Нет подтверждённой истории купонов по счетам.</p>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.instruments}>
              <thead>
                <tr>
                  <th>Счёт и период</th>
                  <th>Полученные купоны</th>
                  <th>Покрытие</th>
                </tr>
              </thead>
              <tbody>
                {value.accounts.map((account) => (
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
                        label={`${account.label}: полученные купоны`}
                      />
                    </td>
                    <td>
                      {statusLabels[account.proof_status]} ·{" "}
                      {account.included ? "включён" : "не включён"}
                      <Explanation codes={account.reason_codes} />
                      {account.exclusion_reason && (
                        <p>
                          Причина исключения: <code>{account.exclusion_reason}</code>
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
