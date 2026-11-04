import type { InstrumentAnalysis } from "../../api/sourceReturns";
import { reasonCopy } from "../../lib/reasonCopy";
import styles from "./InstrumentResult.module.css";
import { type Metric, unavailable } from "./model";
import { Explanation, Value } from "./ReturnsInfo";

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
  hideAccountGift = false,
}: {
  result: { pnl: Metric; rate: Metric } | null;
  analysis?: InstrumentAnalysis<string>;
  reasonCodes?: string[];
  hideAccountGift?: boolean;
}) {
  const visible = (codes: string[]) =>
    hideAccountGift ? codes.filter((code) => code !== "broker_gift_external_flow") : codes;
  const originalPnl = result?.pnl ?? unavailable;
  const originalRate = result?.rate ?? { ...unavailable, unit: "fraction" as const };
  const pnl = { ...originalPnl, reason_codes: visible(originalPnl.reason_codes) };
  const rate = { ...originalRate, reason_codes: visible(originalRate.reason_codes) };
  const reasons = visible([
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
  return (
    <div className={styles.result}>
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
      <Notes label="Причины" codes={reasons} />
      <Notes label="Допущения" codes={usedAssumptions} />
    </div>
  );
}
