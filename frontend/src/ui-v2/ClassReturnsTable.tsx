import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { getClassReturns } from "../api/performance";
import type { ClassReturns, PerformanceAssetClass } from "../api/types";
import { formatDate } from "../lib/format";
import { queryKeys } from "../queryClient";
import { formatPerformancePercent } from "./CapitalPerformanceSummary";
import { ClassEvidencePreparation } from "./ClassEvidencePreparation";
import { needsAnnualizationWarning } from "./capitalPerformanceContext";
import {
  classCoverageCopy,
  classMetricState,
  classReasonCopy,
  isClassReturnsFresh,
} from "./classReturnsCopy";
import styles from "./UiV2CapitalPerformance.module.css";
import { isQueryReady } from "./UiV2StateBlocks";

const CLASSES: Array<{ key: PerformanceAssetClass; label: string }> = [
  { key: "stock", label: "Акции" },
  { key: "bond", label: "Облигации" },
  { key: "gold", label: "Золото" },
  { key: "deposit", label: "Депозиты" },
];

function Reasons({ codes }: { codes: string[] }) {
  return codes.length === 0 ? (
    <p>Причин недоступности нет.</p>
  ) : (
    <ul>
      {codes.map((code) => (
        <li key={code}>
          {classReasonCopy(code)} <code>{code}</code>
        </li>
      ))}
    </ul>
  );
}

function Explanation({ row }: { row: ClassReturns }) {
  return (
    <div className={styles.classExplanation}>
      <dl>
        <dt>Запрошенный период</dt>
        <dd>
          {formatDate(row.requested_period.start_date)} —{" "}
          {formatDate(row.requested_period.end_date)}
        </dd>
        <dt>Фактические границы оценки</dt>
        <dd>
          {formatDate(row.actual_covered_period.start_date, { empty: "не подтверждена" })} —{" "}
          {formatDate(row.actual_covered_period.end_date, { empty: "не подтверждена" })}
        </dd>
        <dt>Валюта</dt>
        <dd>{row.performance_currency}</dd>
        <dt>Основание оценки</dt>
        <dd>
          Сохранённая рыночная стоимость в RUB на границах периода. Это не налоговый учёт и не учёт
          себестоимости.
        </dd>
        <dt>Подтверждение интервала без движений через границу класса</dt>
        <dd>{classCoverageCopy(row.coverage_state)}</dd>
      </dl>
      {row.coverage_provenance.length === 0 ? (
        <p>Подтверждений владельца для этого интервала нет.</p>
      ) : (
        row.coverage_provenance.map((coverage) => (
          <div key={coverage.id}>
            <p>
              Подтверждение владельца · версия {coverage.revision} ·{" "}
              {formatDate(coverage.covered_from)} — {formatDate(coverage.covered_to)} ·{" "}
              {classCoverageCopy(coverage.coverage_state)}
            </p>
            {coverage.provenance_reference ? (
              <p>Ссылка на основание: {coverage.provenance_reference}</p>
            ) : null}
            <p>
              Полный состав на начало:{" "}
              {coverage.opening_inventory_complete ? "подтверждён" : "не подтверждён"}. Полный
              состав на конец:{" "}
              {coverage.closing_inventory_complete ? "подтверждён" : "не подтверждён"}.
            </p>
          </div>
        ))
      )}
      <h4>Причины по подтверждениям</h4>
      <Reasons codes={row.evidence_reason_codes} />
      {(["twrr", "xirr"] as const).map((kind) => (
        <div key={kind}>
          <h4>
            {kind === "xirr" ? "XIRR, годовых" : "TWRR за период"}:{" "}
            {classMetricState(row[kind], row)}
          </h4>
          {row[kind].reason_source === "solver" ? (
            <>
              <p>Причины расчётного метода</p>
              <Reasons codes={row[kind].reason_codes} />
            </>
          ) : row[kind].reason_source === "evidence" ? (
            <>
              <p>Причины по подтверждениям</p>
              <Reasons codes={row[kind].reason_codes} />
            </>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function ClassRow({
  assetClass,
  label,
  start,
  end,
}: {
  assetClass: PerformanceAssetClass;
  label: string;
  start: string;
  end: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const explanationId = useId();
  const query = useQuery({
    queryKey: queryKeys.classReturns(assetClass, start, end),
    queryFn: ({ signal }) => getClassReturns(assetClass, start, end, signal),
    refetchOnWindowFocus: true,
  });
  const ready = isQueryReady(query);
  const row =
    ready && query.data && isClassReturnsFresh(query.data, assetClass, start, end)
      ? query.data
      : null;
  const mismatch = ready && row === null;
  const metricText = (kind: "twrr" | "xirr") =>
    row && row[kind].availability === "available" && row[kind].quality === "exact"
      ? formatPerformancePercent(row[kind].value)
      : "—";

  return (
    <>
      <tr data-testid={`class-return-${assetClass}`}>
        <th scope="row">{label}</th>
        <td data-label="TWRR за период" className={styles.classNumeric}>
          {metricText("twrr")}
        </td>
        <td data-label="XIRR, годовых" className={styles.classNumeric}>
          {metricText("xirr")}
        </td>
        <td className={styles.classState}>
          {query.isError || mismatch ? (
            <>
              <p role="alert">
                {mismatch
                  ? "Ответ не соответствует классу, периоду или валюте и скрыт."
                  : "Не удалось прочитать ответ. Это сетевая ошибка, а не неполнота подтверждений."}
              </p>
              <button
                className={styles.inlineButton}
                onClick={() => void query.refetch()}
                type="button"
              >
                Повторить: {label}
              </button>
            </>
          ) : row ? (
            <>
              <p>TWRR: {classMetricState(row.twrr, row)}</p>
              <p>XIRR: {classMetricState(row.xirr, row)}</p>
              <button
                aria-expanded={expanded}
                aria-controls={explanationId}
                className={styles.inlineButton}
                onClick={() => setExpanded((value) => !value)}
                type="button"
              >
                {expanded ? "Скрыть" : "Подробнее"}: {label}
              </button>
            </>
          ) : (
            <p role="status">Читаем результат…</p>
          )}
        </td>
      </tr>
      {row ? (
        <tr hidden={!expanded} id={explanationId}>
          <td colSpan={4}>
            <Explanation row={row} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function ClassReturnsTable({ start, end }: { start: string; end: string }) {
  return (
    <section aria-label="По классам" className={styles.summary}>
      <p className={styles.periodLine}>
        Доходность классов по историческому составу всего портфеля. Проценты классов не суммируются
        и не усредняются. Оценки в RUB; XIRR и TWRR доступны независимо.
      </p>
      {needsAnnualizationWarning(start, end) ? (
        <p className={styles.warning}>XIRR приведён к году по короткому периоду; это не прогноз.</p>
      ) : null}
      <table className={styles.classTable}>
        <caption className={styles.periodLine}>
          Доходность по классам · {formatDate(start)} — {formatDate(end)}
        </caption>
        <thead>
          <tr>
            <th scope="col">Класс</th>
            <th scope="col">TWRR за период</th>
            <th scope="col">XIRR, годовых</th>
            <th scope="col">Состояние</th>
          </tr>
        </thead>
        <tbody>
          {CLASSES.map(({ key, label }) => (
            <ClassRow
              key={`${key}:${start}:${end}`}
              assetClass={key}
              label={label}
              start={start}
              end={end}
            />
          ))}
        </tbody>
      </table>
      <ClassEvidencePreparation start={start} end={end} />
    </section>
  );
}
