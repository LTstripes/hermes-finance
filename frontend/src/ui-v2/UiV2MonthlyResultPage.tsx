import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import type { AccountResultPoint, InstrumentClassResultPoint, ReportingMonth } from "../api/types";
import { Table, Td, Th } from "../components/ui";
import { formatMoney, formatMoneyDelta, formatMonth } from "../lib/format";
import { moneyAmount, sumMoneyAmounts } from "../lib/money";
import { queryKeys } from "../queryClient";
import { latestClosedMonth, sortReportingMonths } from "./monthSelection";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2ReportContext } from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import styles from "./UiV2Page.module.css";
import resultStyles from "./UiV2MonthlyResult.module.css";

const ACCOUNT_TYPES: Record<string, string> = {
  brokerage: "Брокерский",
  iis: "ИИС",
  deposit: "Депозит",
  savings: "Накопительный",
  cash: "Наличные",
  other: "Прочее",
};

const INSTRUMENT_TYPES: Record<string, string> = {
  stock: "Акции",
  bond: "Облигации",
  fund: "Фонды",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
};

type ResultView = "accounts" | "classes";

function selectedMonth(values: string[], months: ReportingMonth[]): ReportingMonth | null {
  if (values.length === 0) return latestClosedMonth(months);
  if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) return null;
  const id = Number(values[0]);
  if (!Number.isSafeInteger(id)) return null;
  return months.find((month) => month.id === id && month.status === "closed") ?? null;
}

function resultTotal(cash: string, unrealized: string | null): string {
  return formatMoneyDelta(unrealized === null ? null : sumMoneyAmounts([cash, unrealized]));
}

function AccountRows({ rows }: { rows: AccountResultPoint[] }) {
  return (
    <Table className={resultStyles.table}>
      <caption>Результат по счетам</caption>
      <thead>
        <tr>
          <Th>Счёт</Th>
          <Th>Тип</Th>
          <Th numeric>Денежный доход</Th>
          <Th numeric>Нереализованный</Th>
          <Th numeric>Итог строки</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const cash = moneyAmount(row.cash_income);
          const unrealized = moneyAmount(row.unrealized_result);
          return (
            <tr key={row.account_id}>
              <Td data-label="Счёт">
                {row.account_name} <small>#{row.account_id}</small>
              </Td>
              <Td data-label="Тип">{ACCOUNT_TYPES[row.account_type] ?? row.account_type}</Td>
              <Td data-label="Денежный доход" numeric>
                {formatMoneyDelta(cash)}
              </Td>
              <Td data-label="Нереализованный" numeric>
                {formatMoneyDelta(unrealized)}
              </Td>
              <Td data-label="Итог строки" numeric>
                {resultTotal(cash, unrealized)}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function ClassRows({ rows }: { rows: InstrumentClassResultPoint[] }) {
  return (
    <Table className={resultStyles.table}>
      <caption>Результат по классам инструментов</caption>
      <thead>
        <tr>
          <Th>Класс инструмента</Th>
          <Th numeric>Оценка</Th>
          <Th numeric>Себестоимость</Th>
          <Th numeric>Денежный результат</Th>
          <Th numeric>Нереализованный</Th>
          <Th numeric>Итог строки</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const cash = moneyAmount(row.realized_result);
          const unrealized =
            row.unrealized_result === null ? null : moneyAmount(row.unrealized_result);
          return (
            <tr key={row.instrument_type}>
              <Td data-label="Класс инструмента">
                {INSTRUMENT_TYPES[row.instrument_type] ?? row.instrument_type}
              </Td>
              <Td data-label="Оценка" numeric>
                {formatMoney(row.market_value === null ? null : moneyAmount(row.market_value))}
              </Td>
              <Td data-label="Себестоимость" numeric>
                {formatMoney(row.cost_basis === null ? null : moneyAmount(row.cost_basis))}
              </Td>
              <Td data-label="Денежный результат" numeric>
                {formatMoneyDelta(cash)}
              </Td>
              <Td data-label="Нереализованный" numeric>
                {formatMoneyDelta(unrealized)}
              </Td>
              <Td data-label="Итог строки" numeric>
                {resultTotal(cash, unrealized)}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

export default function UiV2MonthlyResultPage() {
  const [params, setParams] = useSearchParams();
  const monthValues = params.getAll("month");
  const viewValues = params.getAll("view");
  const view: ResultView =
    viewValues.length === 1 && viewValues[0] === "classes" ? "classes" : "accounts";
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const monthsReady = isQueryReady(monthsQuery);
  const month = monthsReady ? selectedMonth(monthValues, monthsQuery.data ?? []) : null;
  const dashboardQuery = useQuery({
    enabled: month !== null,
    queryKey: queryKeys.dashboard(month?.id ?? null),
    queryFn: ({ signal }) => {
      if (!month) throw new Error("No closed month selected");
      return getDashboard(month.id, signal);
    },
    refetchOnWindowFocus: true,
  });
  const dashboardReady =
    isQueryReady(dashboardQuery) &&
    dashboardQuery.data?.month?.id === month?.id &&
    dashboardQuery.data?.month?.status === "closed" &&
    dashboardQuery.data?.month?.year === month?.year &&
    dashboardQuery.data?.month?.month === month?.month &&
    dashboardQuery.data?.month?.snapshot_date === month?.snapshot_date;
  const dashboard = dashboardReady ? dashboardQuery.data : null;
  const latest = monthsReady ? latestClosedMonth(monthsQuery.data ?? []) : null;
  const historical = month !== null && latest !== null && month.id !== latest.id;

  function selectView(next: ResultView) {
    const nextParams = new URLSearchParams(params);
    nextParams.set("view", next);
    setParams(nextParams);
  }

  function selectMonth(nextId: string) {
    const nextParams = new URLSearchParams(params);
    nextParams.set("month", nextId);
    setParams(nextParams);
  }

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось проверить отчёты" retry={() => void monthsQuery.refetch()}>
        Результат скрыт, пока список закрытых отчётов недоступен.
      </UiV2Notice>
    );
  } else if (monthsQuery.fetchStatus === "paused") {
    content = (
      <UiV2Notice
        title="Не удалось подтвердить список отчётов"
        retry={() => void monthsQuery.refetch()}
      >
        Проверь соединение с локальным приложением и повтори чтение.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем закрытые отчёты…" />;
  } else if (!month) {
    content = (
      <UiV2Notice
        title={monthValues.length ? "Закрытый отчёт не найден" : "Закрытых отчётов пока нет"}
      >
        {monthValues.length
          ? "Указанный месяц отсутствует или больше не закрыт. Выбери другой закрытый отчёт в архиве."
          : "Результат появится после закрытия первого отчёта."}{" "}
        <Link to="/v2/reports">Все отчёты →</Link>
      </UiV2Notice>
    );
  } else if (dashboardQuery.isError) {
    content = (
      <UiV2Notice
        title="Не удалось загрузить денежный результат"
        retry={() => void dashboardQuery.refetch()}
      >
        Данные выбранного отчёта сейчас недоступны.
      </UiV2Notice>
    );
  } else if (dashboardQuery.fetchStatus === "paused") {
    content = (
      <UiV2Notice
        title="Не удалось подтвердить денежный результат"
        retry={() => void dashboardQuery.refetch()}
      >
        Значения скрыты до успешного чтения выбранного отчёта.
      </UiV2Notice>
    );
  } else if (!isQueryReady(dashboardQuery)) {
    content = <UiV2Loading label="Проверяем денежный результат…" />;
  } else if (!dashboard) {
    content = (
      <UiV2Notice
        title="Результат отчёта не подтверждён"
        retry={() => void dashboardQuery.refetch()}
      >
        Ответ не совпал с выбранным закрытым месяцем. Значения скрыты.
      </UiV2Notice>
    );
  } else {
    const rows =
      view === "accounts" ? dashboard.result_by_account : dashboard.result_by_instrument_class;
    const otherRows =
      view === "accounts" ? dashboard.result_by_instrument_class : dashboard.result_by_account;
    content = (
      <>
        <label className={resultStyles.monthPicker}>
          Закрытый месяц
          <select onChange={(event) => selectMonth(event.target.value)} value={month.id}>
            {sortReportingMonths(monthsQuery.data ?? [])
              .filter((candidate) => candidate.status === "closed")
              .map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {formatMonth(candidate.year, candidate.month)}
                </option>
              ))}
          </select>
        </label>
        <UiV2ReportContext kind={historical ? "historical" : "current"} month={month}>
          <span className={styles.reportContextLinks}>
            {historical ? (
              <Link to={`/v2/reports/${month.id}`}>Отчёт месяца →</Link>
            ) : (
              <Link to="/v2">Текущий отчёт →</Link>
            )}
            <Link to="/v2/reports">Все отчёты →</Link>
          </span>
        </UiV2ReportContext>
        <p className={resultStyles.explanation}>
          Денежный доход и реализованный результат относятся к{" "}
          {formatMonth(month.year, month.month)}. Нереализованный результат — состояние открытых
          позиций на дату снимка, а не доход только за этот месяц. Пополнения, выводы и погашение
          основного долга не считаются доходом.
        </p>
        <nav aria-label="Вид денежного результата" className={resultStyles.switcher}>
          <button
            aria-current={view === "accounts" ? "page" : undefined}
            onClick={() => selectView("accounts")}
            type="button"
          >
            По счетам
          </button>
          <button
            aria-current={view === "classes" ? "page" : undefined}
            onClick={() => selectView("classes")}
            type="button"
          >
            По классам
          </button>
        </nav>
        {rows === undefined ? (
          <UiV2Notice title="Детализация недоступна">
            В ответе нет выбранного разреза результата.
          </UiV2Notice>
        ) : rows.length === 0 ? (
          <UiV2Notice title="Нет строк результата">
            Для этого закрытого месяца в выбранном разрезе нет данных.
          </UiV2Notice>
        ) : view === "accounts" ? (
          <AccountRows rows={rows as AccountResultPoint[]} />
        ) : (
          <ClassRows rows={rows as InstrumentClassResultPoint[]} />
        )}
        {otherRows === undefined ? (
          <p className={resultStyles.note}>Другой разрез в ответе недоступен.</p>
        ) : null}
        <p className={resultStyles.note}>
          Классы сгруппированы по типу инструмента. Денежные события без инструмента могут быть
          только в строках счетов, поэтому суммы двух разрезов не обязаны совпадать. Итог показан
          только внутри строки; при неизвестном нереализованном результате он недоступен.
        </p>
      </>
    );
  }

  return (
    <UiV2Shell
      active="capital"
      busy={!monthsReady || (month !== null && !isQueryReady(dashboardQuery))}
      header={
        <>
          <p className={styles.eyebrow}>Деталь закрытого отчёта</p>
          <h1>Денежный результат</h1>
          <p className={styles.subtitle}>По счетам и классам инструментов выбранного месяца.</p>
          <p className={resultStyles.backLink}>
            <Link to="/v2/capital">← Капитал</Link>
          </p>
        </>
      }
      v1ReturnPath="/analytics"
    >
      {content}
    </UiV2Shell>
  );
}
