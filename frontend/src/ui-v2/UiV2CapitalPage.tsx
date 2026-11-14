import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { listAccounts } from "../api/accounts";
import { monthReturnsPath } from "./returns/monthLink";
import { getCapitalComposition, getClosedReportComparison } from "../api/analytics";
import { listCashBalances } from "../api/cash";
import { getDashboard } from "../api/dashboard";
import { listDeposits } from "../api/deposits";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { listPositions } from "../api/positions";
import { listProperties } from "../api/properties";
import type { RiskAllocationResponse } from "../api/riskAllocation";
import { getRiskAllocation } from "../api/riskAllocation";
import type {
  CapitalChangeComponent,
  CapitalChangeHint,
  CapitalCompositionPoint,
  CapitalFlowBreakdown,
  ClosedReportComparison,
  DashboardMortgage,
  PortfolioSourceCoverage,
  PropertySnapshot,
} from "../api/types";
import {
  CapitalCompositionChart,
  type CapitalCompositionMode,
} from "../components/charts/CapitalCompositionChart";
import { MissingAccountNames, PortfolioCoverageNote } from "../components/PortfolioCoverageNote";
import { HelpTip } from "../components/ui";
import { formatMonth, formatPercent } from "../lib/format";
import { ASSET_CLASS_LABELS, unsupportedMetricReason } from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import { CLASS_COLORS } from "./assetClasses";
import { ClassAllocation, Limits } from "./CapitalAllocationSheet";
import { type BridgeStep, CapitalBridgeChart } from "./CapitalBridgeChart";
import { CapitalDraftValuation } from "./CapitalDraftValuation";
import { ClosedReportTitle } from "./ClosedReportTitle";
import {
  buildHoldingRows,
  filterHoldingRows,
  type HoldingFilter,
  type HoldingRow,
  holdingContextLabel,
  holdingReturnsNavigation,
  isRiskAssetClass,
  rankedNonzeroHoldings,
  UNASSIGNED_CASH_KEY,
} from "./capitalHoldings";
import { selectNewestDraftAfterLatestClosed, sortReportingMonths } from "./monthSelection";
import sheet from "./ReportSheet.module.css";
import capitalStyles from "./UiV2Capital.module.css";
import { UiV2Shell } from "./UiV2Shell";
import { isQueryReady, UiV2Loading, UiV2Notice, UiV2WidgetState } from "./UiV2StateBlocks";
import { UiV2Tabs } from "./UiV2Tabs";
import { moneyText as money, moneyTone } from "./valueFormat";
import { wholeMoneyText as whole, wholeMoneyDeltaText as wholeDelta } from "./wholeMoney";

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

function remainingPositions(count: number): string {
  const form = new Intl.PluralRules("ru").select(count);
  return `ещё ${count} ${form === "one" ? "позиция" : form === "few" ? "позиции" : "позиций"}`;
}

const MONTHS_DATIVE = [
  "январю",
  "февралю",
  "марту",
  "апрелю",
  "маю",
  "июню",
  "июлю",
  "августу",
  "сентябрю",
  "октябрю",
  "ноябрю",
  "декабрю",
];

/** "к июню 2031": the month the change is measured against. */
function toMonthText(year: number, month: number): string {
  const name = MONTHS_DATIVE[month - 1];
  return name ? `${name} ${year}` : formatMonth(year, month);
}

/** Backend coverage that is not a complete known total (missing snapshot or pending source). */
function isIncomplete(coverage: PortfolioSourceCoverage | null | undefined): boolean {
  return (
    coverage != null &&
    (coverage.status !== "complete" ||
      coverage.source_account_financial_coverage?.status === "partial")
  );
}

function SheetSection({
  actions,
  children,
  eyebrow,
  help,
  id,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  eyebrow: string;
  help?: ReactNode;
  id: string;
  title: string;
}) {
  return (
    <section aria-labelledby={id} className={sheet.section} data-testid={`capital-panel-${id}`}>
      <div className={sheet.sectionHead}>
        <div>
          <p className={sheet.eyebrow}>{eyebrow}</p>
          <h2 id={id}>
            {title}
            {help}
          </h2>
        </div>
        {actions ? <div className={sheet.sectionActions}>{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** Hero: liquid capital, its change and the two subtotals it is made of. */
function Hero({
  comparison,
  ready,
  loading,
  retry,
}: {
  comparison: ClosedReportComparison | undefined;
  ready: boolean;
  loading: boolean;
  retry: () => void;
}) {
  const current = ready ? (comparison?.current ?? null) : null;
  const unavailable = current?.portfolio_source_coverage?.status === "unavailable";
  const delta = ready ? (comparison?.liquid_capital_net_delta ?? null) : null;
  const deltaKnown =
    delta !== null &&
    comparison?.previous != null &&
    !unavailable &&
    comparison.liquid_capital_net_delta_coverage?.status !== "unavailable";
  const tone = moneyTone(delta);
  // The change also depends on the previous report. Its incompleteness is said once,
  // naming both reports when both are incomplete.
  const currentIncomplete = isIncomplete(current?.portfolio_source_coverage);
  const previousIncomplete =
    isIncomplete(comparison?.previous?.portfolio_source_coverage) ||
    (!currentIncomplete && isIncomplete(comparison?.liquid_capital_net_delta_coverage));
  const deltaPartial = deltaKnown && previousIncomplete;
  const previousCoverage = comparison?.previous?.portfolio_source_coverage;
  return (
    <section aria-label="Главные показатели капитала" className={capitalStyles.hero}>
      <p className={sheet.eyebrow}>
        Ликвидный капитал
        <HelpTip label="Как считается капитал">
          Ликвидные активы минус включённые обязательства = ликвидный капитал. Жильё и ипотека в
          ликвидный капитал не входят.
        </HelpTip>
      </p>
      {current === null ? (
        loading ? (
          <UiV2Loading label="Загружаем показатели…" />
        ) : (
          <UiV2WidgetState retry={ready ? undefined : retry} />
        )
      ) : (
        <>
          <p
            className={sheet.hero}
            data-testid="capital-net"
            title={unavailable ? undefined : money(current.liquid_capital_net)}
          >
            {unavailable ? "—" : whole(current.liquid_capital_net)}
          </p>
          {deltaKnown && comparison?.previous ? (
            <p className={capitalStyles.deltaRow}>
              <span className={sheet.delta} data-tone={tone}>
                {tone === "positive" ? "▲ " : tone === "negative" ? "▼ " : ""}
                {wholeDelta(delta)}
              </span>
              <span className={sheet.muted}>
                к {toMonthText(comparison.previous.year, comparison.previous.month)}
              </span>
            </p>
          ) : null}
          {deltaPartial && comparison?.previous ? (
            <p className={sheet.gapNote} data-testid="capital-delta-partial">
              {current && currentIncomplete
                ? `Изменение посчитано по известным записям: не хватает данных в отчётах за ${formatMonth(current.year, current.month)} и ${formatMonth(comparison.previous.year, comparison.previous.month)}`
                : `Изменение посчитано по известным записям: в отчёте за ${formatMonth(comparison.previous.year, comparison.previous.month)} не хватает данных`}
              {previousCoverage?.reason_codes.includes("active_account_snapshot_missing") ? (
                <>
                  ;{" "}
                  {previousCoverage.missing_account_ids.length > 1
                    ? "нет снимков счетов"
                    : "нет снимка счёта"}
                  <MissingAccountNames ids={previousCoverage.missing_account_ids} />
                </>
              ) : null}
              .
            </p>
          ) : null}
          <PortfolioCoverageNote coverage={current.portfolio_source_coverage} month={current} />
          <dl className={capitalStyles.facts}>
            <div>
              <dt>Ликвидные активы</dt>
              <dd className={sheet.amount} data-testid="capital-assets">
                {whole(current.liquid_assets_total)}
              </dd>
            </div>
            <div>
              <dt>Включённые обязательства</dt>
              <dd className={sheet.amount} data-testid="capital-debts">
                −{whole(current.included_debts)}
              </dd>
            </div>
          </dl>
        </>
      )}
    </section>
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
    <div
      className={capitalStyles.composition}
      data-testid="capital-panel-capital-composition-title"
    >
      <div className={capitalStyles.compositionHead}>
        <h2 className={sheet.visuallyHidden} id="capital-composition-title">
          Состав во времени
        </h2>
        <p className={sheet.eyebrow} aria-hidden="true">
          Состав по закрытым отчётам
        </p>
        <div className={sheet.sectionActions}>
          <fieldset className={sheet.segmented} aria-label="Показатель состава">
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
          <fieldset className={sheet.segmented} aria-label="Период состава">
            {([3, 12, "all"] as const).map((value) => (
              <button
                aria-pressed={window === value}
                key={value}
                onClick={() => setWindow(value)}
                type="button"
              >
                {value === 3 ? "3 мес" : value === 12 ? "12 мес" : "Всё"}
              </button>
            ))}
          </fieldset>
        </div>
      </div>
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : visible.length === 0 ? (
        <UiV2WidgetState title="История появится после закрытия первого отчёта" />
      ) : (
        <div data-point-count={visible.length} data-testid="capital-composition">
          <CapitalCompositionChart
            assetClasses={assetClasses}
            classColors={CLASS_COLORS}
            height={300}
            mode={mode}
            points={visible}
          />
        </div>
      )}
    </div>
  );
}

function CapitalChange({ comparison }: { comparison: ClosedReportComparison | undefined }) {
  const change = comparison?.capital_change;
  if (
    !comparison?.current ||
    !change ||
    change.reporting_month_id !== comparison?.current?.reporting_month_id ||
    change.previous_reporting_month_id !== (comparison?.previous?.reporting_month_id ?? null)
  )
    return null;
  const flow = change.flow_breakdown;
  if (flow) {
    return (
      <CapitalFlowChange
        eyebrow={formatMonth(comparison.current.year, comparison.current.month)}
        flow={flow}
        hints={change.context_hints ?? []}
      />
    );
  }
  const breakdown = change.breakdown;
  return (
    <SheetSection
      eyebrow={formatMonth(comparison.current.year, comparison.current.month)}
      help={
        breakdown ? (
          <HelpTip label="Как читать изменение капитала">
            Показаны известные суммы. Прочие изменения — изменение включённых обязательств.
            Неподтверждённые движения и недоступные результаты остаются в отдельном необъяснённом
            остатке.
          </HelpTip>
        ) : undefined
      }
      id="capital-change-title"
      title="Как изменился капитал за месяц"
    >
      {breakdown ? (
        <>
          <CapitalBridgeChart
            steps={[
              { label: "Начало месяца", amount: breakdown.start, kind: "level" },
              {
                label: "Внешние внесения и изъятия",
                amount: breakdown.external_net,
                kind: "change",
              },
              {
                label: "Инвестиционный результат",
                amount: breakdown.investment_result,
                kind: "change",
              },
              { label: "Прочие изменения", amount: breakdown.other_changes, kind: "change" },
              {
                label: "Необъяснённый остаток",
                amount: breakdown.unexplained,
                kind: "change",
                testId: "capital-unexplained",
              },
              { label: "Конец месяца", amount: breakdown.end, kind: "level" },
            ]}
          />
          {change.reason_codes.includes("capital_investment_source_estimate") ? (
            <p className={sheet.gapNote}>
              Инвестиционный результат включает оценку по выпискам с совпадающими остатками.
            </p>
          ) : null}
        </>
      ) : (
        <p className={sheet.muted}>
          Для объяснения нужны данные на конец этого и предыдущего календарного месяца.
        </p>
      )}
    </SheetSection>
  );
}

/** A partial component shows its proven part; a fully unknown one stays in the residual. */
function componentStep(label: string, component: CapitalChangeComponent): BridgeStep | null {
  if (component.amount) return { label, amount: component.amount, kind: "change" };
  if (component.items.some((item) => item.amount !== null))
    return {
      label: `${label} (известная часть)`,
      amount: component.known_subtotal,
      kind: "change",
    };
  return null;
}

function CapitalFlowChange({
  eyebrow,
  flow,
  hints,
}: {
  eyebrow: string;
  flow: CapitalFlowBreakdown;
  hints: CapitalChangeHint[];
}) {
  const market = componentStep("Рынок: брокерский и ИИС", flow.investment_market_change);
  const valuation = flow.investment_valuation_difference
    ? componentStep("Разница оценки капитала и выписок", flow.investment_valuation_difference)
    : null;
  const gold = componentStep("Переоценка золота", flow.physical_gold_revaluation);
  const unknown = [
    flow.investment_market_change.amount ? null : "изменение стоимости брокерского счёта и ИИС",
    flow.investment_valuation_difference && !flow.investment_valuation_difference.amount
      ? "разница оценки капитала и выписок"
      : null,
    flow.physical_gold_revaluation.amount || flow.physical_gold_revaluation.items.length === 0
      ? null
      : "переоценка золота",
  ].filter((text): text is string => text !== null);
  // One line per distinct next step; the same advice for two accounts is shown once.
  const marketHints = [
    ...new Set(
      flow.investment_market_change.items
        .filter((item) => item.amount === null && item.unavailable_hint)
        .map((item) => item.unavailable_hint as string),
    ),
  ];
  const steps: BridgeStep[] = [
    { label: "Начало месяца", amount: flow.start, kind: "level" },
    { label: "Доходы минус расходы", amount: flow.monthly_flow, kind: "change" },
    ...(market ? [market] : []),
    ...(valuation ? [valuation] : []),
    ...(gold ? [gold] : []),
    {
      label: "Необъяснённый остаток",
      amount: flow.unexplained,
      kind: "change",
      testId: "capital-unexplained",
    },
    { label: "Конец месяца", amount: flow.end, kind: "level" },
  ];
  return (
    <SheetSection
      eyebrow={eyebrow}
      help={
        <HelpTip label="Как читать изменение капитала">
          Доходы минус расходы — по записям месяца, до откладывания: откладывание остаётся внутри
          капитала. Проценты, купоны и дивиденды входят сюда один раз. Покупка по кредитке — это
          расход, а погашение кредитки со своего счёта не меняет капитал. Всё, что не подтверждено,
          остаётся в необъяснённом остатке. Разница оценки капитала и выписок: капитал считает
          облигации без НКД и не включает мелкие рубли на счетах, а выписка брокера — с ними; это
          разница основы оценки, а не прибыль или убыток.
        </HelpTip>
      }
      id="capital-change-title"
      title="Как изменился капитал за месяц"
    >
      <CapitalBridgeChart steps={steps} />
      {flow.unexplained_hint ? <p className={sheet.gapNote}>{flow.unexplained_hint}</p> : null}
      {unknown.length > 0 ? (
        <p className={sheet.gapNote}>
          Пока не подтверждено и входит в необъяснённый остаток: {unknown.join(", ")}.
        </p>
      ) : null}
      {marketHints.length > 0 ? (
        <ul className={sheet.gapNote} data-testid="capital-market-hints">
          {marketHints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
      {hints.map((hint) => (
        <p className={sheet.gapNote} data-testid="capital-card-hint" key={hint.reason_code}>
          Долг по кредитке вырос на {whole(hint.card_debt_growth)}, а расходов за месяц внесено{" "}
          {whole(hint.recorded_expenses)}. Если это покупки, внесите их в расходы месяца — тогда
          остаток уменьшится.
        </p>
      ))}
    </SheetSection>
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
  return (
    <SheetSection
      eyebrow="Отдельно от ликвидного капитала"
      id="capital-property-title"
      title="Недвижимость"
      help={
        <HelpTip label="Сравнение капитала и ипотеки">
          Недвижимость и ипотека не входят в ликвидный капитал. Положительная разница — капитала
          больше остатка ипотеки, отрицательная — меньше.
        </HelpTip>
      }
    >
      {!ready ? (
        <UiV2WidgetState retry={retry} />
      ) : (
        <div className={capitalStyles.propertyTiles}>
          <div>
            <span>Стоимость недвижимости</span>
            {properties.map((property) => (
              <p key={property.id}>
                <span>{property.name}</span>
                <strong className={sheet.amount} title={money(property.estimated_value)}>
                  {whole(property.estimated_value)}
                </strong>
              </p>
            ))}
          </div>
          <div>
            <span>Остаток ипотеки по отчёту</span>
            <strong
              className={sheet.amount}
              title={mortgage ? money(mortgage.mortgage_balance) : undefined}
            >
              {whole(mortgage?.mortgage_balance)}
            </strong>
          </div>
          <div>
            <span>Покрытие ипотеки капиталом</span>
            <strong className={sheet.amount}>
              {mortgage && isZeroAmount(mortgage.mortgage_balance.amount)
                ? "ипотека закрыта"
                : formatPercent(mortgage?.coverage_pct, { digits: 1 })}
            </strong>
            {mortgage && !isZeroAmount(mortgage.mortgage_balance.amount) ? (
              <small>
                <span>Разница: капитал − ипотека</span>{" "}
                <span data-tone={moneyTone(mortgage.gap)}>{wholeDelta(mortgage.gap)}</span>
              </small>
            ) : null}
          </div>
        </div>
      )}
    </SheetSection>
  );
}

function HoldingsBlock({
  filter,
  monthId,
  resetFilter,
  rows,
  lists,
  risk,
  retryRisk,
}: {
  filter: HoldingFilter;
  monthId: number;
  resetFilter: () => void;
  rows: HoldingRow[];
  lists: Record<"cash" | "deposit" | "position", { ready: boolean; retry: () => void }>;
  risk: RiskAllocationResponse | undefined;
  retryRisk: () => void;
}) {
  const location = useLocation();
  const [mode, setMode] = useState<"account" | "risk_class">(
    filter?.kind === "risk_class" ? "risk_class" : "account",
  );
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const visible = rankedNonzeroHoldings(
    filterHoldingRows(rows, filter).filter((row) => lists[row.kind].ready),
  );
  const metric = mode === "account" ? risk?.allocation_by_account : risk?.allocation_by_asset_class;
  const unsupported = metric
    ? unsupportedMetricReason(metric.support.status, metric.support.reason_codes)
    : null;
  const groups = !unsupported
    ? (metric?.items ?? [])
        .filter((item) => !isZeroAmount(item.amount.amount))
        .map((item) => ({
          key: item.key,
          label:
            mode === "account"
              ? item.key === UNASSIGNED_CASH_KEY
                ? "Деньги без привязки к счёту"
                : item.label
              : (ASSET_CLASS_LABELS[item.key] ?? item.label),
          amount: item.amount,
          share: item.share_pct,
          rows: filterHoldingRows(visible, { kind: mode, value: item.key, label: item.label }),
        }))
    : [];
  const assigned = new Set(groups.flatMap((group) => group.rows.map((row) => row.key)));
  const other = visible.filter((row) => !assigned.has(row.key));
  const allGroups = [
    ...groups,
    ...(other.length
      ? [
          {
            key: "other",
            label: "Остальные строки · вне распределения",
            amount: null,
            share: null,
            rows: other,
          },
        ]
      : []),
  ];
  const top = risk?.top_positions;
  const topReason = top
    ? unsupportedMetricReason(top.support.status, top.support.reason_codes)
    : null;
  return (
    <SheetSection
      actions={<Link to={`/v2/close?month=${monthId}`}>Данные отчётного месяца →</Link>}
      eyebrow="Структура"
      id="capital-holdings-title"
      title="Счета и позиции"
    >
      <div className={capitalStyles.filterBar}>
        <fieldset className={capitalStyles.groupSwitch} aria-label="Группировка позиций">
          <button
            type="button"
            aria-pressed={mode === "account"}
            onClick={() => setMode("account")}
          >
            По счетам
          </button>
          <button
            type="button"
            aria-pressed={mode === "risk_class"}
            onClick={() => setMode("risk_class")}
          >
            По классам
          </button>
        </fieldset>
        {filter ? (
          <>
            <span>Фильтр: {filter.label}</span>
            <button onClick={resetFilter} type="button">
              Сбросить
            </button>
          </>
        ) : null}
      </div>
      {!risk ? (
        <UiV2WidgetState retry={retryRisk} />
      ) : unsupported ? (
        <UiV2WidgetState title={unsupported} />
      ) : null}
      {Object.entries(lists)
        .filter(([, list]) => !list.ready)
        .map(([kind, list]) => (
          <div key={kind}>
            <h3>{kind === "position" ? "Позиции" : kind === "cash" ? "Деньги" : "Вклады"}</h3>
            <UiV2WidgetState retry={list.retry} />
          </div>
        ))}
      <div className={capitalStyles.holdingGroups}>
        {allGroups.map((group, index) => (
          <details
            className={capitalStyles.holdingGroup}
            data-testid="capital-holding-group"
            key={`${mode}:${group.key}`}
            open={filter ? group.rows.length > 0 : index === 0}
          >
            <summary
              className={capitalStyles.accountSummary}
              data-testid={
                mode === "account" && group.key !== "other"
                  ? `capital-bucket-${group.key}`
                  : undefined
              }
            >
              <strong>{group.label}</strong>
              <span className={sheet.amount} title={group.amount ? money(group.amount) : undefined}>
                {group.amount ? whole(group.amount) : "—"}
              </span>
              <span className={sheet.share}>
                {formatPercent(group.share, { digits: 1, share: true })}
              </span>
            </summary>
            <ul className={capitalStyles.holdingList}>
              {(expanded[`${mode}:${group.key}`] ? group.rows : group.rows.slice(0, 3)).map(
                (row) => {
                  const backParams = new URLSearchParams(location.search);
                  const returnFilter =
                    filter ??
                    (group.key === "other"
                      ? null
                      : { kind: mode, value: group.key, label: group.label });
                  if (returnFilter) {
                    backParams.set("holding_kind", returnFilter.kind);
                    backParams.set("holding_value", returnFilter.value);
                    backParams.set("holding_label", returnFilter.label.slice(0, 80));
                  } else
                    for (const key of ["holding_kind", "holding_value", "holding_label"])
                      backParams.delete(key);
                  const target = holdingReturnsNavigation(
                    row,
                    `${location.pathname}${backParams.size ? `?${backParams}` : ""}`,
                  );
                  return (
                    <li
                      className={capitalStyles.holdingRow}
                      data-included={row.includeInCapital ? "true" : "false"}
                      data-testid={`capital-holding-${row.key}`}
                      key={row.key}
                    >
                      <div className={capitalStyles.holdingMain}>
                        {target.href ? (
                          <Link className={capitalStyles.holdingName} to={target.href}>
                            {row.name}
                          </Link>
                        ) : (
                          <span
                            className={capitalStyles.holdingName}
                            title={target.reason ?? undefined}
                          >
                            {row.name}
                          </span>
                        )}
                        <span className={capitalStyles.holdingMeta}>
                          {holdingContextLabel(row)}
                          {row.name === "Без названия" && row.isin ? ` · ${row.isin}` : ""}
                          {(mode === "risk_class" || group.key === "other") && row.accountName
                            ? ` · ${row.accountName}`
                            : ""}
                        </span>
                        {!row.includeInCapital ? (
                          <span className={capitalStyles.holdingMeta}>
                            не входит в ликвидный капитал
                          </span>
                        ) : null}
                      </div>
                      <strong
                        className={`${sheet.amount} ${capitalStyles.holdingAmount}`}
                        title={money(row.amount)}
                      >
                        {whole(row.amount)}
                      </strong>
                    </li>
                  );
                },
              )}
            </ul>
            {group.rows.length > 3 ? (
              <button
                className={capitalStyles.moreHoldings}
                type="button"
                onClick={() =>
                  setExpanded((old) => ({
                    ...old,
                    [`${mode}:${group.key}`]: !old[`${mode}:${group.key}`],
                  }))
                }
              >
                {expanded[`${mode}:${group.key}`]
                  ? "Свернуть"
                  : remainingPositions(group.rows.length - 3)}
              </button>
            ) : null}
          </details>
        ))}
      </div>
      {visible.length === 0 && Object.values(lists).every((list) => list.ready) ? (
        <p className={sheet.muted}>
          {filter ? "В фильтре нет строк." : "В закрытом отчёте нет строк капитала."}
        </p>
      ) : null}
      {metric && !unsupported ? (
        <Limits
          metric={{
            ...metric,
            support: {
              ...metric.support,
              reason_codes: metric.support.reason_codes.filter(
                (reason) => mode !== "account" || reason !== "cash_not_account_linked",
              ),
            },
          }}
          title={mode === "account" ? "По счетам" : "По классам активов"}
        />
      ) : null}
      <p className={sheet.gapNote} data-testid="capital-top-summary">
        Крупнейшие позиции:{" "}
        {top && !topReason ? (
          <>
            топ-{top.top_n} — <span title={money(top.top_amount)}>{whole(top.top_amount)}</span> ·{" "}
            {formatPercent(top.top_share_pct, { digits: 1, share: true })}
          </>
        ) : (
          (topReason ?? "Данные временно недоступны")
        )}
      </p>
    </SheetSection>
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
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const { latestClosed, newestDraft: newerDraft } = selectNewestDraftAfterLatestClosed(months);
  const closedId = latestClosed?.id ?? null;
  const closed = closedId !== null;
  const previousClosedId = months.filter((month) => month.status === "closed")[1]?.id ?? null;

  const comparisonQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.closedReportComparisonBasic,
    queryFn: ({ signal }) => getClosedReportComparison(signal, false),
  });
  const capitalChangeQuery = useQuery({
    enabled:
      closed &&
      isQueryReady(monthsQuery) &&
      isQueryReady(comparisonQuery) &&
      comparisonQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
      comparisonQuery.data.current?.reporting_month_id === closedId &&
      (comparisonQuery.data.previous?.reporting_month_id ?? null) === previousClosedId,
    queryKey: queryKeys.closedReportComparison,
    queryFn: ({ signal }) => getClosedReportComparison(signal),
  });
  const compositionQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
  });
  const riskQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.riskAllocation(closedId, 5),
    queryFn: ({ signal }) => getRiskAllocation(closedId as number, 5, "v1", signal),
  });
  const dashboardQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.dashboardBasic(closedId),
    queryFn: ({ signal }) => getDashboard(closedId as number, signal, false),
  });
  const cashQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.cashBalances(closedId),
    queryFn: ({ signal }) => listCashBalances(closedId as number, signal),
  });
  const depositsQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.deposits(closedId),
    queryFn: ({ signal }) => listDeposits(closedId as number, signal),
  });
  const positionsQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.positions(closedId),
    queryFn: ({ signal }) => listPositions(closedId as number, undefined, signal),
  });
  const propertiesQuery = useQuery({
    enabled: closed,
    queryKey: queryKeys.properties(closedId),
    queryFn: ({ signal }) => listProperties(closedId as number, signal),
  });
  const accountsQuery = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const instrumentsQuery = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
  });

  const monthsReady = isQueryReady(monthsQuery);
  const comparisonReady =
    isQueryReady(comparisonQuery) &&
    comparisonQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
    comparisonQuery.data.current?.reporting_month_id === closedId &&
    (comparisonQuery.data.previous?.reporting_month_id ?? null) === previousClosedId;
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
  const resetFilter = () => setFilter(null);

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2WidgetState title="Не удалось загрузить" retry={() => void monthsQuery.refetch()} />
    );
  } else if (!monthsReady) {
    content = <UiV2Loading label="Проверяем последний закрытый отчёт…" />;
  } else if (!latestClosed) {
    content = (
      <UiV2Notice title="Закрой первый отчёт">
        <Link to="/v2/close">Закрой первый месяц →</Link>
      </UiV2Notice>
    );
  } else {
    const mortgage = dashboardReady ? (dashboardQuery.data?.mortgage ?? null) : null;
    const risk = riskReady ? riskQuery.data : undefined;
    content = (
      <div className={sheet.sheet}>
        <section
          aria-label="Капитал и его состав"
          className={`${sheet.section} ${capitalStyles.top}`}
        >
          <Hero
            comparison={comparison}
            loading={comparisonQuery.isPending || comparisonQuery.isFetching}
            ready={comparisonReady}
            retry={() => void comparisonQuery.refetch()}
          />
          <CompositionOverTime
            assetClasses={compositionReady ? (compositionQuery.data?.asset_classes ?? []) : []}
            points={compositionReady ? (compositionQuery.data?.points ?? []) : []}
            ready={compositionReady}
            retry={() => void compositionQuery.refetch()}
          />
        </section>
        {accountsReady ? (
          <CapitalDraftValuation months={months} accounts={accountsQuery.data ?? []} />
        ) : null}
        <CapitalChange
          comparison={
            comparisonReady &&
            isQueryReady(capitalChangeQuery) &&
            capitalChangeQuery.data?.comparison_basis === "latest_closed_to_previous_closed" &&
            capitalChangeQuery.data.current?.reporting_month_id === closedId &&
            (capitalChangeQuery.data.previous?.reporting_month_id ?? null) === previousClosedId
              ? capitalChangeQuery.data
              : undefined
          }
        />
        <SheetSection
          eyebrow="Структура · ликвидные активы"
          id="capital-allocation-title"
          title="По классам активов"
        >
          {!riskReady ? (
            <UiV2WidgetState retry={() => void riskQuery.refetch()} />
          ) : risk?.allocation_by_asset_class.support.status === "supported" &&
            risk.allocation_by_asset_class.items.every((item) =>
              isZeroAmount(item.amount.amount),
            ) ? (
            <p className={sheet.muted}>Ненулевых строк нет.</p>
          ) : (
            <ClassAllocation
              metric={
                risk
                  ? {
                      ...risk.allocation_by_asset_class,
                      items: risk.allocation_by_asset_class.items.filter(
                        (item) => !isZeroAmount(item.amount.amount),
                      ),
                    }
                  : undefined
              }
              onSelect={pickRiskClass}
              selected={filter?.kind === "risk_class" ? filter.value : null}
            />
          )}
        </SheetSection>
        <HoldingsBlock
          filter={filter}
          risk={risk}
          retryRisk={() => void riskQuery.refetch()}
          lists={{
            cash: { ready: cashReady, retry: () => void cashQuery.refetch() },
            deposit: { ready: depositsReady, retry: () => void depositsQuery.refetch() },
            position: { ready: positionsReady, retry: () => void positionsQuery.refetch() },
          }}
          monthId={latestClosed.id}
          resetFilter={resetFilter}
          rows={holdingRows}
        />
        {propertiesQuery.isError || (propertiesReady && (propertiesQuery.data?.length ?? 0) > 0) ? (
          <PropertyBlock
            mortgage={mortgage}
            properties={propertiesReady ? (propertiesQuery.data ?? []) : []}
            ready={propertiesReady}
            retry={() => void propertiesQuery.refetch()}
          />
        ) : null}
      </div>
    );
  }

  return (
    <UiV2Shell
      active="capital"
      busy={!monthsReady}
      header={
        <>
          <ClosedReportTitle month={latestClosed} title="Капитал" />
          {latestClosed ? (
            <Link to={monthReturnsPath(latestClosed)}>Доходность за месяц →</Link>
          ) : null}
          <UiV2Tabs
            label="Капитал"
            tabs={[
              { label: "Обзор", to: "/v2/capital", active: true },
              { label: "Распределение", to: "/v2/capital/allocation", active: false },
            ]}
          />
          {newerDraft ? (
            <p className={sheet.draftNote} data-testid="capital-draft-note">
              {formatMonth(newerDraft.year, newerDraft.month)} ещё не закрыт — картина остаётся по
              последнему закрытому отчёту. <Link to="/v2">Черновик месяца в «Мои финансы» →</Link>
            </p>
          ) : null}
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
