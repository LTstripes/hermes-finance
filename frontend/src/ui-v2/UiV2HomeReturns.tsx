import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { shortInstrumentName } from "./instrumentName";
import { getHomeSummary } from "./returns/homeSummary";
import { displayMetric, displayWhole, tone } from "./returns/model";
import { useAccountName } from "./returns/useAccountName";
import { useReturnsInvalidated } from "./returns/useReturnsInvalidated";
import styles from "./UiV2Home.module.css";
import { UiV2Skeleton } from "./UiV2StateBlocks";

/** Shares the Returns reader, eligibility and session cache; never blocks Home. */
export function UiV2HomeReturns({ mainSettled }: { mainSettled: boolean }) {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    if (!mainSettled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const frame = requestAnimationFrame(() => {
      // A task after the frame lets the main widgets paint before this heavy read.
      timer = setTimeout(() => setEnabled(true), 0);
    });
    // Hidden or background windows do not run animation frames; start anyway.
    const fallback = setTimeout(() => setEnabled(true), 250);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      clearTimeout(fallback);
    };
  }, [mainSettled]);
  const query = useQuery({
    queryKey: ["returns", "home-summary"],
    queryFn: ({ signal }) => getHomeSummary(signal),
    staleTime: 5 * 60 * 1000,
    enabled,
  });
  const invalidated = useReturnsInvalidated(["returns", "home-summary"]);
  const data =
    !invalidated && !query.isError && query.fetchStatus !== "paused" ? query.data : undefined;
  const accountName = useAccountName(
    data?.ranked.flatMap((row) => row.accounts.map((a) => a.account_link)) ?? [],
  );
  const result = data?.result;
  const ranked = data?.ranked ?? [];
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
            в плюсе {data.positive} · в минусе {data.negative}
            {data.unknown ? ` · без итога ${data.unknown}` : ""}
            {data.unchanged ? ` · без изменения ${data.unchanged}` : ""}
          </p>
          {ranked.length > 0 ? (
            <ol
              className={styles.returnsLeaders}
              aria-label="Три лучших и три худших результата бумаг"
            >
              {ranked.map((row) => {
                const value = BigInt(row.pnl.value ?? "0");
                const names = row.accounts.map((a) => accountName(a.account_link, a.label));
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
              {data.mixed_periods
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
