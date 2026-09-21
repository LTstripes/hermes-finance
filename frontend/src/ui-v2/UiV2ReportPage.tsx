import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { listAccounts } from "../api/accounts";
import { getCapitalComposition } from "../api/analytics";
import { listCashBalances } from "../api/cash";
import { listDeposits } from "../api/deposits";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { listPositions } from "../api/positions";
import { getRiskAllocation, type RiskAllocationResponse } from "../api/riskAllocation";
import type { CapitalCompositionPoint, ReportingMonth } from "../api/types";
import {
  CapitalCompositionChart,
  type CapitalCompositionMode,
} from "../components/charts/CapitalCompositionChart";
import { buildCapitalCompositionSeries } from "../lib/capitalComposition";
import { formatMoney, formatMonth, formatPercent } from "../lib/format";
import { SOURCE_LABELS } from "../lib/labels";
import { unsupportedMetricReason } from "../lib/riskSupportCopy";
import { queryKeys } from "../queryClient";
import { CLASS_COLORS, classMeta } from "./assetClasses";
import { buildHoldingRows, holdingContextLabel, type HoldingRow } from "./capitalHoldings";
import { latestClosedMonth } from "./monthSelection";
import {
  contextualHistoryWindow,
  CURRENT_METHODOLOGY_CAVEAT,
  HISTORY_WINDOWS,
  historyWindowLabel,
  type HistoryWindowSize,
  NO_HISTORICAL_CHANGE_TEXT,
  REPORTS_PATH,
  resolveReportTarget,
  seriesPosition,
  type SeriesPosition,
} from "./reportsArchive";
import {
  isQueryReady,
  UiV2Loading,
  UiV2Notice,
  UiV2ReportContext,
  UiV2WidgetState,
} from "./UiV2StateBlocks";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Shell } from "./UiV2Shell";
import { UNKNOWN_SOURCE_LABEL } from "./uiV2Copy";
import styles from "./UiV2Page.module.css";
import reportStyles from "./UiV2Reports.module.css";
import { moneyText as money } from "./valueFormat";

function isZeroAmount(amount: string): boolean {
  return /^-?0(?:\.0+)?$/.test(amount.trim());
}

function Panel(props: Omit<Parameters<typeof UiV2Panel>[0], "testIdPrefix">) {
  return <UiV2Panel {...props} testIdPrefix="report-panel" />;
}

function ReportValues({ point }: { point: CapitalCompositionPoint }) {
  const metrics: Array<{ detail: string; eyebrow: string; primary?: boolean; testId: string }> = [
    {
      detail: "Активы за вычетом включённых обязательств",
      eyebrow: "Ликвидный капитал",
      primary: true,
      testId: "report-net",
    },
    {
      detail: "Деньги, депозиты, ценные бумаги и прочее ликвидное",
      eyebrow: "Ликвидные активы",
      testId: "report-assets",
    },
    {
      detail: "Вычитаются из активов, не входят в состав",
      eyebrow: "Включённые обязательства",
      testId: "report-debts",
    },
  ];
  const values: Record<string, string> = {
    "report-assets": money(point.liquid_assets_total),
    "report-debts": `− ${money(point.included_debts)}`,
    "report-net": money(point.liquid_capital_net),
  };
  return (
    <>
      <section aria-label="Значения исторического отчёта" className={styles.metrics}>
        {metrics.map((metric) => (
          <article
            className={`${styles.metric} ${metric.primary ? styles.metricPrimary : ""}`}
            key={metric.testId}
          >
            <p className={styles.eyebrow}>{metric.eyebrow}</p>
            <p className={styles.metricValue} data-testid={metric.testId}>
              {values[metric.testId]}
            </p>
            <p className={styles.metricDetail}>{metric.detail}</p>
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

function CompositionBlock({
  assetClasses,
  point,
}: {
  assetClasses: string[];
  point: CapitalCompositionPoint;
}) {
  const [mode, setMode] = useState<CapitalCompositionMode>("amount");
  const datum =
    assetClasses.length > 0 ? buildCapitalCompositionSeries([point], assetClasses)[0] : null;
  const positive = assetClasses.some((assetClass) => {
    const amount = datum?.amounts[assetClass];
    return amount != null && !isZeroAmount(amount);
  });
  return (
    <Panel
      action={
        <fieldset className={styles.segmented} aria-label="Показатель состава отчёта">
          <button aria-pressed={mode === "amount"} onClick={() => setMode("amount")} type="button">
            Суммы
          </button>
          <button aria-pressed={mode === "share"} onClick={() => setMode("share")} type="button">
            Доли
          </button>
        </fieldset>
      }
      eyebrow="Состав закрытого отчёта"
      id="report-composition-title"
      title="Состав отчёта"
    >
      {!datum ? (
        <UiV2WidgetState />
      ) : (
        <>
          <ul className={reportStyles.compositionList} data-testid="report-composition">
            {assetClasses.map((assetClass) => {
              const amount = datum.amounts[assetClass] ?? "0.00";
              const share = datum.shares[assetClass] ?? null;
              return (
                <li data-testid={`report-class-${assetClass}`} key={assetClass}>
                  <span
                    aria-hidden="true"
                    className={reportStyles.classDot}
                    style={{ background: classMeta(assetClass).color }}
                  />
                  <span className={reportStyles.className}>{classMeta(assetClass).label}</span>
                  <strong>
                    {mode === "amount"
                      ? formatMoney(amount, { currency: "₽" })
                      : share === null
                        ? "—"
                        : formatPercent(share, { digits: 1 })}
                  </strong>
                </li>
              );
            })}
          </ul>
          <dl className={styles.netSummary}>
            <div>
              <dt>Ликвидные активы</dt>
              <dd>{money(point.liquid_assets_total)}</dd>
            </div>
            <div className={styles.deduction}>
              <dt>Включённые обязательства</dt>
              <dd>− {money(point.included_debts)}</dd>
            </div>
            <div>
              <dt>Ликвидный капитал</dt>
              <dd>{money(point.liquid_capital_net)}</dd>
            </div>
          </dl>
          {positive ? null : (
            <p className={reportStyles.muted} data-testid="report-composition-empty">
              В этом отчёте нет положительных ликвидных активов: известные нули остаются нулями, а
              доли не рассчитываются.
            </p>
          )}
          <p className={styles.panelFootnote}>
            Обязательства показаны отдельной строкой вычета и не входят в состав как отрицательная
            доля. Доли считаются от ликвидных активов этого отчёта.
          </p>
        </>
      )}
    </Panel>
  );
}

function NeighbourLink({
  direction,
  point,
}: {
  direction: "previous" | "next";
  point: CapitalCompositionPoint;
}) {
  const label =
    direction === "previous"
      ? `← предыдущий закрытый отчёт: ${formatMonth(point.year, point.month)}`
      : `следующий закрытый отчёт: ${formatMonth(point.year, point.month)} →`;
  return (
    <Link
      className={styles.contextLink}
      data-testid={`report-neighbour-${direction}`}
      to={`${REPORTS_PATH}/${point.reporting_month_id}`}
    >
      {label}
    </Link>
  );
}

function HistoryBlock({
  assetClasses,
  monthId,
  points,
  position,
}: {
  assetClasses: string[];
  monthId: number;
  points: CapitalCompositionPoint[];
  position: SeriesPosition;
}) {
  const [window, setWindow] = useState<HistoryWindowSize>(12);
  const [mode, setMode] = useState<CapitalCompositionMode>("amount");
  const visible = contextualHistoryWindow(points, monthId, window);
  return (
    <Panel
      action={
        <div className={reportStyles.controls}>
          <fieldset className={styles.segmented} aria-label="Показатель истории">
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
          <fieldset className={styles.segmented} aria-label="Период истории">
            {HISTORY_WINDOWS.map((value) => (
              <button
                aria-pressed={window === value}
                key={String(value)}
                onClick={() => setWindow(value)}
                type="button"
              >
                {historyWindowLabel(value)}
              </button>
            ))}
          </fieldset>
        </div>
      }
      eyebrow="Место в истории"
      id="report-history-title"
      title="Отчёт в истории закрытых месяцев"
      wide
    >
      <div
        data-point-count={visible.length}
        data-testid="report-history"
        data-window-first-id={visible[0]?.reporting_month_id}
        data-window-last-id={visible.at(-1)?.reporting_month_id}
      >
        <CapitalCompositionChart
          assetClasses={assetClasses}
          classColors={CLASS_COLORS}
          highlightMonthId={monthId}
          mode={mode}
          points={visible}
        />
      </div>
      <p className={styles.panelFootnote}>
        {window === "all"
          ? `Показаны все закрытые отчёты (${visible.length}).`
          : `Показано ${visible.length} закрытых отчётов — окно заканчивается открытым отчётом.`}{" "}
        Пропуски остаются пропусками; значения не интерполируются. Выделенный отчёт — тот, который
        открыт на этой странице.
      </p>
      <div className={reportStyles.neighbours}>
        {position.previous ? (
          <NeighbourLink direction="previous" point={position.previous} />
        ) : (
          <span className={reportStyles.muted}>Это самый ранний закрытый отчёт.</span>
        )}
        {position.next ? (
          <NeighbourLink direction="next" point={position.next} />
        ) : (
          <span className={reportStyles.muted}>Это самый поздний закрытый отчёт.</span>
        )}
      </div>
    </Panel>
  );
}

function LinkedPairsBlock({ point }: { point: CapitalCompositionPoint }) {
  const pairs = [
    { amount: point.linked_pair_assets, label: "Активы связанных пар" },
    { amount: point.linked_pair_debts, label: "Обязательства связанных пар" },
    { amount: point.linked_pair_net_contribution, label: "Вклад связанных пар" },
  ];
  if (!pairs.some((pair) => !isZeroAmount(pair.amount.amount))) return null;
  return (
    <Panel eyebrow="Контекст" id="report-pairs-title" title="Связанные пары" wide>
      <ul className={reportStyles.pairList} data-testid="report-linked-pairs">
        {pairs.map((pair) => (
          <li key={pair.label}>
            <span className={reportStyles.className}>{pair.label}</span>
            <strong>{money(pair.amount)}</strong>
          </li>
        ))}
      </ul>
      <p className={styles.panelFootnote}>
        Эти суммы уже входят в ликвидные активы и включённые обязательства и повторно не вычитаются.
      </p>
    </Panel>
  );
}

function HoldingsBlock({
  lists,
  rows,
}: {
  lists: Record<HoldingRow["kind"], { ready: boolean; retry: () => void }>;
  rows: HoldingRow[];
}) {
  const sections: Array<{ kind: HoldingRow["kind"]; title: string }> = [
    { kind: "cash", title: "Денежные строки" },
    { kind: "deposit", title: "Вклады" },
    { kind: "position", title: "Позиции" },
  ];
  return (
    <Panel eyebrow="Строки отчёта" id="report-holdings-title" title="Где лежит капитал" wide>
      {sections.map((section) => {
        const list = lists[section.kind];
        const sectionRows = rows.filter((row) => row.kind === section.kind);
        return (
          <div className={reportStyles.subBlock} key={section.kind}>
            <h3>{section.title}</h3>
            {!list.ready ? (
              <UiV2WidgetState retry={list.retry} />
            ) : sectionRows.length === 0 ? (
              <p className={reportStyles.muted}>В закрытом отчёте нет строк этого вида.</p>
            ) : (
              <ul className={reportStyles.holdingList}>
                {sectionRows.map((row) => (
                  <li
                    className={reportStyles.holdingRow}
                    data-included={row.includeInCapital ? "true" : "false"}
                    data-testid={`report-holding-${row.key}`}
                    key={row.key}
                  >
                    <div className={reportStyles.holdingMain}>
                      <span className={reportStyles.holdingName}>{row.name}</span>
                      <span className={reportStyles.holdingMeta}>
                        {holdingContextLabel(row)}
                        {row.accountName === null ? "" : ` · ${row.accountName}`}
                      </span>
                    </div>
                    <strong className={reportStyles.holdingAmount}>{money(row.amount)}</strong>
                    {row.includeInCapital ? null : (
                      <span className={reportStyles.excludedBadge}>
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
        суммы строк. Справочники счетов и инструментов — текущие, поэтому действует оговорка о
        методике.
      </p>
    </Panel>
  );
}

function TopPositionsBlock({
  ready,
  retry,
  risk,
}: {
  ready: boolean;
  retry: () => void;
  risk: RiskAllocationResponse | undefined;
}) {
  const concentration = risk?.top_positions;
  const unsupportedReason =
    risk && concentration
      ? unsupportedMetricReason(concentration.support.status, concentration.support.reason_codes)
      : null;
  return (
    <Panel
      eyebrow="Концентрация"
      hint="Доля позиции считается от ликвидных активов этого отчёта"
      id="report-positions-title"
      title="Топ позиций"
    >
      {!ready || !concentration ? (
        <UiV2WidgetState retry={retry} />
      ) : unsupportedReason ? (
        <p className={reportStyles.muted} data-testid="report-top-positions-unsupported">
          {unsupportedReason}
        </p>
      ) : concentration.items.length === 0 ? (
        <p className={reportStyles.muted}>Нет позиций с положительной оценкой.</p>
      ) : (
        <>
          <ul className={reportStyles.positionList} data-testid="report-top-positions">
            {concentration.items.map((item) => (
              <li key={item.key}>
                <span className={reportStyles.className}>{item.label}</span>
                <strong>{money(item.amount)}</strong>
                <span className={reportStyles.classShare}>
                  {formatPercent(item.share_pct, { digits: 1 })}
                </span>
              </li>
            ))}
          </ul>
          <p className={styles.panelFootnote}>
            Это не оценка риска и не инвестиционная доходность.
          </p>
        </>
      )}
    </Panel>
  );
}

export default function UiV2ReportPage() {
  const params = useParams();
  const requestedId = params.monthId;
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
    refetchOnWindowFocus: true,
  });
  const monthsReady = isQueryReady(monthsQuery);
  const months = monthsQuery.data ?? [];
  const target = useMemo(
    () => (monthsReady ? resolveReportTarget(requestedId, months) : null),
    [months, monthsReady, requestedId],
  );
  const latestClosed: ReportingMonth | null = useMemo(() => latestClosedMonth(months), [months]);
  const targetMonth = target?.month ?? null;
  const targetMonthId = targetMonth?.id ?? null;
  const isOlder = target?.kind === "older" && targetMonthId !== null;

  const compositionQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.capitalComposition,
    queryFn: ({ signal }) => getCapitalComposition(signal),
    refetchOnWindowFocus: true,
  });
  const riskQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.riskAllocation(targetMonthId, 5),
    queryFn: ({ signal }) => getRiskAllocation(targetMonthId as number, 5, "v1", signal),
    refetchOnWindowFocus: true,
  });
  const cashQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.cashBalances(targetMonthId),
    queryFn: ({ signal }) => listCashBalances(targetMonthId as number, signal),
    refetchOnWindowFocus: true,
  });
  const depositsQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.deposits(targetMonthId),
    queryFn: ({ signal }) => listDeposits(targetMonthId as number, signal),
    refetchOnWindowFocus: true,
  });
  const positionsQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.positions(targetMonthId),
    queryFn: ({ signal }) => listPositions(targetMonthId as number, undefined, signal),
    refetchOnWindowFocus: true,
  });
  const accountsQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    refetchOnWindowFocus: true,
  });
  const instrumentsQuery = useQuery({
    enabled: isOlder,
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
    refetchOnWindowFocus: true,
  });

  const compositionReady = isQueryReady(compositionQuery);
  const points = compositionQuery.data?.points ?? [];
  const assetClasses = compositionQuery.data?.asset_classes ?? [];
  const position =
    compositionReady && targetMonthId !== null ? seriesPosition(points, targetMonthId) : null;
  const accountsReady = isQueryReady(accountsQuery);
  const instrumentsReady = isQueryReady(instrumentsQuery);
  const rowsMatchMonth = (rows: Array<{ reporting_month_id: number }> | undefined) =>
    targetMonthId !== null &&
    (rows?.every((row) => row.reporting_month_id === targetMonthId) ?? false);
  const cashReady = accountsReady && isQueryReady(cashQuery) && rowsMatchMonth(cashQuery.data);
  const depositsReady =
    accountsReady && isQueryReady(depositsQuery) && rowsMatchMonth(depositsQuery.data);
  const positionsReady =
    accountsReady &&
    instrumentsReady &&
    isQueryReady(positionsQuery) &&
    rowsMatchMonth(positionsQuery.data);
  const riskReady =
    isQueryReady(riskQuery) &&
    targetMonthId !== null &&
    riskQuery.data?.reporting_month_id === targetMonthId;
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

  useEffect(() => {
    if (target?.kind !== "older") return;
    document.getElementById("report-title")?.focus();
  }, [target?.kind]);

  const v1ReturnPath = targetMonth
    ? `/months/${targetMonth.id}`
    : latestClosed
      ? `/months/${latestClosed.id}`
      : "/v1";

  let content: ReactNode;
  if (monthsQuery.isError) {
    content = (
      <UiV2Notice title="Не удалось загрузить отчёты" retry={() => void monthsQuery.refetch()}>
        Отчёт скрыт, пока список подтверждённых закрытых отчётов не прочитан.
      </UiV2Notice>
    );
  } else if (!monthsReady || !target) {
    content = <UiV2Loading label="Проверяем отчёт…" />;
  } else if (target.kind === "malformed" || target.kind === "missing") {
    content = (
      <UiV2Notice title="Отчёт не найден">
        Такого отчёта в архиве нет. <Link to={REPORTS_PATH}>Все отчёты →</Link> ·{" "}
        <Link to="/v2">Мои финансы →</Link>
      </UiV2Notice>
    );
  } else if (target.kind === "draft") {
    content = (
      <UiV2Notice title="Этот месяц ещё не закрыт">
        {formatMonth(target.month.year, target.month.month)} — черновик, не исторический отчёт.{" "}
        <Link to="/v2">Мои финансы →</Link> ·{" "}
        <Link to={`/months/${target.month.id}/close`}>Закрытие месяца →</Link>
      </UiV2Notice>
    );
  } else if (target.kind === "current") {
    content = (
      <UiV2Notice title="Это текущий отчёт">
        {formatMonth(target.month.year, target.month.month)} — последний закрытый отчёт: он открыт в
        «Мои финансы» и не показывается как история. <Link to="/v2">Мои финансы →</Link> ·{" "}
        <Link to="/v2/capital">Капитал →</Link> · <Link to={REPORTS_PATH}>Все отчёты →</Link>
      </UiV2Notice>
    );
  } else if (!compositionReady) {
    content = (
      <UiV2Notice
        retry={() => void compositionQuery.refetch()}
        title="Данные отчёта не подтверждены"
      >
        Подтверждённая история закрытых отчётов не прочитана, поэтому денежные значения этого отчёта
        скрыты. <Link to={REPORTS_PATH}>Все отчёты →</Link>
      </UiV2Notice>
    );
  } else if (!position) {
    content = (
      <UiV2Notice
        retry={() => void compositionQuery.refetch()}
        title="Отчёт не подтверждён в истории"
      >
        Этот месяц закрыт, но его подтверждённого снимка в истории закрытых отчётов нет.{" "}
        <Link to={REPORTS_PATH}>Все отчёты →</Link>
      </UiV2Notice>
    );
  } else {
    const month = target.month;
    content = (
      <>
        <UiV2ReportContext
          kind="historical"
          month={month}
          source={SOURCE_LABELS[month.source] ?? UNKNOWN_SOURCE_LABEL}
          status="Закрыт · Утверждён"
        >
          <span className={styles.reportContextLinks}>
            {latestClosed ? (
              <Link to="/v2">
                Текущий отчёт: {formatMonth(latestClosed.year, latestClosed.month)} →
              </Link>
            ) : null}
            <Link to="/v2">Мои финансы</Link>
            <Link to="/v2/capital">Капитал</Link>
          </span>
        </UiV2ReportContext>
        <p className={reportStyles.caveat} data-testid="report-methodology-caveat">
          {CURRENT_METHODOLOGY_CAVEAT}
        </p>
        <ReportValues point={position.point} />
        <div className={styles.homeGrid}>
          <CompositionBlock assetClasses={assetClasses} point={position.point} />
          <HistoryBlock
            assetClasses={assetClasses}
            monthId={position.point.reporting_month_id}
            points={points}
            position={position}
          />
          <Panel
            eyebrow="Изменение состояния"
            id="report-change-title"
            title="Где изменились суммы"
          >
            <p className={reportStyles.muted} data-testid="report-change-unavailable">
              {NO_HISTORICAL_CHANGE_TEXT}
            </p>
            <p className={styles.panelFootnote}>
              Изменение состояния остаётся в «Мои финансы» и «Капитал» для двух последних закрытых
              отчётов: <Link to="/v2">Мои финансы →</Link> · <Link to="/v2/capital">Капитал →</Link>
            </p>
          </Panel>
          <LinkedPairsBlock point={position.point} />
          <HoldingsBlock
            lists={{
              cash: { ready: cashReady, retry: () => void cashQuery.refetch() },
              deposit: { ready: depositsReady, retry: () => void depositsQuery.refetch() },
              position: { ready: positionsReady, retry: () => void positionsQuery.refetch() },
            }}
            rows={holdingRows}
          />
          <TopPositionsBlock
            ready={riskReady}
            retry={() => void riskQuery.refetch()}
            risk={riskReady ? riskQuery.data : undefined}
          />
          <Panel
            eyebrow="Ниже в предыдущем интерфейсе"
            id="report-handoff-title"
            title="Дальше в предыдущем интерфейсе"
            wide
          >
            <ul className={reportStyles.handoffList} data-testid="report-v1-handoff">
              <li>
                <Link to={`/months/${position.point.reporting_month_id}`}>
                  Отчёт месяца в предыдущем интерфейсе →
                </Link>
              </li>
              <li>
                <Link to="/analytics">Все расчёты в предыдущем интерфейсе →</Link>
              </li>
              <li>
                <Link to="/months">Месяцы в предыдущем интерфейсе →</Link>
              </li>
            </ul>
            <p className={styles.panelFootnote}>
              Предыдущий интерфейс сохраняет свои правила выбора месяца и свой месяц-базис. Это
              отдельный переход, а не встроенная возможность v2.
            </p>
          </Panel>
        </div>
      </>
    );
  }

  return (
    <UiV2Shell
      busy={!monthsReady}
      header={
        <>
          <p className={styles.eyebrow}>Закрытый месяц</p>
          <h1 id="report-title" tabIndex={-1}>
            Исторический отчёт
          </h1>
          <p className={styles.subtitle}>
            Как выглядел отчёт выбранного закрытого месяца. Текущий отчёт всегда открыт в «Мои
            финансы».
          </p>
          <p className={reportStyles.backLink}>
            <Link to={REPORTS_PATH}>← Все отчёты</Link>
          </p>
        </>
      }
      v1ReturnPath={v1ReturnPath}
    >
      {content}
    </UiV2Shell>
  );
}
