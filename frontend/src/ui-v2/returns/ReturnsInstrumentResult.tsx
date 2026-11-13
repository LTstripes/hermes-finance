import type { InstrumentAnalysis } from "../../api/sourceReturns";
import { type PositionRate, positionRateMetric, positionRatePeriod } from "./cards";
import styles from "./InstrumentResult.module.css";
import { displayMetric, type Metric, unavailable } from "./model";
import { Explanation, MissingMetricNote, Value, visibleReturnReasons } from "./ReturnsInfo";

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
  showMissingNote = true,
  positionRates,
}: {
  result: { pnl: Metric; rate: Metric; conditional_pnl?: Metric; conditional_rate?: Metric } | null;
  analysis?: InstrumentAnalysis<string>;
  reasonCodes?: string[];
  showMissingNote?: boolean;
  /** Clean position rates replace the period Modified Dietz for a position (#1016). */
  positionRates?: { simple: PositionRate; xirr: PositionRate | null } | null;
}) {
  const originalPnl = result?.pnl ?? unavailable;
  const originalRate = positionRates
    ? positionRateMetric(positionRates.simple)
    : (result?.rate ?? { ...unavailable, unit: "fraction" as const });
  const annual =
    positionRates?.xirr && positionRates.xirr.value !== null
      ? positionRateMetric(positionRates.xirr)
      : null;
  const shortHolding = !!positionRates?.xirr?.reason_codes.includes("short_holding");
  const pnl = { ...originalPnl, reason_codes: visibleReturnReasons(originalPnl.reason_codes) };
  const rate = { ...originalRate, reason_codes: visibleReturnReasons(originalRate.reason_codes) };
  const reasons = visibleReturnReasons([
    ...new Set([...reasonCodes, ...(analysis?.reason_codes ?? [])]),
  ]).filter((code) => !pnl.reason_codes.includes(code) && !rate.reason_codes.includes(code));
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
              ? "Сумма по доступным данным ₽"
              : "Результат ₽"}
          </dt>
          <dd>
            <Value metric={pnl} label="Результат инструмента" signed />
          </dd>
        </div>
        <div>
          <dt>{positionRates ? "На вложенное %" : "Доходность %"}</dt>
          <dd>
            <Value metric={rate} label="Доходность инструмента" signed={!!positionRates} />
          </dd>
        </div>
        {annual && (
          <div>
            <dt>Годовая %</dt>
            <dd>
              <Value metric={annual} label="Годовая доходность" signed />
            </dd>
          </div>
        )}
      </dl>
      {annual && <small>{positionRatePeriod(positionRates?.xirr)}</small>}
      {showMissingNote && <MissingMetricNote metrics={[pnl, rate]} />}
      {rate.method === "modified_dietz" && <small>Modified Dietz · за период, не годовая</small>}
      {positionRates && !annual && shortHolding && rate.value !== null && (
        <small>Годовая не считается: деньги в среднем были в позиции меньше года</small>
      )}
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
