import { useQuery } from "@tanstack/react-query";
import { SourceInstrumentDetail } from "../SourceInstrumentDetail";
import { formatQuantity } from "../../lib/format";
import { analysisBreakdown } from "./breakdown";
import { dateLabel, type Detail, getDetail, type Period } from "./model";
import styles from "./Returns.module.css";
import { MissingName } from "./ReturnsAvailable";
import { ReturnsBreakdown } from "./ReturnsBreakdown";
import { ReturnsResultMeta } from "./ReturnsResultMeta";
import { cleanMetric } from "./cards";
import { displayMetric } from "./model";
import { ReturnsInstrumentResult } from "./ReturnsInstrumentResult";

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
  return <ReturnsDetailBody detail={query.data} />;
}

export function ReturnsDetailBody({ detail: d }: { detail: Detail }) {
  if (d.contract_version === "returns_source_detail_v2") {
    return (
      <div className={styles.detail}>
        <h3>
          {d.name} <MissingName name={d.name} isin={d.isin} />
        </h3>
        <ReturnsResultMeta
          period={d.period}
          valuationDate={d.valuation_date}
          accountLink={d.account_link}
        />
        <section>
          <h4>Позиция на {dateLabel(d.period.end)}</h4>
          <p>
            Количество: {d.opening_quantity === null ? "—" : formatQuantity(d.opening_quantity)} →{" "}
            {d.closing_quantity === null ? "—" : formatQuantity(d.closing_quantity)}
          </p>
        </section>
        <ReturnsInstrumentResult result={d.clean ? d : null} reasonCodes={d.reason_codes} />
        {d.clean && (
          <details>
            <summary>Известные составляющие</summary>
            {(
              [
                ["Покупки", d.clean.buys],
                ["Продажи", d.clean.sells],
                ["Купоны", d.clean.coupons],
                ["Дивиденды", d.clean.dividends],
                ["Погашение", d.clean.redemption],
              ] as const
            )
              .filter(([, part]) => part.value !== null)
              .map(([label, part]) => (
                <p key={label}>
                  {label}
                  {part.status === "partial" ? " · известная часть" : ""}:{" "}
                  {displayMetric(cleanMetric(part))}
                </p>
              ))}
          </details>
        )}
        <SourceInstrumentDetail
          analysis={d.analysis}
          instrumentType={d.kind}
          personalResult
          operationsOnly
        />
      </div>
    );
  }
  // The shared diagnostic detail has labels for its original component set.
  const components = { ...d.analysis.components };
  for (const name of ["payouts", "price_and_trades", "commissions", "paid_nkd"])
    delete (components as Record<string, unknown>)[name];
  return (
    <div className={styles.detail}>
      <h3>
        {d.name} <MissingName name={d.name} isin={d.isin} />
      </h3>
      {d.name !== d.isin && <small>{d.isin}</small>}
      <ReturnsResultMeta
        period={d.period}
        valuationDate={d.valuation_date}
        accountLink={d.account_link}
      />
      <ReturnsBreakdown value={analysisBreakdown([d.analysis], d.pnl)} total={d.pnl} />
      <SourceInstrumentDetail
        analysis={{ ...d.analysis, components }}
        instrumentType={d.kind}
        personalResult
      />
    </div>
  );
}
