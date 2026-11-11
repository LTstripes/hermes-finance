import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { shortInstrumentName } from "./instrumentName";
import { brokerageResult, instrumentSummary } from "./returns/dashboard";
import {
  compareDecimal,
  displayMetric,
  displayWhole,
  isPartialResult,
  tone,
} from "./returns/model";
import { getOverall } from "./returns/overall";
import { useAccountName } from "./returns/useAccountName";
import { useReturnsInvalidated } from "./returns/useReturnsInvalidated";
import styles from "./UiV2Home.module.css";
import { UiV2Skeleton } from "./UiV2StateBlocks";

/** Shares the Returns reader, eligibility and session cache; never blocks Home. */
export function UiV2HomeReturns({ mainSettled }: { mainSettled: boolean }) {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    if (!mainSettled) return;
    let timer: ReturnType<typeof setTimeout>;
    const frame = requestAnimationFrame(() => {
      // A task after the frame lets the main widgets paint before this heavy read.
      timer = setTimeout(() => setEnabled(true), 0);
    });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [mainSettled]);
  const query = useQuery({
    queryKey: ["returns", "overall", "summaries"],
    queryFn: ({ signal }) => getOverall(signal, true),
    staleTime: 5 * 60 * 1000,
    enabled,
  });
  const invalidated = useReturnsInvalidated(["returns", "overall", "summaries"]);
  const data =
    !invalidated && !query.isError && query.fetchStatus !== "paused" ? query.data : undefined;
  const accountName = useAccountName(data?.source_accounts.map((a) => a.account_link) ?? []);
  const result = data ? brokerageResult(data, "all") : null;
  const rows = data ? data.instruments.map((row) => instrumentSummary(data, row, "all")) : [];
  const known = rows.filter((row) => row.pnl.value !== null && !isPartialResult(row.pnl));
  const positive = known.filter((row) => compareDecimal(row.pnl.value ?? "0", "0") > 0);
  const negative = known.filter((row) => compareDecimal(row.pnl.value ?? "0", "0") < 0);
  const periods = new Set(
    rows
      .filter((row) => row.pnl.value !== null)
      .flatMap((row) =>
        row.accounts
          .filter((a) => a.resultAvailable && a.period)
          .map((a) => `${a.period?.start}/${a.period?.end}`),
      ),
  );
  const ranked =
    periods.size === 1
      ? [
          ...positive
            .sort((a, b) => compareDecimal(b.pnl.value ?? "0", a.pnl.value ?? "0"))
            .slice(0, 3),
          ...negative
            .sort((a, b) => compareDecimal(a.pnl.value ?? "0", b.pnl.value ?? "0"))
            .slice(0, 3),
        ]
      : [];
  const maximum = ranked.reduce((max, row) => {
    const value = BigInt(row.pnl.value ?? "0");
    const absolute = value < 0n ? -value : value;
    return absolute > max ? absolute : max;
  }, 1n);

  return (
    <section className={`${styles.block} ${styles.s5}`} aria-labelledby="home-returns-title">
      <div className={styles.blockHead}>
        <div>
          <p className={styles.kicker}>За всю историю</p>
          <h2 id="home-returns-title">Доходность бумаг</h2>
        </div>
        <Link className={styles.link} to="/v2/returns">
          Все бумаги →
        </Link>
      </div>
      {query.isError || query.fetchStatus === "paused" ? (
        <p className={styles.returnsRetry}>
          Доходность временно недоступна.{" "}
          <button type="button" onClick={() => void query.refetch()}>
            Повторить
          </button>
        </p>
      ) : !data ? (
        <UiV2Skeleton label="Загружаем доходность бумаг" />
      ) : (
        <>
          <strong
            className={styles.midValue}
            data-testid="v2-home-returns-total"
            data-tone={result ? tone(result.amount) : undefined}
            title={result ? displayMetric(result.amount, true) : undefined}
          >
            {result ? displayWhole(result.amount, true) : "—"}
          </strong>
          <p className={styles.note}>
            в плюсе {positive.length} · в минусе {negative.length}
            {known.length < rows.length ? ` · без итога ${rows.length - known.length}` : ""}
            {known.length > positive.length + negative.length
              ? ` · без изменения ${known.length - positive.length - negative.length}`
              : ""}
          </p>
          {ranked.length > 0 ? (
            <ol
              className={styles.returnsLeaders}
              aria-label="Три лучших и три худших результата бумаг"
            >
              {ranked.map((row) => {
                const value = BigInt(row.pnl.value ?? "0");
                const names = row.accounts.map((a) =>
                  accountName(
                    a.account_link ??
                      data.source_accounts.find((source) => source.scope === a.scope)?.account_link,
                    a.label,
                  ),
                );
                return (
                  <li key={row.isin}>
                    <Link
                      to={`/v2/returns/instrument/${encodeURIComponent(row.isin)}?back=%2Fv2`}
                      state={{ instrumentName: row.name }}
                      title={row.name}
                    >
                      {shortInstrumentName({ name: row.name, isin: row.isin, ticker: null })}
                      <small>{names.join(" · ")}</small>
                    </Link>
                    <span
                      className={styles.returnsTrack}
                      data-tone={tone(row.pnl)}
                      aria-hidden="true"
                    >
                      <span
                        style={{
                          width: `${Number(((value < 0n ? -value : value) * 5000n) / maximum) / 100}%`,
                        }}
                      />
                    </span>
                    <strong data-tone={tone(row.pnl)} title={displayMetric(row.pnl, true)}>
                      {displayWhole(row.pnl, true)}
                    </strong>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className={styles.note}>
              {periods.size > 1
                ? "Результаты бумаг относятся к разным периодам — сравнение доступно в подробностях."
                : "Пока нет результатов бумаг для сравнения."}
            </p>
          )}
          {result?.partial && <p className={styles.note}>Итог доступен только по части данных.</p>}
          {query.isFetching && (
            <p className={styles.note} role="status">
              Обновляем…
            </p>
          )}
        </>
      )}
    </section>
  );
}
