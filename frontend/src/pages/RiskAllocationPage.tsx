import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { formatApiError } from "../api/client";
import {
  getRiskAllocation,
  type RiskAllocationMetric,
  type RiskConcentrationMetric,
  type RiskMetricSupport,
  type RiskMoneyValue,
  type RiskSupportIssue,
  type RiskSupportStatus,
} from "../api/riskAllocation";
import { listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import {
  Badge,
  DataValue,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { queryKeys } from "../queryClient";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../lib/format";
import { labelOf } from "../lib/labels";

const ASSET_CLASS_LABELS: Record<string, string> = {
  cash: "Наличные",
  deposits: "Депозиты",
  stock: "Акции",
  bond: "Облигации",
  fund: "Фонды",
  currency: "Валюта",
  gold: "Золото",
  other: "Прочее",
  unknown_asset_class: "Неизвестный класс активов",
  unassigned_cash: "Наличные без привязки к счёту",
};

const SUPPORT_LABELS: Record<string, string> = {
  asset_class: "Класс активов",
  account: "Счета",
  issuer: "Эмитент",
  currency: "Валюта",
  maturity: "Погашение / срок",
  broker: "Брокер",
  bank: "Банк",
  top_positions: "Крупнейшие позиции",
  payout: "Выплаты",
  redemption: "Погашения",
};

const REASON_LABELS: Record<string, string> = {
  bank_identity_not_persisted: "банк не хранится в текущей схеме",
  broker_identity_not_persisted: "брокер не хранится в текущей схеме",
  cash_not_account_linked: "наличные не связаны со счётом",
  currency_conversion_not_supported: "конвертация валюты не поддерживается",
  currency_not_persisted: "валюта не сохранена",
  deposit_forecast_not_concentratable: "оценка депозита не имеет датированного события",
  instrument_not_persisted: "инструмент не сохранён для события",
  instrument_type_not_authoritative: "класс инструмента не подтверждён сохранёнными данными",
  issuer_not_persisted: "эмитент не хранится в текущей схеме",
  maturity_not_persisted: "срок погашения не хранится в текущей схеме",
  no_dated_payouts: "датированных событий в окне нет",
  unsupported_position_valuation: "оценка позиции непригодна для расчёта",
};

function sortMonths(months: ReportingMonth[]): ReportingMonth[] {
  return [...months].sort((a, b) => b.year - a.year || b.month - a.month || b.id - a.id);
}

function statusLabel(status: RiskSupportStatus): string {
  return labelOf(
    { supported: "Поддерживается", unavailable: "Недоступно", unknown: "Неизвестно" },
    status,
  );
}

function statusTone(status: RiskSupportStatus): "ok" | "missing" | "unknown" {
  if (status === "supported") return "ok";
  return status === "unavailable" ? "missing" : "unknown";
}

function money(value: RiskMoneyValue): string {
  return formatMoney(value.amount, { currency: value.currency === "RUB" ? "₽" : value.currency });
}

function percent(value: string | null): string {
  return formatPercent(value, { digits: 2 });
}

function supportReason(reason: string): string {
  return REASON_LABELS[reason] ?? "дополнительное ограничение данных";
}

function concentrationEmptyState(
  metric: RiskConcentrationMetric,
  kind: "positions" | "payouts" | "redemptions",
  asOfDate: string,
): { title: string; description: string } {
  if (metric.support.status !== "supported") {
    const reason = metric.support.reason_codes[0];
    return {
      title: "События недоступны",
      description: reason
        ? `Этот срез нельзя построить: ${supportReason(reason)}.`
        : "Этот срез нельзя построить из доступных данных.",
    };
  }
  if (kind === "payouts") {
    return {
      title: "Выплат в окне нет",
      description:
        "С " +
        formatDate(asOfDate) +
        " и следующие 12 месяцев нет датированных ожидаемых выплат. События без даты в этот срез не входят.",
    };
  }
  if (kind === "redemptions") {
    return {
      title: "Погашений в окне нет",
      description:
        "С " +
        formatDate(asOfDate) +
        " и следующие 12 месяцев нет датированных ожидаемых погашений. События без даты в этот срез не входят.",
    };
  }
  return {
    title: "Нет позиций",
    description: "В выбранном месяце нет позиций с положительной оценкой.",
  };
}

const SOURCE_KIND_LABELS: Record<string, string> = {
  cash_balance: "Денежный остаток",
  deposit: "Депозит",
  expected_flow: "Ожидаемая выплата",
  payout: "Выплата",
  position: "Позиция",
  property: "Недвижимость",
};

function sourceKindLabel(value: string): string {
  return SOURCE_KIND_LABELS[value] ?? "Исключённая строка";
}

function SupportBadge({ support }: { support: RiskMetricSupport }) {
  return <Badge tone={statusTone(support.status)}>{statusLabel(support.status)}</Badge>;
}

function SupportReasons({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <ul className="risk-allocation__reasons">
      {reasons.map((reason) => (
        <li key={reason}>{supportReason(reason)}</li>
      ))}
    </ul>
  );
}

function ExcludedIssues({ issues }: { issues: RiskSupportIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <details className="risk-allocation__excluded">
      <summary>Исключённые строки: {issues.length}</summary>
      <ul className="risk-allocation__reasons">
        {issues.map((issue) => (
          <li
            key={`${issue.source_kind}-${issue.source_id ?? "none"}-${issue.status}-${issue.reason_codes.join("|")}`}
          >
            <Badge tone={statusTone(issue.status)}>{statusLabel(issue.status)}</Badge>{" "}
            {sourceKindLabel(issue.source_kind)} —{" "}
            {issue.reason_codes.map(supportReason).join(", ")}
          </li>
        ))}
      </ul>
    </details>
  );
}

function MetricSupportDetails({
  metric,
}: {
  metric: RiskAllocationMetric | RiskConcentrationMetric;
}) {
  const isApproximate = "is_approximate" in metric && metric.is_approximate;
  const hasDetails =
    isApproximate || metric.support.reason_codes.length > 0 || metric.excluded.length > 0;
  if (!hasDetails) return null;

  return (
    <details className="risk-allocation__metric-details">
      <summary>
        Ограничения данных <SupportBadge support={metric.support} />
      </summary>
      {isApproximate ? (
        <p className="risk-allocation__approximate">
          Некоторые строки приблизительные — это отмечено в сохранённых данных.
        </p>
      ) : null}
      <SupportReasons reasons={metric.support.reason_codes} />
      <ExcludedIssues issues={metric.excluded} />
    </details>
  );
}

function MetricSummary({
  metric,
  kind,
}: {
  metric: RiskAllocationMetric | RiskConcentrationMetric;
  kind: "allocation" | "concentration";
}) {
  const concentration = kind === "concentration" ? (metric as RiskConcentrationMetric) : null;
  const allocation = kind === "allocation" ? (metric as RiskAllocationMetric) : null;
  return (
    <div className="risk-allocation__metric-summary">
      <DataValue label="Всего в срезе" value={money(metric.denominator)} />
      {concentration ? (
        <>
          <DataValue
            label={`Крупнейшие ${concentration.top_n}`}
            value={money(concentration.top_amount)}
          />
          <DataValue label="Доля крупнейших" value={percent(concentration.top_share_pct)} />
        </>
      ) : allocation ? (
        <>
          <DataValue label="Покрыто" value={money(allocation.covered_amount)} />
          <DataValue label="Покрытие" value={percent(allocation.coverage_pct)} />
          <DataValue label="Не распределено" value={money(allocation.unallocated_amount)} />
        </>
      ) : null}
    </div>
  );
}

function AllocationMetricPanel({
  title,
  metric,
  account,
}: {
  title: string;
  metric: RiskAllocationMetric;
  account?: boolean;
}) {
  return (
    <Panel label="Распределение" title={title}>
      <MetricSummary kind="allocation" metric={metric} />
      {metric.items.length === 0 ? (
        <EmptyState
          description="В выбранном месяце нет строк для этого среза."
          inline
          title="Нет данных"
        />
      ) : (
        <Table>
          <caption className="visually-hidden">{title}</caption>
          <thead>
            <tr>
              <Th>{account ? "Счёт" : "Класс"}</Th>
              <Th numeric>Сумма</Th>
              <Th numeric>Доля</Th>
            </tr>
          </thead>
          <tbody>
            {metric.items.map((item) => (
              <tr key={item.key}>
                <Td>{account ? item.label : labelOf(ASSET_CLASS_LABELS, item.key)}</Td>
                <Td numeric>{money(item.amount)}</Td>
                <Td numeric>{percent(item.share_pct)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <MetricSupportDetails metric={metric} />
    </Panel>
  );
}

function ConcentrationPanel({
  title,
  label,
  metric,
  emptyKind,
  asOfDate,
}: {
  title: string;
  label: string;
  metric: RiskConcentrationMetric;
  emptyKind: "positions" | "payouts" | "redemptions";
  asOfDate: string;
}) {
  const emptyState = concentrationEmptyState(metric, emptyKind, asOfDate);
  return (
    <Panel label={label} title={title}>
      <MetricSummary kind="concentration" metric={metric} />
      {metric.items.length === 0 ? (
        <EmptyState description={emptyState.description} inline title={emptyState.title} />
      ) : (
        <Table>
          <caption className="visually-hidden">{title}</caption>
          <thead>
            <tr>
              <Th>Получатель / позиция</Th>
              <Th numeric>Сумма</Th>
              <Th numeric>Доля</Th>
              <Th numeric>Событий</Th>
            </tr>
          </thead>
          <tbody>
            {metric.items.map((item) => (
              <tr key={item.key}>
                <Td>
                  {item.label}
                  {item.is_approximate ? (
                    <span className="risk-allocation__row-note"> · приблизительно</span>
                  ) : null}
                </Td>
                <Td numeric>{money(item.amount)}</Td>
                <Td numeric>{percent(item.share_pct)}</Td>
                <Td numeric>{item.event_count ?? "—"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <MetricSupportDetails metric={metric} />
    </Panel>
  );
}

function SupportMatrix({ support }: { support: Record<string, RiskMetricSupport> }) {
  const keys = ["currency", "issuer", "maturity", "broker", "bank"];
  return (
    <details className="risk-allocation__support-details">
      <summary>Ограничения данных и полнота</summary>
      <Panel label="Полнота данных" title="Какие срезы доступны сейчас">
        <div className="risk-allocation__support-grid">
          {keys.map((key) => {
            const value = support[key];
            if (!value) return null;
            return (
              <div className="risk-allocation__support-item" key={key}>
                <div className="risk-allocation__support-heading">
                  <strong>{SUPPORT_LABELS[key]}</strong>
                  <SupportBadge support={value} />
                </div>
                <SupportReasons reasons={value.reason_codes} />
              </div>
            );
          })}
        </div>
        <p className="muted risk-allocation__support-note">
          Состояния описывают доступность данных, а не уровень риска. Сохранённая оценка позиции в
          рублях не исключается из ликвидного капитала из-за недоступной метаинформации.
        </p>
      </Panel>
    </details>
  );
}

export function RiskAllocationPage() {
  const [months, setMonths] = useState<ReportingMonth[]>([]);
  const [selectedMonthId, setSelectedMonthId] = useState<number | null>(null);
  const [monthsLoading, setMonthsLoading] = useState(true);
  const [monthsError, setMonthsError] = useState<string | null>(null);
  const topN = 5;

  useEffect(() => {
    const controller = new AbortController();
    setMonthsLoading(true);
    void listMonths(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        const sorted = sortMonths(rows);
        setMonths(sorted);
        setSelectedMonthId((previous) =>
          previous != null && sorted.some((month) => month.id === previous)
            ? previous
            : (sorted[0]?.id ?? null),
        );
        setMonthsError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMonths([]);
          setSelectedMonthId(null);
          setMonthsError(formatApiError(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setMonthsLoading(false);
      });
    return () => controller.abort();
  }, []);

  const selectedMonth = useMemo(
    () => months.find((month) => month.id === selectedMonthId) ?? null,
    [months, selectedMonthId],
  );
  const riskQuery = useQuery({
    queryKey: queryKeys.riskAllocation(selectedMonthId, topN),
    queryFn: ({ signal }) => getRiskAllocation(selectedMonthId as number, topN, "v1", signal),
    enabled: selectedMonthId != null,
  });
  const data = riskQuery.data?.reporting_month_id === selectedMonthId ? riskQuery.data : null;
  const hasPortfolioRows = data
    ? data.allocation_by_asset_class.items.length > 0 ||
      data.allocation_by_account.items.length > 0 ||
      data.top_positions.items.length > 0
    : false;

  return (
    <section className="risk-allocation-page stack-18">
      <header className="page-header risk-allocation-page__header">
        <p className="eyebrow">Аналитика</p>
        <h1>Распределение и концентрация</h1>
        <p className="page-header__description">
          Срез ликвидного портфеля для владельца. Все суммы, доли и состояния доступности относятся
          к выбранному снимку; недвижимость сюда не входит.
        </p>
      </header>

      <Panel label="Отчётный месяц" title="Какой срез смотрим">
        {monthsLoading ? (
          <LoadingState description="Загружаем месяцы…" inline />
        ) : monthsError ? (
          <ErrorState description={monthsError} inline title="Не удалось загрузить месяцы" />
        ) : months.length === 0 ? (
          <EmptyState
            description="Сначала создай хотя бы один отчётный месяц."
            inline
            title="Нет месяцев"
          />
        ) : (
          <Field htmlFor="risk-allocation-month" label="Месяц">
            <Select
              id="risk-allocation-month"
              onChange={(event) => setSelectedMonthId(Number(event.target.value))}
              value={selectedMonthId ?? ""}
            >
              {months.map((month) => (
                <option key={month.id} value={month.id}>
                  {formatMonth(month.year, month.month)} ·{" "}
                  {month.status === "closed" ? "утверждён" : "черновик"}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </Panel>

      {selectedMonth ? (
        <section className="risk-allocation__snapshot" aria-label="Сведения о выбранном снимке">
          <DataValue
            label="Снимок"
            value={formatMonth(selectedMonth.year, selectedMonth.month)}
            meta={selectedMonth.status === "closed" ? "Утверждён" : "Черновик"}
          />
          <DataValue
            label="Дата снимка"
            value={formatDate(data?.as_of_date ?? selectedMonth.snapshot_date)}
          />
          <DataValue
            label="Ликвидные активы"
            value={data ? money(data.liquid_assets_total) : "—"}
            size="lg"
          />
        </section>
      ) : null}

      {selectedMonthId != null && riskQuery.isPending ? (
        <LoadingState description="Загружаем распределение выбранного месяца…" />
      ) : null}
      {riskQuery.isError ? (
        <ErrorState
          description={formatApiError(riskQuery.error)}
          title="Не удалось загрузить распределение"
        />
      ) : null}

      {data ? (
        <>
          {!hasPortfolioRows ? (
            <EmptyState
              description="В выбранном месяце нет ликвидных активов и позиций для отображения."
              title="Портфель пуст"
            />
          ) : null}
          <div className="risk-allocation__event-window">
            <strong>Окно будущих событий</strong>
            <span>
              Датированные выплаты и погашения: с {formatDate(data.as_of_date)} · следующие 12
              месяцев. Учитываются только события с известной датой.
            </span>
          </div>
          <div className="risk-allocation__grid">
            <AllocationMetricPanel
              metric={data.allocation_by_asset_class}
              title="По классам активов"
            />
            <AllocationMetricPanel account metric={data.allocation_by_account} title="По счетам" />
          </div>
          <ConcentrationPanel
            asOfDate={data.as_of_date}
            emptyKind="positions"
            label="Позиции"
            metric={data.top_positions}
            title={`${data.top_positions.top_n} крупнейших позиций`}
          />
          <div className="risk-allocation__grid">
            <ConcentrationPanel
              asOfDate={data.as_of_date}
              emptyKind="payouts"
              label="Будущие денежные события"
              metric={data.payout_concentration}
              title="Концентрация выплат"
            />
            <ConcentrationPanel
              asOfDate={data.as_of_date}
              emptyKind="redemptions"
              label="Будущие денежные события"
              metric={data.redemption_concentration}
              title="Концентрация погашений"
            />
          </div>
          <SupportMatrix support={data.support} />
        </>
      ) : null}
    </section>
  );
}
