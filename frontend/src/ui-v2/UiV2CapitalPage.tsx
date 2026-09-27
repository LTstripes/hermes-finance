import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { listAccounts } from "../api/accounts";
import { getCapitalComposition, getClosedReportComparison } from "../api/analytics";
import { listCashBalances } from "../api/cash";
import { getDashboard } from "../api/dashboard";
import { listDebts } from "../api/debts";
import { listDeposits } from "../api/deposits";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { getPerformanceAttribution, getPortfolioTwrr, getPortfolioXirr } from "../api/performance";
import { listPositions } from "../api/positions";
import { listProperties } from "../api/properties";
import { getRiskAllocation, type RiskAllocationResponse } from "../api/riskAllocation";
import type {
  Account,
  CapitalCompositionPoint,
  ClosedReportComparison,
  ClosedReportSnapshot,
  DashboardLinkedPair,
  DashboardMortgage,
  DebtEntry,
  PerformanceAttribution,
  PortfolioTwrr,
  PortfolioXirr,
  PropertySnapshot,
} from "../api/types";
import {
  CapitalCompositionChart,
  type CapitalCompositionMode,
} from "../components/charts/CapitalCompositionChart";
import { buildLinkedPairFacts, pairFactNote } from "../components/LinkedPairContext";
import { PortfolioCoverageNote } from "../components/PortfolioCoverageNote";
import { isGuidedCloseStepId, monthlyCloseReturnPath } from "../components/month-close/navigation";
import { buildCapitalCompositionSeries } from "../lib/capitalComposition";
import { formatDate, formatMoney, formatMonth, formatPercent } from "../lib/format";
import {
  performanceAttributionUnavailableMessage,
  portfolioTwrrUnavailableMessage,
  portfolioXirrUnavailableMessage,
  VALUE_BRIDGE_DISCLAIMER,
  VALUE_BRIDGE_LABEL,
} from "../lib/performanceMessages";
import { unsupportedMetricReason } from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import {
  buildHoldingRows,
  filterHoldingRows,
  type HoldingFilter,
  type HoldingRow,
  holdingContextLabel,
  UNASSIGNED_CASH_KEY,
} from "./capitalHoldings";
import { CLASS_COLORS, classMeta } from "./assetClasses";
import {
  resolveMonthSelection,
  selectNewestDraftAfterLatestClosed,
  sortReportingMonths,
} from "./monthSelection";
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
import styles from "./UiV2Page.module.css";
import {
  liabilityTone,
  moneyDeltaText as moneyDelta,
  moneyText as money,
  moneyTone as tone,
} from "./valueFormat";

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

/** Secondary performance evidence starts collapsed on the narrow layout only. */
function useNarrowViewport(maxWidthPx = 800): boolean {
  const query = `(max-width: ${maxWidthPx}px)`;
  const [narrow, setNarrow] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const handle = (event: MediaQueryListEvent) => setNarrow(event.matches);
    setNarrow(list.matches);
    list.addEventListener("change", handle);
    return () => list.removeEventListener("change", handle);
  }, [query]);
  return narrow;
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

function CurrentAllocation({
  assetClasses,
  comparison,
  filter,
  onPickClass,
  ready,
  retry,
  retryRisk,
  risk,
  riskReady,
}: {
  assetClasses: string[];
  comparison: ClosedReportComparison | undefined;
  filter: HoldingFilter;
  onPickClass: (assetClass: string) => void;
  ready: boolean;
  retry: () => void;
  retryRisk: () => void;
  risk: RiskAllocationResponse | undefined;
  riskReady: boolean;
}) {
  const current: ClosedReportSnapshot | null = ready ? (comparison?.current ?? null) : null;
  const datum =
    current && assetClasses.length > 0
      ? buildCapitalCompositionSeries([current], assetClasses)[0]
      : undefined;
  const concentration = risk?.top_positions;
  const unsupportedReason =
    risk && concentration
      ? unsupportedMetricReason(concentration.support.status, concentration.support.reason_codes)
      : null;
  return (
    <Panel
      eyebrow="Текущий снимок"
      hint="Только подтверждённые строки закрытого отчёта"
      id="capital-now-title"
      title="Сейчас"
    >
      {!current || !datum ? (
        <UiV2WidgetState retry={ready ? undefined : retry} />
      ) : (
        <>
          <ul className={capitalStyles.classList}>
            {assetClasses.map((assetClass) => {
              const amount = datum.amounts[assetClass] ?? "0.00";
              const share = datum.shares[assetClass] ?? null;
              return (
                <li key={assetClass}>
                  <button
                    aria-pressed={filter?.kind === "class" && filter.value === assetClass}
                    className={capitalStyles.classButton}
                    data-testid={`capital-class-${assetClass}`}
                    onClick={() => onPickClass(assetClass)}
                    type="button"
                  >
                    <span
                      aria-hidden="true"
                      className={capitalStyles.classDot}
                      style={{ background: classMeta(assetClass).color }}
                    />
                    <span className={capitalStyles.className}>{classMeta(assetClass).label}</span>
                    <strong>{formatMoney(amount, { currency: "₽" })}</strong>
                    <span className={capitalStyles.classShare}>
                      {share === null ? "—" : formatPercent(share, { digits: 1 })}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <dl className={styles.netSummary}>
            <div>
              <dt>Ликвидные активы</dt>
              <dd>{money(current.liquid_assets_total)}</dd>
            </div>
            <div className={styles.deduction}>
              <dt>Включённые обязательства</dt>
              <dd>− {money(current.included_debts)}</dd>
            </div>
            <div>
              <dt>Ликвидный капитал</dt>
              <dd>
                {current.portfolio_source_coverage?.status === "unavailable"
                  ? "—"
                  : money(current.liquid_capital_net)}
              </dd>
            </div>
          </dl>
          <div className={capitalStyles.subBlock}>
            <h3>Топ позиций</h3>
            {!riskReady || !concentration ? (
              <UiV2WidgetState retry={retryRisk} />
            ) : unsupportedReason ? (
              <p className={capitalStyles.muted}>{unsupportedReason}</p>
            ) : concentration.items.length === 0 ? (
              <p className={capitalStyles.muted}>Нет позиций с положительной оценкой.</p>
            ) : (
              <ul className={capitalStyles.positionList} data-testid="capital-top-positions">
                {concentration.items.map((item) => (
                  <li key={item.key}>
                    <span className={capitalStyles.className}>{item.label}</span>
                    <strong>{money(item.amount)}</strong>
                    <span className={capitalStyles.classShare}>
                      {formatPercent(item.share_pct, { digits: 1 })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className={styles.panelFootnote}>
              Доля позиции считается от ликвидных активов. Это не оценка риска.
            </p>
          </div>
        </>
      )}
    </Panel>
  );
}

function ChangeBlock({
  comparison,
  ready,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  retry: () => void;
}) {
  const deltas = ready ? (comparison?.asset_class_deltas ?? null) : null;
  const reconciles =
    ready &&
    comparison?.availability === "available" &&
    comparison.net_liquid_capital_reconciles === true;
  return (
    <Panel
      eyebrow="Изменение состояния"
      hint="Изменение состояния, не инвестиционная доходность"
      id="capital-change-title"
      title="Где изменились суммы"
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : !deltas ? (
        <UiV2WidgetState title="Нужны два закрытых отчёта для сравнения" />
      ) : !reconciles ? (
        <UiV2WidgetState title="Изменение не подтверждено: строки не сходятся с итогом" />
      ) : (
        <>
          <ul className={styles.changeList} data-testid="capital-change-list">
            {deltas.map((item) => (
              <li key={item.asset_class}>
                <span>{classMeta(item.asset_class).label}</span>
                <strong data-tone={tone(item.amount)}>{moneyDelta(item.amount)}</strong>
              </li>
            ))}
            <li className={styles.liabilityChange}>
              <span>Включённые обязательства</span>
              <strong data-tone={liabilityTone(comparison?.included_debts_delta)}>
                {moneyDelta(comparison?.included_debts_delta)}
              </strong>
            </li>
          </ul>
          <div className={styles.changeTotal}>
            <span>Изменение ликвидного капитала</span>
            <strong data-tone={tone(comparison?.liquid_capital_net_delta)}>
              {comparison?.liquid_capital_net_delta_coverage?.status === "unavailable"
                ? "—"
                : moneyDelta(comparison?.liquid_capital_net_delta)}
            </strong>
            <PortfolioCoverageNote coverage={comparison?.liquid_capital_net_delta_coverage} />
          </div>
          <p className={styles.panelFootnote}>
            Та же пара закрытых отчётов, что на «Мои финансы». Перемещение между классами может
            менять строки без роста капитала; рост обязательств уменьшает чистый капитал.
          </p>
        </>
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
                      <span className={capitalStyles.holdingName}>{row.name}</span>
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
        суммы строк. <Link to={`/months/${monthId}`}>Отчёт месяца в предыдущем интерфейсе →</Link>
      </p>
    </Panel>
  );
}

function LinkedPairsBlock({
  accounts,
  comparison,
  comparisonReady,
  debts,
  pairs,
  ready,
  retry,
}: {
  accounts: Account[];
  comparison: ClosedReportComparison | undefined;
  comparisonReady: boolean;
  debts: DebtEntry[];
  pairs: DashboardLinkedPair[] | null;
  ready: boolean;
  retry: () => void;
}) {
  const facts = useMemo(
    () => buildLinkedPairFacts(ready ? pairs : null, debts, accounts),
    [accounts, debts, pairs, ready],
  );
  const current = comparisonReady ? (comparison?.current ?? null) : null;
  return (
    <Panel eyebrow="Контекст" id="capital-pairs-title" title="Связанные пары" wide>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : facts.length === 0 ? (
        <p className={capitalStyles.muted}>В закрытом отчёте связанных пар нет.</p>
      ) : (
        <>
          {facts.some((fact) => !fact.contextAvailable) ? (
            <p className={capitalStyles.muted} data-testid="capital-pair-gap" role="status">
              Для части связей не хватает факта актива за выбранный месяц. Недоступные суммы
              остаются «—» и не подменяются нулём.
            </p>
          ) : null}
          <ul className={capitalStyles.pairList}>
            {facts.map((fact) => (
              <li
                className={capitalStyles.pairCard}
                data-testid={`capital-pair-${fact.debtId}`}
                key={fact.debtId}
              >
                <div className={capitalStyles.pairNames}>
                  <strong>{fact.accountName}</strong>
                  <span className={capitalStyles.muted}>↔ {fact.debtName}</span>
                </div>
                <dl className={capitalStyles.pairValues}>
                  <div>
                    <dt>Активы связанных пар</dt>
                    <dd>{fact.contextAvailable ? money(fact.accountBalance) : "—"}</dd>
                  </div>
                  <div>
                    <dt>Обязательства связанных пар</dt>
                    <dd>{money(fact.debtBalance)}</dd>
                  </div>
                  <div>
                    <dt>Вклад связанных пар</dt>
                    <dd>{fact.contextAvailable ? money(fact.netContribution) : "—"}</dd>
                  </div>
                </dl>
                <p className={styles.panelFootnote}>{pairFactNote(fact)}</p>
              </li>
            ))}
          </ul>
          {current ? (
            <p className={styles.panelFootnote} data-testid="capital-pair-aggregate">
              В текущем снимке: активы связанных пар {money(current.linked_pair_assets)} ·
              обязательства связанных пар {money(current.linked_pair_debts)} · вклад связанных пар{" "}
              {money(current.linked_pair_net_contribution)}. Эти суммы уже входят в ликвидные активы
              и включённые обязательства.
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function PerformanceItem({
  currency,
  metricLabel,
  ready,
  reason,
  period,
  retry,
  testId,
}: {
  currency: string | null;
  metricLabel: string;
  period: string | null;
  ready: boolean;
  reason: string | null;
  retry: () => void;
  testId: string;
}) {
  return (
    <article data-testid={testId}>
      <p className={styles.eyebrow}>{metricLabel}</p>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : currency === null ? (
        <p className={capitalStyles.muted}>
          {reason ?? "Не удалось получить подтверждённый результат для выбранного периода."}
        </p>
      ) : (
        <>
          <p className={capitalStyles.performanceValue}>{currency}</p>
          <p className={capitalStyles.muted}>{period}</p>
        </>
      )}
    </article>
  );
}

function PerformanceBlock({
  attribution,
  attributionReady,
  pairEnd,
  pairStart,
  retry,
  twrr,
  twrrReady,
  xirr,
  xirrReady,
}: {
  attribution: PerformanceAttribution | null;
  attributionReady: boolean;
  pairEnd: string | null;
  pairStart: string | null;
  retry: () => void;
  twrr: PortfolioTwrr | null;
  twrrReady: boolean;
  xirr: PortfolioXirr | null;
  xirrReady: boolean;
}) {
  const narrow = useNarrowViewport();
  const period = pairStart && pairEnd ? `${formatDate(pairStart)} — ${formatDate(pairEnd)}` : null;
  const bridgeValue =
    attribution &&
    attribution.availability === "available" &&
    attribution.quality === "exact" &&
    attribution.value !== null
      ? moneyDelta(attribution.value)
      : null;
  const xirrValue =
    xirr && xirr.availability === "available" && xirr.value !== null
      ? formatPercent(xirr.value, { digits: 2, signed: true })
      : null;
  const twrrValue =
    twrr && twrr.availability === "available" && twrr.value !== null
      ? formatPercent(twrr.value, { digits: 2, signed: true })
      : null;
  return (
    <Panel eyebrow="Доходность" id="capital-performance-title" title="Доходность портфеля" wide>
      {pairStart === null || pairEnd === null ? (
        <UiV2WidgetState title="Нужны два закрытых отчёта для расчёта за период" />
      ) : (
        <details className={capitalStyles.collapsible} open={!narrow}>
          <summary>Показать расчёты за период между двумя закрытыми отчётами</summary>
          <div className={capitalStyles.performanceList}>
            <PerformanceItem
              currency={bridgeValue}
              metricLabel={`${VALUE_BRIDGE_LABEL} · ${VALUE_BRIDGE_DISCLAIMER}`}
              period={period}
              ready={attributionReady}
              reason={
                attribution
                  ? performanceAttributionUnavailableMessage(attribution.reason_codes)
                  : null
              }
              retry={retry}
              testId="capital-performance-bridge"
            />
            <PerformanceItem
              currency={xirrValue}
              metricLabel="Годовая доходность (XIRR)"
              period={period}
              ready={xirrReady}
              reason={xirr ? portfolioXirrUnavailableMessage(xirr.reason_codes) : null}
              retry={retry}
              testId="capital-performance-xirr"
            />
            <PerformanceItem
              currency={twrrValue}
              metricLabel="Доходность за период (TWRR)"
              period={period}
              ready={twrrReady}
              reason={twrr ? portfolioTwrrUnavailableMessage(twrr.reason_codes) : null}
              retry={retry}
              testId="capital-performance-twrr"
            />
          </div>
        </details>
      )}
      <p className={styles.panelFootnote}>
        Расчёты доступны только для того же интервала между двумя закрытыми отчётами.{" "}
        <Link className={styles.contextLink} to="/analytics">
          Все расчёты в предыдущем интерфейсе →
        </Link>
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
  const [filter, setFilter] = useState<HoldingFilter>(null);

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
  const debtsQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.debts(closedId),
    queryFn: ({ signal }) => listDebts(closedId as number, signal),
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
  const riskReady = isQueryReady(riskQuery) && riskQuery.data?.reporting_month_id === closedId;
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
  const debtsReady = isQueryReady(debtsQuery) && rowsMatchMonth(debtsQuery.data, closedId);
  const propertiesReady =
    isQueryReady(propertiesQuery) && rowsMatchMonth(propertiesQuery.data, closedId);

  const comparison = comparisonReady ? comparisonQuery.data : undefined;
  const current: ClosedReportSnapshot | null = comparison?.current ?? null;
  const previous = comparison?.previous ?? null;
  const pairStart =
    comparison?.availability === "available" &&
    current &&
    previous &&
    previous.snapshot_date < current.snapshot_date
      ? previous.snapshot_date
      : null;
  const pairEnd = pairStart === null ? null : (current?.snapshot_date ?? null);

  const attributionQuery = useQuery({
    enabled: pairStart !== null,
    queryKey: queryKeys.performanceAttribution(pairStart, pairEnd),
    queryFn: ({ signal }) =>
      getPerformanceAttribution(pairStart as string, pairEnd as string, signal),
    refetchOnWindowFocus: true,
  });
  const xirrQuery = useQuery({
    enabled: pairStart !== null,
    queryKey: queryKeys.portfolioXirr(pairStart, pairEnd),
    queryFn: ({ signal }) => getPortfolioXirr(pairStart as string, pairEnd as string, signal),
    refetchOnWindowFocus: true,
  });
  const twrrQuery = useQuery({
    enabled: pairStart !== null,
    queryKey: queryKeys.portfolioTwrr(pairStart, pairEnd),
    queryFn: ({ signal }) => getPortfolioTwrr(pairStart as string, pairEnd as string, signal),
    refetchOnWindowFocus: true,
  });

  const periodMatches = (period: { start_date: string; end_date: string } | undefined) =>
    period !== undefined &&
    pairStart !== null &&
    period.start_date === pairStart &&
    period.end_date === pairEnd;
  const attributionReady =
    isQueryReady(attributionQuery) &&
    attributionQuery.data?.scope === "portfolio" &&
    periodMatches(attributionQuery.data.period);
  const xirrReady =
    isQueryReady(xirrQuery) &&
    xirrQuery.data?.scope === "portfolio" &&
    periodMatches(xirrQuery.data.period);
  const twrrReady =
    isQueryReady(twrrQuery) &&
    twrrQuery.data?.scope === "portfolio" &&
    periodMatches(twrrQuery.data.period);

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

  const requestedMonth = resolveMonthSelection(params.getAll("month"), months);
  const requestedStepValues = params.getAll("step");
  const requestedStep =
    requestedStepValues.length === 1 && isGuidedCloseStepId(requestedStepValues[0])
      ? requestedStepValues[0]
      : null;
  const v1ReturnPath =
    requestedMonth.kind === "selected"
      ? requestedStep
        ? monthlyCloseReturnPath({
            monthId: requestedMonth.month.id,
            origin: "monthly-close",
            step: requestedStep,
          })
        : `/months/${requestedMonth.month.id}`
      : latestClosed
        ? `/months/${latestClosed.id}`
        : "/v1";

  const pickClass = (assetClass: string) =>
    setFilter({ kind: "class", label: classMeta(assetClass).label, value: assetClass });
  const pickAccount = (key: string, label: string) =>
    setFilter({
      kind: "account",
      label: key === UNASSIGNED_CASH_KEY ? "наличные без привязки к счёту" : label,
      value: key,
    });
  const resetFilter = () => setFilter(null);

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
        финансовую картину. <Link to="/monthly-close">Перейти к закрытию месяца →</Link>
      </UiV2Notice>
    );
  } else {
    const pairs = dashboardReady
      ? (dashboardQuery.data?.summary?.liquid_capital?.linked_pairs ?? null)
      : null;
    const mortgage = dashboardReady ? (dashboardQuery.data?.mortgage ?? null) : null;
    const pairsReady = dashboardReady && pairs !== null && debtsReady && accountsReady;
    content = (
      <>
        <UiV2ReportContext month={latestClosed}>
          <span className={styles.reportContextLinks}>
            <Link to="/v2/reports">Все отчёты →</Link>
            <Link to={`/months/${latestClosed.id}`}>Отчёт месяца в предыдущем интерфейсе →</Link>
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
        <div className={styles.homeGrid}>
          <CompositionOverTime
            assetClasses={compositionReady ? (compositionQuery.data?.asset_classes ?? []) : []}
            points={compositionReady ? (compositionQuery.data?.points ?? []) : []}
            ready={compositionReady}
            retry={() => void compositionQuery.refetch()}
          />
          <CurrentAllocation
            assetClasses={comparisonReady ? (comparison?.asset_classes ?? []) : []}
            comparison={comparison}
            filter={filter}
            onPickClass={pickClass}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
            retryRisk={() => void riskQuery.refetch()}
            risk={riskReady ? riskQuery.data : undefined}
            riskReady={riskReady}
          />
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
          <ChangeBlock
            comparison={comparison}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <LinkedPairsBlock
            accounts={accountsQuery.data ?? []}
            comparison={comparison}
            comparisonReady={comparisonReady}
            debts={debtsReady ? (debtsQuery.data ?? []) : []}
            pairs={pairs}
            ready={pairsReady}
            retry={() =>
              void Promise.all([
                dashboardQuery.refetch(),
                debtsQuery.refetch(),
                accountsQuery.refetch(),
              ])
            }
          />
          <PerformanceBlock
            attribution={attributionReady ? (attributionQuery.data ?? null) : null}
            attributionReady={attributionReady}
            pairEnd={pairEnd}
            pairStart={pairStart}
            retry={() =>
              void Promise.all([
                attributionQuery.refetch(),
                xirrQuery.refetch(),
                twrrQuery.refetch(),
              ])
            }
            twrr={twrrReady ? (twrrQuery.data ?? null) : null}
            twrrReady={twrrReady}
            xirr={xirrReady ? (xirrQuery.data ?? null) : null}
            xirrReady={xirrReady}
          />
          {propertiesQuery.isError ||
          (propertiesReady && (propertiesQuery.data?.length ?? 0) > 0) ? (
            <PropertyBlock
              mortgage={mortgage}
              properties={propertiesReady ? (propertiesQuery.data ?? []) : []}
              ready={propertiesReady}
              retry={() => void propertiesQuery.refetch()}
            />
          ) : null}
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
          <p className={styles.subtitle}>Ликвидный капитал, его состав, счета и доходность.</p>
          <p className={capitalStyles.backLink}>
            <Link to="/v2">← Мои финансы</Link>
          </p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2Shell>
  );
}
