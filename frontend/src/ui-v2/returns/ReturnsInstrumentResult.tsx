import type { InstrumentAnalysis } from "../../api/sourceReturns";
import { reasonCopy } from "../../lib/reasonCopy";
import styles from "./InstrumentResult.module.css";
import { displayMetric, type Metric, unavailable } from "./model";
import { Explanation, Value, visibleReturnReasons } from "./ReturnsInfo";

function Notes({ label, codes }: { label: string; codes: string[] }) {
  const messages = [
    ...new Set(codes.map((code) => reasonCopy(code, { surface: "returns" }).message)),
  ];
  if (!messages.length) return null;
  return (
    <div className={styles.notes}>
      <span>
        {label}: {messages.slice(0, 2).join(" ")}
      </span>
      <details>
        <summary>Подробнее: {label.toLocaleLowerCase("ru")}</summary>
        <Explanation codes={codes} />
      </details>
    </div>
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
    ...new Set([
      ...reasonCodes,
      ...pnl.reason_codes,
      ...rate.reason_codes,
      ...(analysis?.reason_codes ?? []),
    ]),
  ]);
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
  const beforeCosts =
    pnl.value === null &&
    result?.conditional_pnl?.value != null &&
    result.conditional_pnl.reason_codes.includes("unallocated_costs_excluded");
  return (
    <div className={styles.result}>
      {beforeCosts && (
        <section aria-label="Результат без нераспределённых расходов">
          <p>Без нераспределённых расходов счёта</p>
          <strong>{displayMetric(result!.conditional_pnl!, true)}</strong>
          {" · "}
          {result?.conditional_rate && displayMetric(result.conditional_rate)}
          <small>Полный результат после распределения расходов пока неизвестен.</small>
        </section>
      )}
      <dl className={styles.metrics}>
        <div>
          <dt>Результат ₽</dt>
          <dd>
            <Value metric={pnl} label="Результат инструмента" signed />
          </dd>
        </div>
        <div>
          <dt>Доходность %</dt>
          <dd>
            <Value metric={rate} label="Доходность инструмента" />
          </dd>
        </div>
      </dl>
      {rate.method === "modified_dietz" && <small>Modified Dietz · за период, не годовая</small>}
      {(pnl.value === null || rate.value === null) && (
        <p className={styles.notice}>Нужна проверка данных</p>
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
