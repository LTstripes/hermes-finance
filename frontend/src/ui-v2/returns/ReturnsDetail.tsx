import { useQuery } from "@tanstack/react-query";
import { SourceInstrumentDetail } from "../SourceInstrumentDetail";
import { analysisBreakdown } from "./breakdown";
import { type Detail, getDetail, type Period } from "./model";
import styles from "./Returns.module.css";
import { MissingName } from "./ReturnsAvailable";
import { ReturnsBreakdown } from "./ReturnsBreakdown";
import { ReturnsResultMeta } from "./ReturnsResultMeta";

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
