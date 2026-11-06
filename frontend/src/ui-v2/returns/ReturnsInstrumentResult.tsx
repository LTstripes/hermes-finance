import type { InstrumentAnalysis } from "../../api/sourceReturns";
import { reasonCopy } from "../../lib/reasonCopy";
import styles from "./InstrumentResult.module.css";
import { displayMetric, type Metric, unavailable } from "./model";
import { Explanation, Value, visibleReturnReasons } from "./ReturnsInfo";

function Notes({ label, codes }: { label: string; codes: string[] }) {
  if (!codes.length) return null;
  return (
    <details className={styles.notes}>
      <summary>{label}</summary>
      <Explanation codes={codes} />
    </details>
  );
}

/** Render server results only; a missing full result is never a partial subtotal or zero. */
export function ReturnsInstrumentResult({
  result,
  analysis,
  reasonCodes = [],
}: {
  result: { pnl: Metric; rate: Metric; conditional_pnl?: Metric; conditional_rate?: Metric } | null;
  analysis?: InstrumentAnalysis<string>;
  reasonCodes?: string[];
}) {
  const originalPnl = result?.pnl ?? unavailable;
  const originalRate = result?.rate ?? { ...unavailable, unit: "fraction" as const };
  const pnl = { ...originalPnl, reason_codes: visibleReturnReasons(originalPnl.reason_codes) };
  const rate = { ...originalRate, reason_codes: visibleReturnReasons(originalRate.reason_codes) };
  const reasons = visibleReturnReasons([
    ...new Set([...reasonCodes, ...(analysis?.reason_codes ?? [])]),
  ]).filter((code) => !pnl.reason_codes.includes(code) && !rate.reason_codes.includes(code));
  const status = (metric: Metric, fallback: string) =>
    metric.reason_codes.length
      ? reasonCopy(metric.reason_codes[0], { surface: "returns" }).message
      : fallback;
  const usedAssumptions = [
    ...new Set([
      ...(analysis?.assumptions ?? []),
      ...(analysis?.pnl.assumptions ?? []),
      ...(analysis?.modified_dietz.assumptions ?? []),
      ...(analysis?.events
        .filter((event) => event.current && event.counted)
        .flatMap((event) => event.assumptions) ?? []),
    ]),
  ];
  const observedPayouts = (
    [
      ["Купоны", analysis?.components.coupons],
      ["Дивиденды", analysis?.components.dividends],
    ] as const
  ).filter(
    ([, value]) => value?.value != null && value.value !== "0" && value.status !== "unavailable",
  );
  return (
    <div className={styles.result}>
      <dl className={styles.metrics}>
        <div>
          <dt>
            {originalPnl.reason_codes.includes("clean_partial_result")
              ? "Известная часть результата ₽"
              : "Результат ₽"}
          </dt>
          <dd>
            <Value metric={pnl} label="Результат инструмента" signed />
            {pnl.value === null && <small>{status(pnl, "Результат недоступен")}</small>}
          </dd>
        </div>
        <div>
          <dt>Доходность %</dt>
          <dd>
            <Value metric={rate} label="Доходность инструмента" />
            {rate.value === null && <small>{status(rate, "Доходность недоступна")}</small>}
          </dd>
        </div>
      </dl>
      {rate.method === "modified_dietz" && <small>Modified Dietz · за период, не годовая</small>}
      {pnl.value === null && observedPayouts.length > 0 && (
        <div>
          <p>Найденные выплаты — данные могут быть неполными</p>
          <dl>
            {observedPayouts.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{displayMetric({ ...unavailable, value: value?.value ?? null })}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <Notes label="Причины" codes={reasons} />
      <Notes label="Допущения" codes={usedAssumptions} />
    </div>
  );
}
