import { useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { getSourceInstrumentReturns, type SourceInstrumentReturns } from "../api/sourceReturns";
import { Button, Select, Table, Td, Th } from "../components/ui";
import { formatDate, formatMonthKey } from "../lib/format";
import sheet from "./ReportSheet.module.css";
import {
  money,
  observed,
  Reasons,
  References,
  SourceInstrumentDetail,
  statusLabel,
} from "./SourceInstrumentDetail";
import styles from "./UiV2BondSlice.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

const eventLabels = {
  BUY: "Покупка",
  SELL: "Продажа",
  COUPON: "Купон",
  DIVIDEND: "Дивиденд",
  FEE: "Комиссия",
  TAX: "Налог",
  REDEMPTION: "Погашение",
  UNRESOLVED: "Вид операции не установлен",
};

/** Presentation of server v2 facts only: no return arithmetic, writers or evidence promotion. */
export function UiV2BondSlice({
  account,
  sources,
}: {
  account: string;
  sources: SourceInstrumentReturns;
}) {
  const periodId = useId();
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
        Счёт источника: <strong>{sources.native_source_account ?? "не указан в выписке"}</strong>
      </p>
      <p className={styles.note}>
        Позиции из выписок показаны для сверки. Они не влияют на закрытие месяца.
      </p>
      {sourceBonds.length === 0 ? (
        <p>В сохранённых источниках этого счёта нет облигаций с подтверждённым типом.</p>
      ) : (
        <>
          <label className={`${sheet.select} ${styles.period}`} htmlFor={periodId}>
            Период облигаций{" "}
            <Select
              id={periodId}
              aria-label="Период облигаций"
              value={period}
              onChange={(event) => select("bond_period", event.target.value)}
            >
              <option value="history">Доступная история источников</option>
              {months.map((value) => (
                <option key={value} value={value}>
                  {formatMonthKey(value.slice(0, 7))}
                </option>
              ))}
            </Select>
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
              <Button variant="ghost" onClick={() => void selected.refetch()}>
                Повторить чтение облигаций
              </Button>
            </UiV2Notice>
          ) : (
            <>
              <Table className={styles.bonds}>
                <caption>Облигации выбранного счёта и периода</caption>
                <thead>
                  <tr>
                    <Th scope="col">Облигация</Th>
                    <Th scope="col" numeric>
                      Количество на конец
                    </Th>
                    <Th scope="col" numeric>
                      Стоимость по выписке
                    </Th>
                    <Th scope="col">Дата оценки</Th>
                    <Th scope="col" numeric>
                      Известные купоны
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {bonds.map((row) => (
                    <tr key={row.isin}>
                      <Th scope="row">
                        <Button
                          variant="ghost"
                          size="sm"
                          title={row.isin}
                          aria-pressed={instrument?.isin === row.isin}
                          onClick={() => select("bond_isin", row.isin)}
                        >
                          {row.short_name === undefined
                            ? (row.source_name ?? "Без названия")
                            : (row.short_name ?? "Без названия")}
                        </Button>
                      </Th>
                      <Td numeric>{observed(row.analysis.closing.quantity)}</Td>
                      <Td numeric>{money(row.analysis.closing.reported_value_kopecks)}</Td>
                      <Td>
                        {row.analysis.closing.reported_value_kopecks === null
                          ? `Нет оценки на ${formatDate(row.analysis.closing.date)}`
                          : formatDate(row.analysis.closing.date)}
                      </Td>
                      <Td numeric>
                        {money(row.analysis.components.coupons.value)}
                        <small>{statusLabel(row.analysis.components.coupons.status)}</small>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <p className={styles.note}>
                Стоимость указана по выписке брокера. Состав цены и накопленный купонный доход (НКД)
                показаны в деталях облигации.
              </p>
              {chosenIsin !== null && !instrument ? (
                <UiV2Notice title="Выбранная облигация недоступна">
                  ISIN <code>{chosenIsin || "(пустой ISIN)"}</code> не найден в выбранном счёте и
                  периоде. Выберите облигацию в таблице или проверьте ISIN в ссылке.
                </UiV2Notice>
              ) : instrument ? (
                <section aria-label={`Детали облигации ${instrument.isin}`}>
                  <h3 title={instrument.isin}>
                    {instrument.short_name === undefined
                      ? (instrument.source_name ?? "Без названия")
                      : (instrument.short_name ?? "Без названия")}
                  </h3>
                  <SourceInstrumentDetail analysis={instrument.analysis} />
                </section>
              ) : null}
              {!!data?.unresolved_events.length && (
                <details className={styles.disclosure}>
                  <summary>
                    Нераспределённые события счёта в истории источников:{" "}
                    {data.unresolved_events.length}
                  </summary>
                  <p>Эти события не отнесены автоматически к выбранной облигации.</p>
                  <Table aria-label="Нераспределённые события">
                    <thead>
                      <tr>
                        <Th>Дата</Th>
                        <Th>Операция</Th>
                        <Th>Причина и источники</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.unresolved_events.map((event) => (
                        <tr key={event.event_key}>
                          <Td>{formatDate(event.event_date)}</Td>
                          <Td>{eventLabels[event.kind]}</Td>
                          <Td>
                            <Reasons codes={event.reason_codes} />
                            <References values={event.source_references} />
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </details>
              )}
            </>
          )}
        </>
      )}
    </UiV2Panel>
  );
}
