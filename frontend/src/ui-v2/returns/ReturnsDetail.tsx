import { useQuery } from "@tanstack/react-query";
import { formatQuantity } from "../../lib/format";
import { dateLabel, getDetail, type Period } from "./model";
import { Explanation, Value } from "./ReturnsInfo";
import { MissingName } from "./ReturnsAvailable";
import styles from "./Returns.module.css";

const kinds: Record<string, string> = {
  BUY: "Покупка",
  SELL: "Продажа",
  COUPON: "Купон",
  DIVIDEND: "Дивиденд",
  FEE: "Комиссия",
  TAX: "Налог",
  REDEMPTION: "Погашение",
  UNRESOLVED: "Требует уточнения",
};
export function ReturnsDetail({
  scope,
  period,
  isin,
  revision,
}: {
  scope: string;
  period: Period;
  isin: string;
  revision: number;
}) {
  const query = useQuery({
    queryKey: ["returns", "detail", scope, period.start, period.end, isin, revision],
    queryFn: ({ signal }) => getDetail(scope, period, isin, signal),
    staleTime: 0,
  });
  if (query.isError)
    return (
      <p role="alert">
        Не удалось загрузить детали.{" "}
        <button type="button" onClick={() => void query.refetch()}>
          Повторить
        </button>
      </p>
    );
  if (query.isFetching || !query.data) return <p role="status">Загружаем детали…</p>;
  const d = query.data;
  return (
    <div className={styles.detail}>
      <h3>
        {d.name} <MissingName name={d.name} isin={d.isin} />
      </h3>
      {d.name !== d.isin && <small>{d.isin}</small>}
      <div className={styles.detailFacts}>
        <p>
          Количество: {formatQuantity(d.opening_quantity)} → {formatQuantity(d.closing_quantity)}
        </p>
        <div>
          Покупки: <Value metric={d.buys} label="Покупки" />
        </div>
        <div>
          Продажи: <Value metric={d.sells} label="Продажи" />
        </div>
      </div>
      {d.conditional && (
        <details>
          <summary>Условная оценка по стоимости в выписке</summary>
          <p>Без подтверждённого НКД на границах; не входит в общий результат и топы.</p>
          <Value metric={d.conditional_pnl} label="Условный результат" signed /> ·{" "}
          <Value metric={d.conditional_rate} label="Условный процент" />
        </details>
      )}
      <details>
        <summary>Что учтено в расчёте</summary>
        <Explanation codes={d.reason_codes} />
        <p>
          Выплаты и повторные наблюдения учитывает сервер. Продажа и реинвестирование не создают
          дополнительный доход.
        </p>
      </details>
      <h3>Сделки и выплаты</h3>
      {d.events.length === 0 ? (
        <p>Операций за выбранный период нет.</p>
      ) : (
        <div className={styles.events}>
          {d.events.map((e) => (
            <div className={styles.event} key={e.ordinal}>
              <strong>{kinds[e.kind] ?? "Операция"}</strong>
              <span>{e.date ? dateLabel(e.date) : "Дата не установлена"}</span>
              <span>{e.quantity === null ? "—" : e.quantity.replace(".", ",")} шт.</span>
              <Value metric={e.amount} label={`${kinds[e.kind] ?? "Операция"}: сумма`} />
              <small>
                Деньги: {e.cash_date ? dateLabel(e.cash_date) : "—"} · Бумаги:{" "}
                {e.quantity_date ? dateLabel(e.quantity_date) : "—"}
                {!e.counted && " · Не учтено в результате"}
              </small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
