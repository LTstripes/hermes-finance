import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { listMonths } from "../api/months";
import {
  getRiskAllocation,
  type RiskAllocationMetric,
  type RiskConcentrationItem,
  type RiskConcentrationMetric,
  type RiskMetricSupport,
  type RiskMoneyValue,
  type RiskSupportIssue,
} from "../api/riskAllocation";
import type { ReportingMonth } from "../api/types";
import { HelpTip, Table, Td, Th } from "../components/ui";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../lib/format";
import {
  ASSET_CLASS_LABELS,
  sourceKindLabel,
  supportReasonLabel,
  supportStatusLabel,
} from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import { sortReportingMonths } from "./monthSelection";
import styles from "./UiV2CapitalAllocation.module.css";
import pageStyles from "./UiV2Page.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { UiV2Tabs } from "./UiV2Tabs";

const TOP_N = 5;

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
  return value == null ? "—" : formatPercent(value, { digits: 1, share: true });
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
      {approximate ? <p>Часть сумм приблизительна</p> : null}
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

export function Allocation({
  title,
  metric,
  account = false,
  expanded = false,
  onSelect,
}: {
  title: string;
  metric: RiskAllocationMetric | undefined;
  account?: boolean;
  expanded?: boolean;
  onSelect?: (key: string, label: string) => void;
}) {
  if (!metric) return <UiV2WidgetState title={`${title}: нет данных`} />;
  const partialCoverage = metric.coverage_pct !== null && metric.coverage_pct !== "100.00";
  return (
    <details className={styles.metric} open={expanded || undefined}>
      <summary>
        <span className={styles.metricName}>{title}</span>
        {partialCoverage ? <span>покрытие {percent(metric.coverage_pct)}</span> : null}
        <Support support={metric.support} />
      </summary>
      <div className={styles.metricBody}>
        {partialCoverage ? (
          <p className={styles.partial}>
            ⚠ часть сумм не распределена{" "}
            <HelpTip label={`Нераспределённые суммы: ${title}`}>
              Основа долей — полная сумма ликвидных активов. Неизвестные группы входят в неё.
            </HelpTip>
          </p>
        ) : null}
        <details>
          <summary>Подробнее о суммах</summary>
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
        </details>
        {metric.items.length === 0 ? (
          <p className={styles.empty}>Нет данных</p>
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
                <tr
                  key={item.key}
                  data-testid={onSelect && !account ? `capital-class-${item.key}` : undefined}
                >
                  <Td data-label={account ? "Счёт" : "Класс активов"}>
                    {onSelect ? (
                      <button
                        className={styles.groupButton}
                        type="button"
                        onClick={() => onSelect(item.key, item.label)}
                      >
                        {account
                          ? item.key === "unassigned_cash"
                            ? (ASSET_CLASS_LABELS[item.key] ?? item.label)
                            : item.label
                          : (ASSET_CLASS_LABELS[item.key] ?? item.label)}
                      </button>
                    ) : account ? (
                      item.key === "unassigned_cash" ? (
                        (ASSET_CLASS_LABELS[item.key] ?? item.label)
                      ) : (
                        item.label
                      )
                    ) : (
                      (ASSET_CLASS_LABELS[item.key] ?? item.label)
                    )}
                  </Td>
                  <Td className={styles.amount} data-label="Сумма" numeric>
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

export function Concentration({
  title,
  metric,
  basis,
  event = false,
  expanded = false,
  renderLabel,
}: {
  title: string;
  metric: RiskConcentrationMetric | undefined;
  basis?: string;
  event?: boolean;
  expanded?: boolean;
  renderLabel?: (item: RiskConcentrationItem) => ReactNode;
}) {
  if (!metric) return <UiV2WidgetState title={`${title}: нет данных`} />;
  return (
    <details className={styles.metric} open={expanded || undefined}>
      <summary>
        <span className={styles.metricName}>{title}</span>
        <span>
          Топ-{metric.top_n} · {percent(metric.top_share_pct)}
        </span>
        <Support support={metric.support} />
      </summary>
      <div className={styles.metricBody}>
        <dl className={`${styles.facts} ${event ? "" : styles.concentrationFacts}`}>
          {basis ? (
            <div>
              <dt>{basis}</dt>
              <dd>{money(metric.denominator)}</dd>
            </div>
          ) : null}
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
          <p className={styles.empty}>Нет данных</p>
        ) : (
          <Table className={`${styles.table} ${event ? "" : styles.concentrationTable}`}>
            <caption className={styles.visuallyHidden}>{title}</caption>
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
                    {renderLabel ? renderLabel(item) : item.label}
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

export default function UiV2CapitalAllocationPage() {
  const [params, setParams] = useSearchParams();
  const monthValues = params.getAll("month");
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
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
      <UiV2WidgetState retry={() => void monthsQuery.refetch()} title="Не удалось загрузить" />
    );
  } else if (monthsQuery.fetchStatus === "paused") {
    content = (
      <UiV2WidgetState retry={() => void monthsQuery.refetch()} title="Не удалось загрузить" />
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
      <UiV2WidgetState retry={() => void riskQuery.refetch()} title="Не удалось загрузить" />
    );
  } else if (riskQuery.fetchStatus === "paused") {
    content = (
      <UiV2WidgetState retry={() => void riskQuery.refetch()} title="Не удалось загрузить" />
    );
  } else if (!riskReady) {
    content = <UiV2Loading label="Проверяем распределение выбранного месяца…" />;
  } else if (!data) {
    content = (
      <UiV2WidgetState retry={() => void riskQuery.refetch()} title="Не удалось загрузить" />
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
        {portfolioEmpty ? <UiV2WidgetState title="Портфель пуст" /> : null}
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
          Будущие события: с {formatDate(data.as_of_date)}, 12 месяцев. Погашение — не доход.
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
          <UiV2Tabs
            label="Капитал"
            tabs={[
              { label: "Обзор", to: "/v2/capital", active: false },
              { label: "Распределение", to: "/v2/capital/allocation", active: true },
            ]}
          />
        </>
      }
    >
      {content}
    </UiV2Shell>
  );
}
