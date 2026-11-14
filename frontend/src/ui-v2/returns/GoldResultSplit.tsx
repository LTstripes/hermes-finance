import type { GoldDecomposition } from "./goldHistory";
import { displayMetric, displayWhole } from "./model";
import { Explanation, Info } from "./ReturnsInfo";

export function GoldResultSplit({ value }: { value: GoldDecomposition }) {
  return (
    <>
      {(
        [
          [
            "Зафиксировано",
            value.realized_result,
            "Выручка продаж минус FIFO-стоимость проданных граммов. Комиссии и налоги исключены.",
          ],
          [
            "В цене",
            value.unrealized_result,
            "Текущая оценка остатка минус его FIFO-стоимость. Для закрытой позиции — ноль.",
          ],
        ] as const
      ).map(([label, metric, explanation]) => {
        return (
          <div key={String(label)}>
            <dt>
              {String(label)}{" "}
              <Info label={String(label)}>
                <p>{String(explanation)}</p>
                <Explanation codes={metric.reason_codes} />
              </Info>
            </dt>
            <dd title={displayMetric(metric, true)}>{displayWhole(metric, true)}</dd>
          </div>
        );
      })}
    </>
  );
}
