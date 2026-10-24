import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { getSourceInstrumentReturns, type SourceInstrumentReturns } from "../api/sourceReturns";
import {
  SourceInstrumentDetail,
  money,
  observed,
  statusLabel,
  Reasons,
  References,
} from "./SourceInstrumentDetail";
import styles from "./UiV2BondSlice.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

/** Presentation of server v2 facts only: no return arithmetic, writers or evidence promotion. */
export function UiV2BondSlice({
  account,
  sources,
}: {
  account: string;
  sources: SourceInstrumentReturns;
}) {
  const [params, setParams] = useSearchParams();
  const ownContext = !params.get("source_account") || params.get("source_account") === account;
  const period = ownContext ? (params.get("bond_period") ?? "history") : "history";
  const chosenIsin = ownContext ? params.get("bond_isin") : null;
  function select(key: "bond_period" | "bond_isin", value: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("source_account", account);
      if (value === "history") next.delete(key);
      else next.set(key, value);
      return next;
    });
  }
  const sourceBonds = sources.instruments.filter((row) => row.instrument_type === "bond");
  const months = [...new Set(sourceBonds.flatMap((row) => row.months.map((value) => value.month)))]
    .sort()
    .reverse();
  const selectedMonth = sourceBonds
    .flatMap((row) => row.months)
    .find((row) => row.month === period)?.analysis;
  const selected = useQuery({
    queryKey: ["source-returns", "bond-period", account, period],
    queryFn: ({ signal }) =>
      getSourceInstrumentReturns(account, signal, {
        opening_date: selectedMonth?.opening_date ?? "",
        closing_date: selectedMonth?.closing_date ?? "",
      }),
    enabled: period !== "history" && !!selectedMonth,
  });
  const data = period === "history" ? sources : selected.data;
  const bonds = data?.instruments.filter((row) => row.instrument_type === "bond") ?? [];
  const instrument = chosenIsin === null ? bonds[0] : bonds.find((row) => row.isin === chosenIsin);
  const scopeMismatch =
    data &&
    (data.source_account !== account ||
      data.native_source_account !== sources.native_source_account);
  return (
    <UiV2Panel
      eyebrow="Из сохранённых источников"
      id="bond-slice"
      testIdPrefix="returns"
      title="Облигации: позиции, сделки и купоны"
      wide
    >
      <p>
        Счёт источника:{" "}
        <strong>{sources.native_source_account ?? "нативный счёт не установлен"}</strong> · выбран:{" "}
        {account}.
      </p>
      <p className={styles.note}>
        Только чтение. Данные выписок не являются принятой финансовой позицией и не дают готовности
        к Close.
      </p>
      {sourceBonds.length === 0 ? (
        <p>В сохранённых источниках этого счёта нет облигаций с подтверждённым типом.</p>
      ) : (
        <>
          <label>
            Период облигаций{" "}
            <select
              aria-label="Период облигаций"
              value={period}
              onChange={(event) => select("bond_period", event.target.value)}
            >
              <option value="history">Доступная история источников</option>
              {months.map((value) => (
                <option key={value} value={value}>
                  {value.slice(0, 7)}
                </option>
              ))}
            </select>
          </label>
          {scopeMismatch ? (
            <UiV2Notice title="Счёт ответа не совпадает с выбранным">
              Обновите чтение источников.
            </UiV2Notice>
          ) : period !== "history" && !selectedMonth ? (
            <UiV2Notice title="Период больше не доступен в источниках">
              Выберите другой период.
            </UiV2Notice>
          ) : period !== "history" && selected.isPending ? (
            <UiV2Loading label="Читаем период облигаций…" />
          ) : selected.isError && period !== "history" ? (
            <UiV2Notice title="Не удалось прочитать облигации">
              {formatApiError(selected.error)}
              <button type="button" onClick={() => void selected.refetch()}>
                Повторить чтение облигаций
              </button>
            </UiV2Notice>
          ) : (
            <>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption>Облигации выбранного счёта и периода</caption>
                  <thead>
                    <tr>
                      <th>Облигация</th>
                      <th>Количество на конец</th>
                      <th>Стоимость по выписке</th>
                      <th>Дата оценки</th>
                      <th>Известные купоны</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bonds.map((row) => (
                      <tr key={row.isin}>
                        <th>
                          <button
                            type="button"
                            aria-pressed={instrument?.isin === row.isin}
                            onClick={() => select("bond_isin", row.isin)}
                          >
                            {row.source_name ?? row.isin}
                          </button>
                          <br />
                          <small>{row.isin}</small>
                        </th>
                        <td>{observed(row.analysis.closing.quantity)}</td>
                        <td>{money(row.analysis.closing.reported_value_kopecks)}</td>
                        <td>
                          {row.analysis.closing.reported_value_kopecks === null
                            ? `Нет оценки на ${row.analysis.closing.date}`
                            : row.analysis.closing.date}
                        </td>
                        <td>
                          {money(row.analysis.components.coupons.value)} ·{" "}
                          {statusLabel(row.analysis.components.coupons.status)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={styles.note}>
                Стоимость показана как reported value из выписки. Подтверждённый состав clean/dirty
                указан в деталях.
              </p>
              {chosenIsin !== null && !instrument ? (
                <UiV2Notice title="Выбранная облигация недоступна">
                  ISIN <code>{chosenIsin || "(пустой ISIN)"}</code> не найден в выбранном счёте и
                  периоде. Выберите облигацию в таблице или проверьте ISIN в ссылке.
                </UiV2Notice>
              ) : instrument ? (
                <section aria-label={`Детали облигации ${instrument.isin}`}>
                  <h3>
                    {instrument.source_name ?? instrument.isin} · {instrument.isin}
                  </h3>
                  <SourceInstrumentDetail analysis={instrument.analysis} />
                </section>
              ) : null}
              {!!data?.unresolved_events.length && (
                <details>
                  <summary>
                    Нераспределённые события счёта в истории источников:{" "}
                    {data.unresolved_events.length}
                  </summary>
                  <p>Эти события не отнесены автоматически к выбранной облигации.</p>
                  <ul>
                    {data.unresolved_events.map((event) => (
                      <li key={event.event_key}>
                        {observed(event.event_date)} · {event.kind}
                        <Reasons codes={event.reason_codes} />
                        <References values={event.source_references} />
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </>
      )}
    </UiV2Panel>
  );
}
