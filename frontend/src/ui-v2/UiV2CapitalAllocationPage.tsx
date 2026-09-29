import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { listMonths } from "../api/months";
import {
  getRiskAllocation,
  type RiskAllocationMetric,
  type RiskAllocationResponse,
  type RiskConcentrationMetric,
  type RiskMetricSupport,
  type RiskMoneyValue,
  type RiskSupportIssue,
} from "../api/riskAllocation";
import type { ReportingMonth } from "../api/types";
import { Table, Td, Th } from "../components/ui";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../lib/format";
import {
  ASSET_CLASS_LABELS,
  sourceKindLabel,
  supportReasonLabel,
  supportStatusLabel,
} from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import { sortReportingMonths } from "./monthSelection";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import pageStyles from "./UiV2Page.module.css";
import styles from "./UiV2CapitalAllocation.module.css";

const TOP_N = 5;

const UNSUPPORTED_DIMENSIONS: Record<string, string> = {
  issuer: "Эмитент",
  currency: "Валюта",
  maturity: "Срок погашения",
  broker: "Брокер",
  bank: "Банк",
};

function selectedMonth(values: string[], months: ReportingMonth[]): ReportingMonth | null {
  if (values.length === 0) return sortReportingMonths(months)[0] ?? null;
  if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) return null;
  const id = Number(values[0]);
  return Number.isSafeInteger(id) ? (months.find((month) => month.id === id) ?? null) : null;
}

function money(value: RiskMoneyValue | null | undefined): string {
  if (!value?.amount || !value.currency) return "—";
  return formatMoney(value.amount, { currency: value.currency === "RUB" ? "₽" : value.currency });
}

function percent(value: string | null | undefined): string {
  return value == null ? "—" : formatPercent(value, { digits: 2 });
}

function Support({ support }: { support: RiskMetricSupport }) {
  return (
    <span className={styles.support} data-status={support.status}>
      {supportStatusLabel(support.status)}
    </span>
  );
}

function Limits({
  support,
  excluded,
  approximate = false,
}: {
  support: RiskMetricSupport;
  excluded: RiskSupportIssue[];
  approximate?: boolean;
}) {
  if (!approximate && support.reason_codes.length === 0 && excluded.length === 0) return null;
  return (
    <div className={styles.limits}>
      {approximate ? <p>Часть сумм приблизительна по сохранённым данным.</p> : null}
      {support.reason_codes.length > 0 ? (
        <ul>
          {support.reason_codes.map((reason) => (
            <li key={reason}>{supportReasonLabel(reason)}</li>
          ))}
        </ul>
      ) : null}
      {excluded.length > 0 ? (
        <details>
          <summary>Исключённые строки: {excluded.length}</summary>
          <ul>
            {excluded.map((issue) => (
              <li
                key={`${issue.source_kind}-${issue.source_id ?? "unknown"}-${issue.status}-${issue.reason_codes.join("|")}`}
              >
                {sourceKindLabel(issue.source_kind)} · {supportStatusLabel(issue.status)} ·{" "}
                {issue.reason_codes.map(supportReasonLabel).join(", ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function Allocation({
  title,
  metric,
  account = false,
}: {
  title: string;
  metric: RiskAllocationMetric | undefined;
  account?: boolean;
}) {
  if (!metric)
    return <UiV2Notice title={`${title}: нет ответа`}>Срез отсутствует в ответе.</UiV2Notice>;
  const zeroDenominator = /^0+(?:\.0+)?$/.test(metric.denominator.amount);
  const undefinedCoverage = metric.coverage_pct === null && !zeroDenominator;
  const partialCoverage = metric.coverage_pct !== null && metric.coverage_pct !== "100.00";
  const includedUnallocated = metric.items.find(
    (item) => item.key === "unknown_asset_class" || item.key === "unassigned_cash",
  );
  return (
    <details className={styles.metric}>
      <summary>
        <span className={styles.metricName}>{title}</span>
        <span>
          {metric.items.length} групп ·{" "}
          {zeroDenominator && metric.coverage_pct === null
            ? "нулевая основа, доля не определяется"
            : metric.coverage_pct === null
              ? "покрытие неизвестно"
              : `покрытие известных групп ${percent(metric.coverage_pct)}`}
        </span>
        <Support support={metric.support} />
      </summary>
      <div className={styles.metricBody}>
        {zeroDenominator && metric.coverage_pct === null ? (
          <p className={styles.intro}>При нулевой основе процент покрытия не определяется.</p>
        ) : null}
        {undefinedCoverage ? (
          <p className={styles.partial}>API не определил долю покрытия для этого среза.</p>
        ) : null}
        {partialCoverage ? (
          <p className={styles.partial}>
            Покрытие известных групп ниже 100%. Основа долей остаётся полной суммой ликвидных
            активов из ответа.
          </p>
        ) : null}
        {metric.support.status !== "supported" || metric.excluded.length > 0 ? (
          <p className={styles.partial}>
            Доступность данных: {supportStatusLabel(metric.support.status).toLowerCase()}.
            Ограничения и исключённые строки указаны ниже.
          </p>
        ) : null}
        {includedUnallocated ? (
          <p className={styles.intro}>
            Не отнесённая к известным группам сумма уже показана строкой «
            {ASSET_CLASS_LABELS[includedUnallocated.key] ?? includedUnallocated.label}» и входит в
            основу долей. Не прибавляй её повторно.
          </p>
        ) : null}
        <dl className={styles.facts}>
          <div>
            <dt>Основа долей · ликвидные активы</dt>
            <dd>{money(metric.denominator)}</dd>
          </div>
          <div>
            <dt>Распределено по известным группам</dt>
            <dd>{money(metric.covered_amount)}</dd>
          </div>
          <div>
            <dt>Не отнесено к известным группам · в составе основы</dt>
            <dd>{money(metric.unallocated_amount)}</dd>
          </div>
        </dl>
        {metric.items.length === 0 ? (
          <p className={styles.empty}>
            {metric.support.status === "supported"
              ? "Нет строк в этом срезе."
              : "Строки для этого среза недоступны."}
          </p>
        ) : (
          <Table className={styles.table}>
            <caption>{title}</caption>
            <thead>
              <tr>
                <Th>{account ? "Счёт" : "Класс активов"}</Th>
                <Th numeric>Сумма</Th>
                <Th numeric>Доля ликвидных активов</Th>
              </tr>
            </thead>
            <tbody>
              {metric.items.map((item) => (
                <tr key={item.key}>
                  <Td data-label={account ? "Счёт" : "Класс активов"}>
                    {account
                      ? item.key === "unassigned_cash"
                        ? (ASSET_CLASS_LABELS[item.key] ?? item.label)
                        : item.label
                      : (ASSET_CLASS_LABELS[item.key] ?? item.label)}
                  </Td>
                  <Td data-label="Сумма" numeric>
                    {money(item.amount)}
                  </Td>
                  <Td data-label="Доля ликвидных активов" numeric>
                    {percent(item.share_pct)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <Limits excluded={metric.excluded} support={metric.support} />
      </div>
    </details>
  );
}

function Concentration({
  title,
  metric,
  basis,
  event = false,
}: {
  title: string;
  metric: RiskConcentrationMetric | undefined;
  basis: string;
  event?: boolean;
}) {
  if (!metric)
    return <UiV2Notice title={`${title}: нет ответа`}>Срез отсутствует в ответе.</UiV2Notice>;
  const qualified =
    metric.support.status !== "supported" || metric.excluded.length > 0 || metric.is_approximate;
  return (
    <details className={styles.metric}>
      <summary>
        <span className={styles.metricName}>{title}</span>
        <span>
          Топ {metric.top_n} · {percent(metric.top_share_pct)} от включённого
        </span>
        <Support support={metric.support} />
      </summary>
      <div className={styles.metricBody}>
        <p className={styles.partial}>
          Показаны только крупнейшие {metric.top_n} из включённых строк. Топ не означает полный
          охват{event ? " будущих событий" : " портфеля"}
          {qualified ? "; данные имеют ограничения" : ""}.
        </p>
        <dl className={styles.facts}>
          <div>
            <dt>{basis}</dt>
            <dd>{money(metric.denominator)}</dd>
          </div>
          <div>
            <dt>Сумма топ {metric.top_n}</dt>
            <dd>{money(metric.top_amount)}</dd>
          </div>
          <div>
            <dt>Доля от основы</dt>
            <dd>{percent(metric.top_share_pct)}</dd>
          </div>
        </dl>
        {metric.items.length === 0 ? (
          <p className={styles.empty}>
            {metric.support.status === "supported"
              ? event
                ? "Нет датированных событий в окне."
                : "Нет позиций с положительной оценкой."
              : "Срез недоступен или покрытие не подтверждено."}
          </p>
        ) : (
          <Table className={styles.table}>
            <caption>{title}</caption>
            <thead>
              <tr>
                <Th>{event ? "Событие / инструмент" : "Позиция"}</Th>
                <Th numeric>Сумма</Th>
                <Th numeric>Доля от основы</Th>
                {event ? <Th numeric>Событий</Th> : null}
              </tr>
            </thead>
            <tbody>
              {metric.items.map((item) => (
                <tr key={item.key}>
                  <Td data-label={event ? "Событие / инструмент" : "Позиция"}>
                    {item.label}
                    {item.is_approximate ? " · приблизительно" : ""}
                  </Td>
                  <Td data-label="Сумма" numeric>
                    {money(item.amount)}
                  </Td>
                  <Td data-label="Доля от основы" numeric>
                    {percent(item.share_pct)}
                  </Td>
                  {event ? (
                    <Td data-label="Событий" numeric>
                      {item.event_count ?? "—"}
                    </Td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <Limits
          approximate={metric.is_approximate}
          excluded={metric.excluded}
          support={metric.support}
        />
      </div>
    </details>
  );
}

function Availability({ support }: { support: RiskAllocationResponse["support"] }) {
  return (
    <details className={styles.availability}>
      <summary>Остальные измерения и ограничения</summary>
      <p>API сообщает доступность этих измерений, но не отдаёт распределение по ним.</p>
      <ul>
        {Object.entries(UNSUPPORTED_DIMENSIONS).map(([key, title]) => {
          const state = support[key];
          return (
            <li key={key}>
              <strong>{title}</strong>
              {state ? (
                <>
                  <Support support={state} />
                  {state.reason_codes.map(supportReasonLabel).join(", ")}
                </>
              ) : (
                " · состояние не получено"
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

export default function UiV2CapitalAllocationPage() {
  const [params, setParams] = useSearchParams();
  const monthValues = params.getAll("month");
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const monthsReady = isQueryReady(monthsQuery);
  const month = monthsReady ? selectedMonth(monthValues, monthsQuery.data ?? []) : null;
  const riskQuery = useQuery({
    enabled: month !== null,
    queryKey: queryKeys.riskAllocation(month?.id ?? null, TOP_N),
    queryFn: ({ signal }) => {
      if (!month) throw new Error("No reporting month selected");
      return getRiskAllocation(month.id, TOP_N, "v1", signal);
    },
    refetchOnWindowFocus: true,
  });
  const riskReady = isQueryReady(riskQuery);
  const data =
    riskReady &&
    riskQuery.data?.reporting_month_id === month?.id &&
    riskQuery.data?.as_of_date === month?.snapshot_date
      ? riskQuery.data
      : null;

  function changeMonth(value: string) {
    const next = new URLSearchParams(params);
    next.set("month", value);
    setParams(next);
  }

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice retry={() => void monthsQuery.refetch()} title="Не удалось загрузить месяцы">
        Распределение скрыто до проверки списка месяцев.
      </UiV2Notice>
    );
  } else if (monthsQuery.fetchStatus === "paused") {
    content = (
      <UiV2Notice retry={() => void monthsQuery.refetch()} title="Список месяцев не подтверждён">
        Повтори чтение из локального приложения.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем месяцы…" />;
  } else if (!month) {
    content = (
      <UiV2Notice title={monthValues.length ? "Месяц не найден" : "Нет отчётных месяцев"}>
        {monthValues.length
          ? "Адрес указывает на отсутствующий или некорректный месяц. Выбери месяц в архиве."
          : "Создай отчётный месяц, чтобы увидеть распределение."}{" "}
        <Link to="/v2/reports">Все отчёты →</Link>
      </UiV2Notice>
    );
  } else if (riskQuery.isError) {
    content = (
      <UiV2Notice retry={() => void riskQuery.refetch()} title="Не удалось загрузить распределение">
        Данные выбранного месяца скрыты до успешного чтения.
      </UiV2Notice>
    );
  } else if (riskQuery.fetchStatus === "paused") {
    content = (
      <UiV2Notice retry={() => void riskQuery.refetch()} title="Распределение не подтверждено">
        Повтори чтение из локального приложения.
      </UiV2Notice>
    );
  } else if (!riskReady) {
    content = <UiV2Loading label="Проверяем распределение выбранного месяца…" />;
  } else if (!data) {
    content = (
      <UiV2Notice retry={() => void riskQuery.refetch()} title="Ответ не совпал со снимком">
        Данные скрыты: месяц или дата снимка в ответе отличаются от выбранных.
      </UiV2Notice>
    );
  } else {
    const portfolioEmpty =
      /^0+(?:\.0+)?$/.test(data.liquid_assets_total?.amount ?? "") &&
      data.allocation_by_asset_class?.support.status === "supported" &&
      data.allocation_by_account?.support.status === "supported" &&
      data.top_positions?.support.status === "supported" &&
      data.allocation_by_asset_class.items.length === 0 &&
      data.allocation_by_account.items.length === 0 &&
      data.top_positions.items.length === 0;
    content = (
      <>
        <label className={styles.monthPicker}>
          Отчётный месяц
          <select onChange={(event) => changeMonth(event.target.value)} value={month.id}>
            {sortReportingMonths(monthsQuery.data ?? []).map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {formatMonth(candidate.year, candidate.month)} ·{" "}
                {candidate.status === "closed" ? "закрыт" : "черновик"}
              </option>
            ))}
          </select>
        </label>
        <section aria-label="Контекст снимка" className={styles.snapshot}>
          <div>
            <span>Месяц</span>
            <strong>
              {formatMonth(month.year, month.month)} ·{" "}
              {month.status === "closed" ? "закрыт" : "черновик"}
            </strong>
          </div>
          <div>
            <span>На дату</span>
            <strong>{formatDate(data.as_of_date)}</strong>
          </div>
          <div>
            <span>Ликвидные активы</span>
            <strong>{money(data.liquid_assets_total)}</strong>
          </div>
        </section>
        {portfolioEmpty ? (
          <UiV2Notice title="Портфель пуст">
            В выбранном снимке нет строк ликвидного портфеля. Нулевые суммы в срезах показаны только
            там, где их вернул API.
          </UiV2Notice>
        ) : null}
        <p className={styles.intro}>
          Доли распределений и позиций относятся к ликвидным активам в базовой валюте{" "}
          {data.base_currency}. Неизвестные и исключённые строки отмечены отдельно.
        </p>
        <h2 className={styles.groupTitle}>Распределение</h2>
        <div className={styles.grid}>
          <Allocation metric={data.allocation_by_asset_class} title="По классам активов" />
          <Allocation account metric={data.allocation_by_account} title="По счетам" />
        </div>
        <h2 className={styles.groupTitle}>Концентрация</h2>
        <Concentration
          basis="Основа долей · ликвидные активы"
          metric={data.top_positions}
          title="Крупнейшие позиции"
        />
        <p className={styles.intro}>
          Будущие датированные события: с {formatDate(data.as_of_date)} и следующие 12 месяцев.
          Основа долей каждого среза — сумма включённых датированных событий, а не капитал.
          Погашение основного долга не является пассивным доходом. События без даты сюда не входят.
        </p>
        <div className={styles.grid}>
          <Concentration
            basis="Основа долей · включённые выплаты"
            event
            metric={data.payout_concentration}
            title="Выплаты"
          />
          <Concentration
            basis="Основа долей · включённые погашения"
            event
            metric={data.redemption_concentration}
            title="Погашения"
          />
        </div>
        <Availability support={data.support ?? {}} />
      </>
    );
  }

  return (
    <UiV2Shell
      active="capital"
      busy={!monthsReady || (month !== null && !riskReady)}
      header={
        <>
          <p className={pageStyles.eyebrow}>Деталь капитала</p>
          <h1>Распределение и концентрация</h1>
          <p className={pageStyles.subtitle}>
            Срез ликвидного портфеля и будущих датированных событий.
          </p>
          <p className={styles.backLink}>
            <Link to="/v2/capital">← Капитал</Link>
          </p>
        </>
      }
      v1ReturnPath="/analytics/risk-allocation"
    >
      {content}
    </UiV2Shell>
  );
}
