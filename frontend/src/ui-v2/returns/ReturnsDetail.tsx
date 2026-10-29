import { useQuery } from "@tanstack/react-query";
import { SourceInstrumentDetail } from "../SourceInstrumentDetail";
import { getDetail, type Period } from "./model";
import styles from "./Returns.module.css";
import { MissingName } from "./ReturnsAvailable";

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
      <SourceInstrumentDetail analysis={d.analysis} instrumentType={d.kind} personalResult />
    </div>
  );
}
