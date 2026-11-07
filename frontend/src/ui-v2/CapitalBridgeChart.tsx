import type { MoneyValue } from "../api/types";
import styles from "./CapitalBridgeChart.module.css";
import { moneyDeltaText as exactDelta, moneyText as exactText, moneyTone } from "./valueFormat";
import { wholeMoneyDeltaText as moneyDeltaText, wholeMoneyText as moneyText } from "./wholeMoney";

export type BridgeStep = {
  label: string;
  amount: MoneyValue;
  kind: "level" | "change";
  testId?: string;
};

/** Geometry only: positions never feed a shown amount. */
function coordinate(value: MoneyValue): number {
  const number = Number(value.amount);
  return Number.isFinite(number) ? number : 0;
}

/**
 * Waterfall "start → each known component → end" (#1079 stage 4). All amounts
 * come from the backend bridge; the chart only places them. Level bars start
 * at the bottom of a cropped axis so that monthly changes stay readable.
 */
export function CapitalBridgeChart({ steps }: { steps: BridgeStep[] }) {
  let running = 0;
  const placed = steps.map((step) => {
    const value = coordinate(step.amount);
    if (step.kind === "level") {
      running = value;
      return { step, from: value, to: value };
    }
    const from = running;
    running += value;
    return { step, from, to: running };
  });
  const levels = placed.flatMap((item) => [item.from, item.to]);
  const high = Math.max(...levels);
  const low = Math.min(...levels);
  const range = high - low || Math.abs(high) * 0.1 || 1;
  // Crop the axis below the lowest level by one and a half ranges, never below zero for positive data.
  const floor = low >= 0 ? Math.max(0, low - range * 1.5) : low - range * 0.25;
  const top = high + range * 0.15;
  const span = top - floor || 1;
  const percent = (value: number) => `${((value - floor) / span) * 100}%`;

  return (
    <ol
      className={styles.bridge}
      style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
    >
      {placed.map(({ step, from, to }, index) => {
        const level = step.kind === "level";
        const lower = level ? floor : Math.min(from, to);
        const upper = level ? to : Math.max(from, to);
        const tone = level ? "level" : moneyTone(step.amount);
        const last = index === placed.length - 1;
        return (
          <li
            data-testid={step.testId}
            key={step.label}
            title={level ? exactText(step.amount) : exactDelta(step.amount)}
          >
            <span aria-hidden="true" className={styles.plot}>
              {index > 0 ? (
                <span className={styles.connector} style={{ bottom: percent(from) }} />
              ) : null}
              <span
                className={styles.bar}
                data-last={last || undefined}
                data-tone={tone}
                style={{
                  bottom: percent(lower),
                  height: `calc(${percent(upper)} - ${percent(lower)})`,
                }}
              >
                <span className={styles.value}>
                  {level ? moneyText(step.amount) : moneyDeltaText(step.amount)}
                </span>
              </span>
            </span>
            <span className={styles.label}>{step.label}</span>
            <span className={styles.visuallyHidden}>
              : {level ? moneyText(step.amount) : moneyDeltaText(step.amount)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
