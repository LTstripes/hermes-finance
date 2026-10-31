import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { listAccounts } from "../api/accounts";
import { getCapitalComposition, getClosedReportComparison } from "../api/analytics";
import { listCashBalances } from "../api/cash";
import { getDashboard } from "../api/dashboard";
import { listDeposits } from "../api/deposits";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { listPositions } from "../api/positions";
import { listProperties } from "../api/properties";
import { getRiskAllocation, type RiskAllocationResponse } from "../api/riskAllocation";
import type {
  CapitalCompositionPoint,
  ClosedReportComparison,
  DashboardMortgage,
  PropertySnapshot,
} from "../api/types";
import {
  CapitalCompositionChart,
  type CapitalCompositionMode,
} from "../components/charts/CapitalCompositionChart";
import { PortfolioCoverageNote } from "../components/PortfolioCoverageNote";
import { formatMonth, formatPercent } from "../lib/format";
import { unsupportedMetricReason } from "../lib/riskSupportCopy";
import { ASSET_CLASS_LABELS } from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import { CapitalDraftValuation } from "./CapitalDraftValuation";
import {
  buildHoldingRows,
  filterHoldingRows,
  type HoldingFilter,
  type HoldingRow,
  holdingContextLabel,
  holdingReturnsNavigation,
  isRiskAssetClass,
  UNASSIGNED_CASH_KEY,
} from "./capitalHoldings";
import { CLASS_COLORS } from "./assetClasses";
import { selectNewestDraftAfterLatestClosed, sortReportingMonths } from "./monthSelection";
import capitalStyles from "./UiV2Capital.module.css";
import { UiV2Panel } from "./UiV2Panel";
import {
  isQueryReady,
  UiV2Loading,
  UiV2Notice,
  UiV2ReportContext,
  UiV2WidgetState,
} from "./UiV2StateBlocks";
import { UiV2Shell } from "./UiV2Shell";
import { Allocation, Concentration } from "./UiV2CapitalAllocationPage";
import allocationStyles from "./UiV2CapitalAllocation.module.css";
import styles from "./UiV2Page.module.css";
import { moneyDeltaText as moneyDelta, moneyText as money } from "./valueFormat";

type HistoryWindow = 3 | 12 | "all";

function rowsMatchMonth(
  rows: Array<{ reporting_month_id: number }> | undefined,
  monthId: number | null,
): boolean {
  if (monthId === null) return false;
  return rows?.every((row) => row.reporting_month_id === monthId) ?? false;
}

function isZeroAmount(amount: string): boolean {
  return /^-?0(?:\.0+)?$/.test(amount.trim());
}

function Panel({
  action,
  children,
  eyebrow,
  hint,
  id,
  title,
  wide = false,
}: Omit<Parameters<typeof UiV2Panel>[0], "testIdPrefix">) {
  return (
    <UiV2Panel
      action={action}
      eyebrow={eyebrow}
      hint={hint}
      id={id}
      testIdPrefix="capital-panel"
      title={title}
      wide={wide}
    >
      {children}
    </UiV2Panel>
  );
}

function HeadlineGrid({
  comparison,
  ready,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const current = ready ? (comparison?.current ?? null) : null;
  const retryOrNothing = ready ? undefined : retry;
  const metrics: Array<{
    detail: string;
    eyebrow: string;
    primary?: boolean;
    testId: string;
    value: string | null;
  }> = [
    {
      detail: "Активы за вычетом включённых обязательств",
      eyebrow: "Ликвидный капитал",
      primary: true,
      testId: "capital-net",
      value: current
        ? current.portfolio_source_coverage?.status === "unavailable"
          ? "—"
          : money(current.liquid_capital_net)
        : null,
    },
    {
      detail: "Деньги, депозиты, ценные бумаги и прочее ликвидное",
      eyebrow: "Ликвидные активы",
      testId: "capital-assets",
      value: current ? money(current.liquid_assets_total) : null,
    },
    {
      detail: "Вычитаются из активов, не входят в состав",
      eyebrow: "Включённые обязательства",
      testId: "capital-debts",
      value: current ? `− ${money(current.included_debts)}` : null,
    },
  ];
  return (
    <>
      <section aria-label="Главные показатели капитала" className={styles.metrics}>
        {metrics.map((metric) => (
          <article
            className={`${styles.metric} ${metric.primary ? styles.metricPrimary : ""}`}
            key={metric.testId}
          >
            <p className={styles.eyebrow}>{metric.eyebrow}</p>
            {metric.value === null ? (
              <UiV2WidgetState retry={retryOrNothing} />
            ) : (
              <>
                <p className={styles.metricValue} data-testid={metric.testId}>
                  {metric.value}
                </p>
                {metric.primary ? (
                  <PortfolioCoverageNote coverage={current?.portfolio_source_coverage} />
                ) : null}
                <p className={styles.metricDetail}>{metric.detail}</p>
              </>
            )}
          </article>
        ))}
      </section>
      <p>
        <Link className={styles.contextLink} to="/v2/returns">
          Доходность в целом — вся доступная история и инструменты
        </Link>
      </p>
      <p className={styles.panelFootnote}>
        Ликвидные активы минус включённые обязательства = ликвидный капитал. Жильё и ипотека в
        ликвидный капитал не входят.
      </p>
    </>
  );
}

function CompositionOverTime({
  assetClasses,
  points,
  ready,
  retry,
}: {
  assetClasses: string[];
  points: CapitalCompositionPoint[];
  ready: boolean;
  retry: () => void;
}) {
  const [window, setWindow] = useState<HistoryWindow>(12);
  const [mode, setMode] = useState<CapitalCompositionMode>("amount");
  const visible = window === "all" ? points : points.slice(-window);
  return (
    <Panel
      action={
        <div className={capitalStyles.controls}>
          <fieldset className={styles.segmented} aria-label="Показатель состава">
            <button
              aria-pressed={mode === "amount"}
              onClick={() => setMode("amount")}
              type="button"
            >
              Суммы
            </button>
            <button aria-pressed={mode === "share"} onClick={() => setMode("share")} type="button">
              Доли
            </button>
          </fieldset>
          <fieldset className={styles.segmented} aria-label="Период состава">
            {([3, 12, "all"] as const).map((value) => (
              <button
                aria-pressed={window === value}
                key={value}
                onClick={() => setWindow(value)}
                type="button"
              >
                {value === 3 ? "3 месяца" : value === 12 ? "12 месяцев" : "Всё время"}
              </button>
            ))}
          </fieldset>
        </div>
      }
      eyebrow="Закрытые отчёты"
      id="capital-composition-title"
      title="Состав во времени"
      wide
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : visible.length === 0 ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <div data-point-count={visible.length} data-testid="capital-composition">
          <CapitalCompositionChart
            assetClasses={assetClasses}
            classColors={CLASS_COLORS}
            mode={mode}
            points={visible}
          />
          <p className={styles.panelFootnote}>
            Показаны последние {visible.length} закрытых отчёта. Пропуски остаются пропусками;
            значения не интерполируются.
          </p>
        </div>
      )}
    </Panel>
  );
}

function AccountBuckets({
  filter,
  onPickAccount,
  retry,
  risk,
}: {
  filter: HoldingFilter;
  onPickAccount: (key: string, label: string) => void;
  retry: () => void;
  risk: RiskAllocationResponse;
}) {
  const metric = risk.allocation_by_account;
  const unsupported = unsupportedMetricReason(metric.support.status, metric.support.reason_codes);
  if (unsupported) {
    return <UiV2WidgetState retry={retry} title={unsupported} />;
  }
  if (metric.items.length === 0) {
    return <p className={capitalStyles.muted}>В закрытом отчёте нет строк для этого среза.</p>;
  }
  return (
    <>
      <ul className={capitalStyles.bucketList}>
        {metric.items.map((item) => (
          <li key={item.key}>
            <button
              aria-pressed={filter?.kind === "account" && filter.value === item.key}
              className={capitalStyles.bucketButton}
              data-testid={`capital-bucket-${item.key}`}
              onClick={() => onPickAccount(item.key, item.label)}
              type="button"
            >
              <span className={capitalStyles.className}>
                {item.key === UNASSIGNED_CASH_KEY ? "Наличные без привязки к счёту" : item.label}
              </span>
              <strong>{money(item.amount)}</strong>
              <span className={capitalStyles.classShare}>
                {formatPercent(item.share_pct, { digits: 1 })}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className={styles.panelFootnote}>
        Наличные в этом срезе остаются без привязки к счёту. Счета ниже показывают только депозиты и
        позиции.
      </p>
    </>
  );
}

function HoldingsBlock({
  filter,
  onPickAccount,
  monthId,
  resetFilter,
  retryRisk,
  risk,
  riskReady,
  rows,
  lists,
}: {
  filter: HoldingFilter;
  lists: Record<"cash" | "deposit" | "position", { ready: boolean; retry: () => void }>;
  monthId: number;
  onPickAccount: (key: string, label: string) => void;
  resetFilter: () => void;
  retryRisk: () => void;
  risk: RiskAllocationResponse | undefined;
  riskReady: boolean;
  rows: HoldingRow[];
}) {
  const location = useLocation();
  const backParams = new URLSearchParams(location.search);
  if (filter) {
    backParams.set("holding_kind", filter.kind);
    backParams.set("holding_value", filter.value);
    backParams.set("holding_label", filter.label);
  } else {
    for (const key of ["holding_kind", "holding_value", "holding_label"]) backParams.delete(key);
  }
  const back = `${location.pathname}${backParams.size ? `?${backParams}` : ""}`;
  const visible = filterHoldingRows(rows, filter);
  const sections: Array<{ kind: HoldingRow["kind"]; title: string }> = [
    { kind: "cash", title: "Денежные строки" },
    { kind: "deposit", title: "Вклады" },
    { kind: "position", title: "Позиции" },
  ];
  return (
    <Panel eyebrow="Строки отчёта" id="capital-holdings-title" title="Где лежит капитал" wide>
      {filter ? (
        <div className={capitalStyles.filterBar}>
          <span>Фильтр: {filter.label}</span>
          <button onClick={resetFilter} type="button">
            Сбросить
          </button>
        </div>
      ) : null}
      <div className={capitalStyles.subBlock}>
        <h3>Счета</h3>
        {!riskReady || !risk ? (
          <UiV2WidgetState retry={retryRisk} />
        ) : (
          <AccountBuckets
            filter={filter}
            onPickAccount={onPickAccount}
            retry={retryRisk}
            risk={risk}
          />
        )}
      </div>
      {sections.map((section) => {
        const list = lists[section.kind];
        const sectionRows = visible.filter((row) => row.kind === section.kind);
        return (
          <div className={capitalStyles.subBlock} key={section.kind}>
            <h3>{section.title}</h3>
            {!list.ready ? (
              <UiV2WidgetState retry={list.retry} />
            ) : sectionRows.length === 0 ? (
              <p className={capitalStyles.muted}>
                {filter
                  ? "В фильтре нет строк этого вида."
                  : "В закрытом отчёте нет строк этого вида."}
              </p>
            ) : (
              <ul className={capitalStyles.holdingList}>
                {sectionRows.map((row) => (
                  <li
                    className={capitalStyles.holdingRow}
                    data-included={row.includeInCapital ? "true" : "false"}
                    data-testid={`capital-holding-${row.key}`}
                    key={row.key}
                  >
                    <div className={capitalStyles.holdingMain}>
                      {row.kind === "position" && holdingReturnsNavigation(row, back).href ? (
                        <Link
                          className={capitalStyles.holdingName}
                          to={holdingReturnsNavigation(row, back).href ?? ""}
                        >
                          {row.name}
                        </Link>
                      ) : (
                        <span className={capitalStyles.holdingName}>{row.name}</span>
                      )}
                      {row.kind === "position" && !holdingReturnsNavigation(row, back).href && (
                        <small>{holdingReturnsNavigation(row).reason}</small>
                      )}
                      <span className={capitalStyles.holdingMeta}>
                        {holdingContextLabel(row)}
                        {row.accountName === null ? "" : ` · ${row.accountName}`}
                      </span>
                    </div>
                    <strong className={capitalStyles.holdingAmount}>{money(row.amount)}</strong>
                    {row.includeInCapital ? null : (
                      <span className={capitalStyles.excludedBadge}>
                        не входит в ликвидный капитал
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
      <p className={styles.panelFootnote}>
        Строки показаны как есть в закрытом отчёте. Итоги берутся из подтверждённой сводки, а не из
        суммы строк. <Link to={`/v2/data/months/${monthId}`}>Данные отчётного месяца →</Link>
      </p>
    </Panel>
  );
}

function PropertyBlock({
  mortgage,
  properties,
  ready,
  retry,
}: {
  mortgage: DashboardMortgage | null;
  properties: PropertySnapshot[];
  ready: boolean;
  retry: () => void;
}) {
  const mortgageClosed = mortgage !== null && isZeroAmount(mortgage.mortgage_balance.amount);
  return (
    <Panel
      eyebrow="Отдельно от ликвидного капитала"
      id="capital-property-title"
      title="Недвижимость"
      wide
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : (
        <>
          <ul className={capitalStyles.holdingList}>
            {properties.map((property) => (
              <li className={capitalStyles.holdingRow} key={property.id}>
                <div className={capitalStyles.holdingMain}>
                  <span className={capitalStyles.holdingName}>{property.name}</span>
                  <span className={capitalStyles.holdingMeta}>Оценка и остаток ипотеки</span>
                </div>
                <strong className={capitalStyles.holdingAmount}>
                  {money(property.estimated_value)}
                </strong>
                <span className={capitalStyles.excludedBadge}>
                  ипотека {money(property.mortgage_balance)}
                </span>
              </li>
            ))}
          </ul>
          {mortgage ? (
            <dl className={styles.netSummary}>
              <div>
                <dt>Остаток ипотеки по отчёту</dt>
                <dd>{money(mortgage.mortgage_balance)}</dd>
              </div>
              <div>
                <dt>Покрытие ипотеки капиталом</dt>
                <dd>
                  {mortgageClosed
                    ? "ипотека закрыта"
                    : formatPercent(mortgage.coverage_pct, { digits: 1 })}
                </dd>
              </div>
              {mortgageClosed ? null : (
                <div>
                  <dt>Разница: капитал − ипотека</dt>
                  <dd>{moneyDelta(mortgage.gap)}</dd>
                </div>
              )}
            </dl>
          ) : null}
          <p className={styles.panelFootnote}>
            Недвижимость и ипотека не входят в ликвидный капитал и не смешиваются с составом.
            Разница показана со знаком: положительная — капитала больше остатка ипотеки,
            отрицательная — меньше.
          </p>
        </>
      )}
    </Panel>
  );
}

export default function UiV2CapitalPage() {
  const [params] = useSearchParams();
  const [filter, setFilter] = useState<HoldingFilter>(() => {
    const kind = params.get("holding_kind"),
      value = params.get("holding_value"),
      label = params.get("holding_label");
    if (
      ["holding_kind", "holding_value", "holding_label"].some(
        (key) => params.getAll(key).length !== 1,
      ) ||
      !value ||
      !label ||
      label.length > 80
    )
      return null;
    if (kind === "class" && /^[a-z_]+$/.test(value)) return { kind, value, label };
    if (kind === "risk_class" && isRiskAssetClass(value))
      return { kind, value, label: ASSET_CLASS_LABELS[value] };
    if (kind === "account" && (/^account:[1-9]\d*$/.test(value) || value === UNASSIGNED_CASH_KEY))
      return { kind, value, label };
    return null;
  });

  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const { latestClosed, newestDraft: newerDraft } = selectNewestDraftAfterLatestClosed(months);
  const closedId = latestClosed?.id ?? null;
  const closed = closedId !== null;

  const comparisonQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.closedReportComparison,
    queryFn: ({ signal }) => getClosedReportComparison(signal),
    refetchOnWindowFocus: true,
  });
  const compositionQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
    refetchOnWindowFocus: true,
  });
  const riskQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.riskAllocation(closedId, 5),
    queryFn: ({ signal }) => getRiskAllocation(closedId as number, 5, "v1", signal),
    refetchOnWindowFocus: true,
  });
  const dashboardQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.dashboard(closedId),
    queryFn: ({ signal }) => getDashboard(closedId as number, signal),
    refetchOnWindowFocus: true,
  });
  const cashQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.cashBalances(closedId),
    queryFn: ({ signal }) => listCashBalances(closedId as number, signal),
    refetchOnWindowFocus: true,
  });
  const depositsQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.deposits(closedId),
    queryFn: ({ signal }) => listDeposits(closedId as number, signal),
    refetchOnWindowFocus: true,
  });
  const positionsQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.positions(closedId),
    queryFn: ({ signal }) => listPositions(closedId as number, undefined, signal),
    refetchOnWindowFocus: true,
  });
  const propertiesQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.properties(closedId),
    queryFn: ({ signal }) => listProperties(closedId as number, signal),
    refetchOnWindowFocus: true,
  });
  const accountsQuery = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    refetchOnWindowFocus: true,
  });
  const instrumentsQuery = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
    refetchOnWindowFocus: true,
  });

  const monthsReady = isQueryReady(monthsQuery);
  const comparisonReady =
    isQueryReady(comparisonQuery) &&
    comparisonQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
    comparisonQuery.data.current?.reporting_month_id === closedId;
  const compositionReady =
    isQueryReady(compositionQuery) &&
    compositionQuery.data?.points.at(-1)?.reporting_month_id === closedId;
  const riskReady =
    isQueryReady(riskQuery) &&
    riskQuery.data?.reporting_month_id === closedId &&
    riskQuery.data.as_of_date === latestClosed?.snapshot_date;
  const dashboardReady =
    isQueryReady(dashboardQuery) && dashboardQuery.data?.month?.id === closedId;
  const accountsReady = isQueryReady(accountsQuery);
  const instrumentsReady = isQueryReady(instrumentsQuery);
  const cashReady =
    accountsReady && isQueryReady(cashQuery) && rowsMatchMonth(cashQuery.data, closedId);
  const depositsReady =
    accountsReady && isQueryReady(depositsQuery) && rowsMatchMonth(depositsQuery.data, closedId);
  const positionsReady =
    accountsReady &&
    instrumentsReady &&
    isQueryReady(positionsQuery) &&
    rowsMatchMonth(positionsQuery.data, closedId);
  const propertiesReady =
    isQueryReady(propertiesQuery) && rowsMatchMonth(propertiesQuery.data, closedId);

  const comparison = comparisonReady ? comparisonQuery.data : undefined;
  const holdingRows = useMemo(
    () =>
      buildHoldingRows({
        accounts: accountsQuery.data ?? [],
        cash: cashQuery.data ?? [],
        deposits: depositsQuery.data ?? [],
        instruments: instrumentsQuery.data ?? [],
        positions: positionsReady ? (positionsQuery.data ?? []) : [],
      }),
    [
      accountsQuery.data,
      cashQuery.data,
      depositsQuery.data,
      instrumentsQuery.data,
      positionsQuery.data,
      positionsReady,
    ],
  );

  const pickRiskClass = (value: string) => {
    if (isRiskAssetClass(value))
      setFilter({ kind: "risk_class", value, label: ASSET_CLASS_LABELS[value] });
  };
  const pickAccount = (key: string, label: string) =>
    setFilter({
      kind: "account",
      label: key === UNASSIGNED_CASH_KEY ? "наличные без привязки к счёту" : label,
      value: key,
    });
  const resetFilter = () => setFilter(null);

  const capitalBackParams = new URLSearchParams(params);
  if (filter) {
    capitalBackParams.set("holding_kind", filter.kind);
    capitalBackParams.set("holding_value", filter.value);
    capitalBackParams.set("holding_label", filter.label);
  } else {
    for (const key of ["holding_kind", "holding_value", "holding_label"])
      capitalBackParams.delete(key);
  }
  const capitalBack = `/v2/capital${capitalBackParams.size ? `?${capitalBackParams}` : ""}`;

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Показатели капитала скрыты, пока актуальный закрытый отчёт не подтверждён.
      </UiV2Notice>
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем последний закрытый отчёт…" />;
  } else if (!latestClosed) {
    content = (
      <UiV2Notice title="Закрой первый отчёт">
        «Капитал» строится только по закрытым данным. Черновик не выдаётся за подтверждённую
        финансовую картину. <Link to="/v2/close">Перейти к закрытию месяца →</Link>
      </UiV2Notice>
    );
  } else {
    const mortgage = dashboardReady ? (dashboardQuery.data?.mortgage ?? null) : null;
    content = (
      <>
        <UiV2ReportContext month={latestClosed}>
          <span className={styles.reportContextLinks}>
            <Link to={`/v2/capital/monthly-result?month=${latestClosed.id}`}>
              Денежный результат месяца →
            </Link>
            <Link to="/v2/reports">Все отчёты →</Link>
          </span>
        </UiV2ReportContext>
        {newerDraft ? (
          <p className={capitalStyles.draftNote} data-testid="capital-draft-note">
            {formatMonth(newerDraft.year, newerDraft.month)} ещё не закрыт — картина остаётся по
            последнему закрытому отчёту. <Link to="/v2">Черновик месяца в «Мои финансы» →</Link>
          </p>
        ) : null}
        <HeadlineGrid
          comparison={comparison}
          ready={comparisonReady}
          retry={() => void comparisonQuery.refetch()}
        />
        {accountsReady ? (
          <CapitalDraftValuation months={months} accounts={accountsQuery.data ?? []} />
        ) : null}
        <div className={styles.homeGrid}>
          <CompositionOverTime
            assetClasses={compositionReady ? (compositionQuery.data?.asset_classes ?? []) : []}
            points={compositionReady ? (compositionQuery.data?.points ?? []) : []}
            ready={compositionReady}
            retry={() => void compositionQuery.refetch()}
          />
          <Panel
            eyebrow="Состав капитала"
            id="capital-allocation-title"
            title="Распределение и концентрация"
            wide
          >
            {!riskReady ? (
              <UiV2WidgetState retry={() => void riskQuery.refetch()} />
            ) : (
              <>
                <div className={allocationStyles.grid}>
                  <Allocation
                    expanded
                    metric={riskQuery.data?.allocation_by_asset_class}
                    title="По классам активов"
                    onSelect={(key) => pickRiskClass(key)}
                  />
                  <Allocation
                    expanded
                    account
                    metric={riskQuery.data?.allocation_by_account}
                    title="По счетам"
                    onSelect={pickAccount}
                  />
                </div>
                <Concentration
                  expanded
                  metric={riskQuery.data?.top_positions}
                  basis="Основа долей · ликвидные активы"
                  title="Крупнейшие позиции"
                  renderLabel={(item) => {
                    const row = holdingRows.find(
                      (r) =>
                        r.key === `position-${item.position_id}` &&
                        r.accountId === item.account_id &&
                        r.instrumentId === item.instrument_id,
                    );
                    const target = row ? holdingReturnsNavigation(row, capitalBack) : null;
                    return target?.href ? <Link to={target.href}>{item.label}</Link> : item.label;
                  }}
                />
              </>
            )}
          </Panel>
          {propertiesQuery.isError ||
          (propertiesReady && (propertiesQuery.data?.length ?? 0) > 0) ? (
            <PropertyBlock
              mortgage={mortgage}
              properties={propertiesReady ? (propertiesQuery.data ?? []) : []}
              ready={propertiesReady}
              retry={() => void propertiesQuery.refetch()}
            />
          ) : null}
          <HoldingsBlock
            filter={filter}
            lists={{
              cash: { ready: cashReady, retry: () => void cashQuery.refetch() },
              deposit: { ready: depositsReady, retry: () => void depositsQuery.refetch() },
              position: { ready: positionsReady, retry: () => void positionsQuery.refetch() },
            }}
            monthId={latestClosed.id}
            onPickAccount={pickAccount}
            resetFilter={resetFilter}
            retryRisk={() => void riskQuery.refetch()}
            risk={riskReady ? riskQuery.data : undefined}
            riskReady={riskReady}
            rows={holdingRows}
          />
        </div>
      </>
    );
  }

  return (
    <UiV2Shell
      active="capital"
      busy={!monthsReady}
      header={
        <>
          <p className={styles.eyebrow}>Откуда складывается капитал</p>
          <h1>Капитал</h1>
          <p className={styles.subtitle}>Ликвидный капитал, его состав и счета.</p>
          <p className={capitalStyles.backLink}>
            <Link to="/v2">← Мои финансы</Link>
          </p>
        </>
      }
    >
      {content}
      {monthsReady && accountsReady && !latestClosed ? (
        <CapitalDraftValuation months={months} accounts={accountsQuery.data ?? []} />
      ) : null}
    </UiV2Shell>
  );
}
