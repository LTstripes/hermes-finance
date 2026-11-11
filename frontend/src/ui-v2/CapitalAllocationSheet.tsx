import type { ReactNode } from "react";

import type {
  RiskAllocationMetric,
  RiskConcentrationItem,
  RiskConcentrationMetric,
  RiskMoneyValue,
} from "../api/riskAllocation";
import { HelpTip } from "../components/ui";
import { formatPercent } from "../lib/format";
import {
  ASSET_CLASS_LABELS,
  sourceKindLabel,
  supportReasonLabel,
  unsupportedMetricReason,
} from "../lib/riskSupportCopy";
import styles from "./CapitalAllocationSheet.module.css";
import { UNASSIGNED_CASH_KEY } from "./capitalHoldings";
import sheet from "./ReportSheet.module.css";
import { UiV2WidgetState } from "./UiV2StateBlocks";
import { wholeMoneyText } from "./wholeMoney";

/** Risk-allocation classes keep the --c-* colours of the capital classes (#1079). */
const RISK_CLASS_COLORS: Record<string, string> = {
  cash: "var(--c-cash)",
  deposits: "var(--c-dep)",
  stock: "var(--c-stock)",
  bond: "var(--c-bond)",
  gold: "var(--c-gold)",
  fund: "#6f9c8b",
  currency: "#7d8fa6",
  other: "#b9b2a4",
};

/** Overview sums in whole rubles (P 12.2); exact amounts stay in Capital holdings. */
function money(value: RiskMoneyValue | null | undefined): string {
  if (!value?.amount || !value.currency) return "—";
  return wholeMoneyText(value, "—");
}

function percent(value: string | null | undefined): string {
  return value == null ? "—" : formatPercent(value, { digits: 1, share: true });
}

/** Share of a backend percentage as a bar width; geometry only. */
function width(value: string | null | undefined): string {
  const number = value == null ? Number.NaN : Number(value);
  return Number.isFinite(number) ? `${Math.max(0, Math.min(100, number))}%` : "0%";
}

function isZero(value: RiskMoneyValue | null | undefined): boolean {
  return value != null && /^-?0(?:\.0+)?$/.test(value.amount.trim());
}

/**
 * One muted line for everything that limits a slice: unallocated amount,
 * support reasons and excluded rows. Said once, not per table (AGENTS).
 */
function Limits({ metric, title }: { metric: RiskAllocationMetric; title: string }) {
  // Unassigned cash is its own row in the account slice; the same sum is not repeated below it.
  const shownAsRow = metric.items.some(
    (item) =>
      item.key === UNASSIGNED_CASH_KEY &&
      item.amount.amount === metric.unallocated_amount.amount &&
      item.amount.currency === metric.unallocated_amount.currency,
  );
  const unallocated =
    metric.coverage_pct !== null && metric.coverage_pct !== "100.00" && !shownAsRow;
  const reasons = metric.support.reason_codes.map(supportReasonLabel);
  if (!unallocated && reasons.length === 0 && metric.excluded.length === 0) return null;
  return (
    <div className={sheet.gapNote}>
      {unallocated ? (
        <span>
          Не распределено {money(metric.unallocated_amount)}
          <HelpTip label={`Нераспределённые суммы: ${title}`}>
            Основа долей — полная сумма ликвидных активов {money(metric.denominator)}. Неизвестные
            группы входят в неё.
          </HelpTip>
        </span>
      ) : null}
      {reasons.length > 0 ? <span>{reasons.join("; ")}</span> : null}
      {metric.excluded.length > 0 ? (
        <details className={styles.excluded}>
          <summary>Исключённые строки: {metric.excluded.length}</summary>
          <ul>
            {metric.excluded.map((issue) => (
              <li
                key={`${issue.source_kind}-${issue.source_id ?? "unknown"}-${issue.status}-${issue.reason_codes.join("|")}`}
              >
                {sourceKindLabel(issue.source_kind)} ·{" "}
                {issue.reason_codes.map(supportReasonLabel).join(", ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function classLabel(key: string, fallback: string): string {
  return ASSET_CLASS_LABELS[key] ?? fallback;
}

/** Liquid assets by class: one 100% strip and a legend that filters the holdings. */
export function ClassAllocation({
  metric,
  selected,
  onSelect,
}: {
  metric: RiskAllocationMetric | undefined;
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  if (!metric) return <UiV2WidgetState title="По классам активов: нет данных" />;
  const unsupported = unsupportedMetricReason(metric.support.status, metric.support.reason_codes);
  if (unsupported) return <UiV2WidgetState title={unsupported} />;
  if (metric.items.length === 0) return <p className={sheet.muted}>Нет данных</p>;
  return (
    <div className={styles.block}>
      <div aria-hidden="true" className={sheet.strip}>
        {metric.items
          .filter((item) => !isZero(item.amount))
          .map((item) => (
            <span
              key={item.key}
              style={{
                background: RISK_CLASS_COLORS[item.key] ?? "var(--faint)",
                flexBasis: width(item.share_pct),
                flexGrow: 0,
              }}
            />
          ))}
      </div>
      <ul className={sheet.legend}>
        {metric.items.map((item) => (
          <li data-testid={`capital-class-${item.key}`} key={item.key}>
            <i
              aria-hidden="true"
              className={sheet.dot}
              style={{ background: RISK_CLASS_COLORS[item.key] ?? "var(--faint)" }}
            />
            <button
              aria-pressed={selected === item.key}
              className={styles.pick}
              onClick={() => onSelect(item.key)}
              type="button"
            >
              {classLabel(item.key, item.label)}
            </button>
            <strong className={sheet.amount}>{money(item.amount)}</strong>
            <span className={sheet.share}>{percent(item.share_pct)}</span>
          </li>
        ))}
      </ul>
      <Limits metric={metric} title="По классам активов" />
    </div>
  );
}

/** Liquid assets by account as bars; each row filters the holdings. */
export function AccountAllocation({
  metric,
  selected,
  onSelect,
  retry,
}: {
  metric: RiskAllocationMetric | undefined;
  selected: string | null;
  onSelect: (key: string, label: string) => void;
  retry: () => void;
}) {
  if (!metric) return <UiV2WidgetState title="По счетам: нет данных" />;
  const unsupported = unsupportedMetricReason(metric.support.status, metric.support.reason_codes);
  if (unsupported) return <UiV2WidgetState retry={retry} title={unsupported} />;
  if (metric.items.length === 0)
    return <p className={sheet.muted}>В закрытом отчёте нет строк для этого среза.</p>;
  return (
    <div className={styles.block}>
      <ul className={styles.bars}>
        {metric.items.map((item) => (
          <li key={item.key}>
            <button
              aria-pressed={selected === item.key}
              className={styles.barRow}
              data-testid={`capital-bucket-${item.key}`}
              onClick={() => onSelect(item.key, item.label)}
              type="button"
            >
              <span className={styles.barLabel}>
                {item.key === UNASSIGNED_CASH_KEY ? ASSET_CLASS_LABELS.unassigned_cash : item.label}
              </span>
              <strong className={sheet.amount}>{money(item.amount)}</strong>
              <span className={sheet.share}>{percent(item.share_pct)}</span>
              <span aria-hidden="true" className={`${sheet.track} ${styles.barTrack}`}>
                <span className={sheet.fill} style={{ width: width(item.share_pct) }} />
              </span>
            </button>
          </li>
        ))}
      </ul>
      <Limits
        metric={{
          ...metric,
          // Unassigned cash is already its own row here; its reason needs no second line.
          support: {
            ...metric.support,
            reason_codes: metric.support.reason_codes.filter(
              (reason) => reason !== "cash_not_account_linked",
            ),
          },
        }}
        title="По счетам"
      />
    </div>
  );
}

/** Largest positions as a ranked table with share bars. */
export function TopPositions({
  metric,
  renderLabel,
}: {
  metric: RiskConcentrationMetric | undefined;
  renderLabel: (item: RiskConcentrationItem) => ReactNode;
}) {
  if (!metric) return <UiV2WidgetState title="Крупнейшие позиции: нет данных" />;
  const unsupported = unsupportedMetricReason(metric.support.status, metric.support.reason_codes);
  if (unsupported) return <UiV2WidgetState title={unsupported} />;
  if (metric.items.length === 0) return <p className={sheet.muted}>Нет данных</p>;
  return (
    <div className={styles.block} data-testid="capital-top-positions">
      <p className={sheet.muted}>
        Топ-{metric.top_n}: <strong className={sheet.amount}>{money(metric.top_amount)}</strong> ·{" "}
        {percent(metric.top_share_pct)} ликвидных активов
      </p>
      <table className={styles.positions}>
        <caption className={sheet.visuallyHidden}>Крупнейшие позиции</caption>
        <thead className={sheet.visuallyHidden}>
          <tr>
            <th scope="col">Позиция</th>
            <th scope="col">Сумма</th>
            <th scope="col">Доля ликвидных активов</th>
          </tr>
        </thead>
        <tbody>
          {metric.items.map((item, index) => (
            <tr key={item.key}>
              <th scope="row">
                <span className={styles.rank}>{index + 1}</span>
                <span className={styles.positionName}>
                  {renderLabel(item)}
                  {item.account_name ? <small>{item.account_name}</small> : null}
                </span>
              </th>
              <td className={sheet.amount}>
                {item.is_approximate ? (
                  <abbr className={styles.approx} title="приблизительно">
                    ≈{" "}
                  </abbr>
                ) : null}
                {money(item.amount)}
              </td>
              <td className={styles.shareCell}>
                <span className={sheet.share}>{percent(item.share_pct)}</span>
                <span aria-hidden="true" className={sheet.track}>
                  <span className={sheet.fill} style={{ width: width(item.share_pct) }} />
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {metric.excluded.length > 0 ? (
        <p className={sheet.gapNote}>Исключённые строки: {metric.excluded.length}</p>
      ) : null}
    </div>
  );
}
