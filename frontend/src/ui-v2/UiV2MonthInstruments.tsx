import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { getSourceInstrumentReturns } from "../api/sourceReturns";
import { Button } from "../components/ui";
import { MonthInstrumentPayouts } from "./MonthInstrumentPayouts";
import { SourceInstrumentDetail, money, observed, rate, Reasons } from "./SourceInstrumentDetail";
import styles from "./UiV2BondSlice.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

/** One Month reader and the existing instrument detail; all economics remain server-owned. */
export function UiV2MonthInstruments({
  monthId,
  year,
  month,
  account,
  sourceVersion,
}: {
  monthId: number;
  year: number;
  month: number;
  account: string;
  sourceVersion: string;
}) {
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const opening = new Date(Date.UTC(year, month - 1, 0)).toISOString().slice(0, 10);
  const closing = new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
  const queryKey = useMemo(
    () => [
      "source-returns",
      "month-instruments",
      monthId,
      account,
      opening,
      closing,
      sourceVersion,
    ],
    [monthId, account, opening, closing, sourceVersion],
  );
  const read = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const value = await getSourceInstrumentReturns(account, signal, {
        opening_date: opening,
        closing_date: closing,
      });
      if (
        value.source_account !== account ||
        value.financial_authority !== "none" ||
        value.authority !== "provisional" ||
        !Array.isArray(value.instruments) ||
        value.instruments.some(
          (row) =>
            row.analysis.contract_version !== "instrument_return_v2" ||
            row.analysis.opening_date !== opening ||
            row.analysis.closing_date !== closing ||
            row.analysis.opening.date !== opening ||
            row.analysis.closing.date !== closing,
        )
      )
        throw new Error("Счёт или период instrument_return_v2 не совпал с выбранным месяцем.");
      return value;
    },
    refetchOnWindowFocus: true,
  });
  useEffect(
    () =>
      client.getQueryCache().subscribe((event) => {
        if (
          event.type !== "updated" ||
          !["instruments", "accounts", "broker-identity-mappings"].includes(
            String(event.query.queryKey[0]),
          )
        )
          return;
        if (
          event.action.type === "invalidate" ||
          (event.action.type === "success" &&
            (event.action.manual || event.query.state.dataUpdateCount > 1))
        )
          void client.invalidateQueries({ queryKey });
      }),
    [client, queryKey],
  );
  const values = params.getAll("instrument_isin");
  const data = read.data;
  const explicit = values.length > 0;
  const instrument =
    values.length > 1
      ? undefined
      : explicit
        ? data?.instruments.find((row) => row.isin === values[0])
        : data?.instruments[0];
  const events =
    instrument?.analysis.events.filter(
      (event) =>
        event.event_date !== null && event.event_date > opening && event.event_date <= closing,
    ) ?? [];

  return (
    <UiV2Panel
      eyebrow="Из сохранённых источников · только чтение"
      title="Инструменты и выплаты месяца"
      id="month-instruments"
      testIdPrefix="month"
      wide
    >
      <p>
        Выбранный счёт: {account} · нативный: {data?.native_source_account ?? "не подтверждён"}.
        Интервал результата: ({opening}, {closing}]. Дата снимка месяца не подменяет эти границы.
      </p>
      <Button type="button" disabled={read.isFetching} onClick={() => void read.refetch()}>
        Обновить чтение инструментов
      </Button>
      {read.isFetching || read.isPending ? (
        <UiV2Loading label="Читаем инструменты выбранного месяца…" />
      ) : read.isError ? (
        <UiV2Notice title="Инструменты месяца не подтверждены">
          {formatApiError(read.error)}
        </UiV2Notice>
      ) : !data?.native_source_account ? (
        <UiV2Notice title="Нативный счёт источника не подтверждён">
          Другой счёт автоматически не выбран.
        </UiV2Notice>
      ) : (
        <>
          {!data.instruments.length ? (
            <p>В этом счёте нет доступных инструментов. Это не означает нулевой результат.</p>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <caption>Инструменты выбранного счёта и месяца</caption>
                <thead>
                  <tr>
                    <th>Инструмент / ISIN</th>
                    <th>Количество на {closing}</th>
                    <th>Полный P&amp;L</th>
                    <th>Modified Dietz · приблизительно за период, не годовых</th>
                  </tr>
                </thead>
                <tbody>
                  {data.instruments.map((row) => (
                    <tr key={row.isin}>
                      <th>
                        <button
                          type="button"
                          aria-pressed={instrument?.isin === row.isin}
                          onClick={() =>
                            setParams((previous) => {
                              const next = new URLSearchParams(previous);
                              next.set("instrument_isin", row.isin);
                              next.delete("payout_as_of");
                              return next;
                            })
                          }
                        >
                          {row.source_name ?? row.isin}
                        </button>
                        <br />
                        {row.isin} ·{" "}
                        {row.instrument_type === "bond"
                          ? "Облигация"
                          : row.instrument_type === "stock"
                            ? "Акция"
                            : "Тип не подтверждён"}
                      </th>
                      <td>{observed(row.analysis.closing.quantity)}</td>
                      <td>
                        {row.analysis.pnl.value === null
                          ? "Недоступен"
                          : money(row.analysis.pnl.value)}
                      </td>
                      <td>{rate(row.analysis.modified_dietz.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {explicit && !instrument ? (
            <UiV2Notice title="Выбранный инструмент недоступен">
              ISIN {values.join(" / ") || "(пустой)"} не подтверждён в этом счёте и периоде. Выбери
              инструмент явно; другая бумага не подставляется.
            </UiV2Notice>
          ) : instrument ? (
            <section aria-label={`Инструмент ${instrument.isin}`} key={instrument.isin}>
              <h3>
                {instrument.source_name ?? instrument.isin} · {instrument.isin}
              </h3>
              <p>
                {data.native_source_account} × {instrument.isin} · {opening} — {closing}. Источник
                не является принятой финансовой позицией.
              </p>
              <p>
                Распознано за выбранный период: сделок{" "}
                {events.filter((event) => event.kind === "BUY" || event.kind === "SELL").length},
                выплат{" "}
                {
                  events.filter((event) =>
                    ["COUPON", "DIVIDEND", "REDEMPTION"].includes(event.kind),
                  ).length
                }
                . Это доступные события источника; полнота и исключения показаны ниже.
              </p>
              <SourceInstrumentDetail
                analysis={instrument.analysis}
                instrumentType={instrument.instrument_type}
                payoutPreviewHere
              />
              <MonthInstrumentPayouts
                key={`${data.native_source_account}:${instrument.isin}:${JSON.stringify(instrument.analysis)}`}
                account={account}
                nativeAccount={data.native_source_account}
                isin={instrument.isin}
                closingDate={closing}
                sourceReferences={instrument.analysis.source_references}
              />
            </section>
          ) : null}
          {!!data.unresolved_events.length && (
            <details>
              <summary>Нераспределённые события счёта ({data.unresolved_events.length})</summary>
              {data.unresolved_events.map((event) => (
                <p key={event.event_key}>
                  {event.event_date ?? "Дата неизвестна"} · {event.kind} · {event.event_key}
                </p>
              ))}
            </details>
          )}
          {!!data.gaps.length && (
            <details>
              <summary>Пробелы источников ({data.gaps.length})</summary>
              <Reasons codes={data.gaps.map((gap) => gap.code)} />
            </details>
          )}
        </>
      )}
    </UiV2Panel>
  );
}
