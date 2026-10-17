import { useEffect, useRef, useState } from "react";
import {
  type BrokerStatementReturn,
  formatStatementPercent,
  statementMoney,
} from "../api/brokerStatementReturn";
import {
  contextMatches,
  resultMatches,
  type WhatIfAssumptions,
  type WhatIfChoice,
  type WhatIfContext,
  type WhatIfResult,
  whatIfRequest,
} from "../api/brokerStatementWhatIf";
import { formatApiError } from "../api/client";
import { formatDate } from "../lib/format";
import styles from "./BrokerStatementWhatIfPanel.module.css";

const LABELS: Record<WhatIfChoice, string> = {
  native_totals_continuously:
    "Моделировать этот счёт непрерывно по нативным оценкам на обе даты, без корректировок стоимости",
  use_displayed_schedule:
    "Использовать весь показанный график: принятые H2 обязательны, кандидат — согласно отдельному выбору",
  include_as_account_inflow: "Включить кандидата как поступление в счёт по дате проводки",
  exclude_from_external_schedule:
    "Исключить кандидата из внешних движений модели; наблюдаемый cash остаётся",
  no_other_account_crossings:
    "В этой модели у выбранного счёта нет других пересечений границы, кроме показанного графика",
  no_additional_flow_or_adjustment:
    "Эти Money-проводки не дают дополнительного потока инвестора или корректировки конечных оценок",
  no_additional_channel_effect:
    "Этот канал не даёт дополнительного эффекта cash, активов или обязательств вне нативных итогов и графика",
};
const SLOTS = {
  native_basis: "Нативные оценки счёта",
  schedule: "График движений",
  remaining_crossings: "Остальные пересечения границы",
  money_basis: "Неразрешённые Money-проводки",
  residual: "Остаточный риск канала",
};

export function BrokerStatementWhatIfPanel({ actual }: { actual: BrokerStatementReturn }) {
  const [file, setFile] = useState<File | null>(null);
  const [context, setContext] = useState<WhatIfContext | null>(null);
  const [selected, setSelected] = useState<Record<string, WhatIfChoice>>({});
  const [mode, setMode] = useState<WhatIfAssumptions["schedule_mode"]>(null);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      generation.current++;
      controller.current?.abort();
    },
    [],
  );
  function invalidate() {
    generation.current++;
    controller.current?.abort();
    setResult(null);
    setBusy(false);
    setError("");
  }
  const assumptions: WhatIfAssumptions = {
    version: "account_native_what_if_v1",
    schedule_mode: mode,
    selections: (context?.required_assumptions ?? [])
      .filter((r) => selected[r.requirement_id])
      .map((r) => ({
        requirement_id: r.requirement_id,
        source_references: r.source_references,
        choice: selected[r.requirement_id],
      }))
      .sort((a, b) =>
        a.requirement_id < b.requirement_id ? -1 : a.requirement_id > b.requirement_id ? 1 : 0,
      ),
  };
  async function run(operation: "context" | "evaluate" | "export") {
    if (!file || (operation !== "context" && !context)) return;
    const previous = result;
    invalidate();
    const epoch = generation.current;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    try {
      if (operation === "context") {
        setContext(null);
        setSelected({});
        setMode(null);
        const fresh = await whatIfRequest<WhatIfContext>(operation, actual, file, abort.signal);
        if (generation.current !== epoch) return;
        if (!contextMatches(fresh, actual))
          throw new Error("Контекст не соответствует выбранному счёту, периоду или S3.");
        setContext(fresh);
      } else if (context) {
        const fresh = await whatIfRequest<WhatIfResult>(
          operation,
          actual,
          file,
          abort.signal,
          context,
          assumptions,
          operation === "export" ? (previous ?? undefined) : undefined,
        );
        if (generation.current !== epoch) return;
        if (
          !resultMatches(fresh, context, actual, assumptions) ||
          (operation === "export" && fresh.result_fingerprint !== previous?.result_fingerprint)
        ) {
          throw new Error("Результат не соответствует текущему контексту и явным допущениям.");
        }
        setResult(fresh);
        if (operation === "export" && fresh.status === "hypothetical") {
          const url = URL.createObjectURL(
            new Blob([JSON.stringify(fresh, null, 2)], { type: "application/json" }),
          );
          const link = document.createElement("a");
          link.href = url;
          link.download = "broker-statement-what-if.json";
          link.click();
          URL.revokeObjectURL(url);
        }
      }
    } catch (cause) {
      if (generation.current !== epoch) return;
      setContext(null);
      setSelected({});
      setMode(null);
      setResult(null);
      setError(formatApiError(cause));
    } finally {
      if (generation.current === epoch) setBusy(false);
    }
  }
  return (
    <section className={styles.panel} aria-label="Условная оценка / сценарий">
      <h2>Условная оценка / сценарий</h2>
      <p className={styles.qualification}>
        Гипотетическая модель выбранного счёта. Она не подтверждает фактическую доходность, полноту
        движений или внешность для портфеля. Допущения действуют только до изменения страницы.
      </p>
      <p>
        Фактический S3:{" "}
        {actual.status === "unavailable"
          ? "Недоступна"
          : formatStatementPercent(actual.rate_fraction)}
        . Причины: {actual.reason_codes.join(", ") || "нет"}.
      </p>
      <label>
        Неизменённый оригинал XML
        <input
          aria-label="Оригинал WHAT-IF"
          type="file"
          accept=".xml"
          onChange={(e) => {
            invalidate();
            setContext(null);
            setSelected({});
            setMode(null);
            setFile(e.target.files?.[0] ?? null);
          }}
        />
      </label>
      <button type="button" disabled={!file || busy} onClick={() => void run("context")}>
        Проверить контекст сценария
      </button>
      {busy && <p role="status">Перепроверяем источник и зависимости…</p>}
      {error && <p role="alert">{error}</p>}
      {context && (
        <>
          <h3>Наблюдаемые нативные факты</h3>
          <div className={styles.facts}>
            <p>
              {formatDate(context.t0)} · EOD:{" "}
              {statementMoney(context.observed.opening?.total_value_kopecks ?? null)}
            </p>
            <p>
              {formatDate(context.t1)} · EOD:{" "}
              {statementMoney(context.observed.closing?.total_value_kopecks ?? null)}
            </p>
            <p>Изменение капитала: {statementMoney(context.observed.capital_delta_kopecks)}</p>
          </div>
          <p>
            Это изменение капитала, не доходность. Позиции и отдельный RUB cash показаны в actual S3
            выше.
          </p>
          <h3>Принятые H2 и необязательный кандидат</h3>
          <ul>
            {context.fixed_schedule.map((f) => (
              <li key={f.source_reference}>
                {formatDate(f.event_date)}: {statementMoney(f.signed_amount_kopecks)} · обязательное
                принятое H2
              </li>
            ))}
          </ul>
          {context.fixed_schedule.length === 0 && (
            <p>Принятых H2 нет. Это не подтверждение отсутствия движений.</p>
          )}
          {context.optional_candidate && (
            <p>
              Неподтверждённый кандидат: {formatDate(context.optional_candidate.event_date)} · +
              {statementMoney(context.optional_candidate.signed_amount_kopecks)}. Дата проводки;
              принадлежность внешнему инвестору не доказана.
            </p>
          )}
          {context.hard_blockers.length > 0 && (
            <div role="alert">
              <p>Сценарий заблокирован:</p>
              <ul>
                {context.hard_blockers.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          <h3>Явные допущения</h3>
          {context.required_assumptions.map((r) => (
            <div key={r.requirement_id}>
              <label>
                {SLOTS[r.slot]} · {r.subject}
                <select
                  aria-label={r.requirement_id}
                  value={selected[r.requirement_id] ?? ""}
                  onChange={(e) => {
                    invalidate();
                    setSelected((s) => ({
                      ...s,
                      [r.requirement_id]: e.target.value as WhatIfChoice,
                    }));
                  }}
                >
                  <option value="">Не выбрано</option>
                  {r.choices.map((choice) => (
                    <option key={choice} value={choice}>
                      {LABELS[choice]}
                    </option>
                  ))}
                </select>
              </label>
              {selected[r.requirement_id] && <p>{LABELS[selected[r.requirement_id]]}</p>}
              <details>
                <summary>Полный состав ссылок ({r.source_references.length})</summary>
                <ul>
                  {r.source_references.map((ref) => (
                    <li key={ref}>{ref}</li>
                  ))}
                </ul>
              </details>
            </div>
          ))}
          <label>
            Режим графика
            <select
              aria-label="Режим графика"
              value={mode ?? ""}
              onChange={(e) => {
                invalidate();
                setMode((e.target.value as typeof mode) || null);
              }}
            >
              <option value="">Не выбран</option>
              <option value="dated">Явный датированный график</option>
              <option value="explicit_empty">Явно пустой график</option>
            </select>
          </label>
          <button
            type="button"
            disabled={busy || context.hard_blockers.length > 0}
            onClick={() => void run("evaluate")}
          >
            Рассчитать условную оценку
          </button>
          {result && (
            <section aria-label="Результат сценария">
              {result.status === "hypothetical" ? (
                <>
                  <p className={styles.rate}>
                    {formatStatementPercent(result.scenario_rate_fraction)} · за фактический период
                  </p>
                  <p>
                    <strong>
                      Условный результат после учёта выбранных внешних движений:{" "}
                      {statementMoney(result.scenario_result_kopecks)}
                    </strong>
                  </p>
                  <p>
                    V1 − V0 − выбранные внешние движения. Не фактическая прибыль, налоговый доход
                    или V0 × ставка.
                  </p>
                </>
              ) : (
                <p>
                  {result.status === "needs_assumptions"
                    ? "Выбери все необходимые допущения и режим графика."
                    : `Расчёт заблокирован: ${result.reason_codes.join(", ")}`}
                </p>
              )}
              <h3>Выбранные допущения</h3>
              <ul>
                {result.assumptions.selections.map((s) => (
                  <li key={s.requirement_id}>{LABELS[s.choice]}</li>
                ))}
              </ul>
              <h3>Ограничения фактического результата</h3>
              <ul>
                {result.limitations.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </section>
          )}
          <button
            type="button"
            disabled={busy || result?.status !== "hypothetical"}
            onClick={() => void run("export")}
          >
            Экспорт сценария JSON с перепроверкой
          </button>
          <details>
            <summary>Полный диагностический состав и fingerprints</summary>
            <pre>{JSON.stringify(context, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
