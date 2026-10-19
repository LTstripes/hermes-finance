import { useEffect, useRef, useState } from "react";
import {
  contextMatches,
  type ProvisionalAssumptions,
  type ProvisionalChoice,
  type ProvisionalContext,
  type ProvisionalRequirement,
  type ProvisionalResult,
  provisionalRequest,
  resultMatches,
} from "../../api/brokerStatementProvisional";
import { formatStatementPercent, statementMoney } from "../../api/brokerStatementReturn";
import { formatApiError } from "../../api/client";
import type { SourceIntake } from "../../api/sourceIntake";
import { formatDate } from "../../lib/format";
import styles from "./BrokerProvisionalEstimate.module.css";

const CHOICES: Record<ProvisionalChoice, string> = {
  native_totals_continuously:
    "Моделировать этот счёт непрерывно по нативным EOD-итогам, без корректировок стоимости",
  use_displayed_schedule: "Использовать явно выбранный график внешних движений",
  include_as_account_inflow: "Включить как внешнее поступление в счёт по дате проводки",
  exclude_from_external_schedule:
    "Не считать внешним движением; наблюдаемая проводка остаётся в источнике",
  no_other_account_crossings:
    "В этом сценарии у счёта нет других пересечений границы, кроме выбранного графика",
  no_additional_flow_or_adjustment:
    "Распознанные сделки/расчёты/комиссии/НКД/pending не дают дополнительного потока или корректировки",
  native_totals_include_REPO_as_reported:
    "Нативные итоги уже включают REPO так, как его показал брокер; отдельный эффект не моделируется",
  unparsed_rows_reflected_in_native_totals:
    "Нераспознанные строки уже отражены в нативных итогах брокера; отдельный эффект не моделируется",
};
const SLOTS: Record<ProvisionalRequirement["slot"], string> = {
  native_basis: "Нативные итоги счёта",
  schedule: "График внешних движений",
  candidate: "Распознанный входящий кандидат",
  remaining_crossings: "Остальные пересечения границы",
  trades_money_basis: "Сделки, расчёты, комиссии, НКД, pending",
  repo_basis: "REPO",
  unparsed_basis: "Нераспознанные разделы",
};

export function BrokerProvisionalEstimate({
  intake,
  file,
  disabled = false,
}: {
  intake: SourceIntake;
  file: File | null;
  disabled?: boolean;
}) {
  const [context, setContext] = useState<ProvisionalContext | null>(null);
  const [selected, setSelected] = useState<Record<string, ProvisionalChoice>>({});
  const [mode, setMode] = useState<ProvisionalAssumptions["schedule_mode"]>(null);
  const [result, setResult] = useState<ProvisionalResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const key = `${intake.id}:${intake.head_seq}:${intake.manifest_digest}:${
    file ? `${file.name}:${file.size}:${file.lastModified}` : "no-file"
  }`;

  function invalidate() {
    generation.current++;
    controller.current?.abort();
    controller.current = null;
    setResult(null);
    setBusy(false);
    setError("");
  }
  // biome-ignore lint/correctness/useExhaustiveDependencies: the intake/original key is the reset trigger.
  useEffect(() => {
    invalidate();
    setContext(null);
    setSelected({});
    setMode(null);
  }, [key]);
  useEffect(
    () => () => {
      generation.current++;
      controller.current?.abort();
    },
    [],
  );

  const assumptions: ProvisionalAssumptions = {
    version: "source_intake_provisional_v2",
    schedule_mode: mode,
    selections: (context?.required_assumptions ?? [])
      .filter((requirement) => selected[requirement.requirement_id])
      .map((requirement) => ({
        requirement_id: requirement.requirement_id,
        source_references: requirement.source_references,
        choice: selected[requirement.requirement_id],
      }))
      .sort((left, right) =>
        left.requirement_id < right.requirement_id
          ? -1
          : left.requirement_id > right.requirement_id
            ? 1
            : 0,
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
        const fresh = await provisionalRequest<ProvisionalContext>(
          operation,
          intake,
          file,
          abort.signal,
        );
        if (generation.current !== epoch) return;
        if (!contextMatches(fresh, intake))
          throw new Error("Контекст не соответствует выбранному source-intake или оригиналу.");
        setContext(fresh);
      } else if (context) {
        const fresh = await provisionalRequest<ProvisionalResult>(
          operation,
          intake,
          file,
          abort.signal,
          context,
          assumptions,
          operation === "export" ? (previous ?? undefined) : undefined,
        );
        if (generation.current !== epoch) return;
        if (
          !resultMatches(fresh, context, assumptions) ||
          (operation === "export" && fresh.result_fingerprint !== previous?.result_fingerprint)
        ) {
          throw new Error("Результат не соответствует текущему контексту и явным допущениям.");
        }
        setResult(fresh);
        if (operation === "export" && fresh.status === "provisional") {
          const url = URL.createObjectURL(
            new Blob([JSON.stringify(fresh, null, 2)], { type: "application/json" }),
          );
          const link = document.createElement("a");
          link.href = url;
          link.download = "broker-statement-provisional.json";
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

  const blocked = disabled || busy;
  return (
    <section className={styles.panel} aria-label="Предварительная доходность по source-intake">
      <h3>Предварительная доходность по source-intake</h3>
      <p className={styles.qualification}>
        Read-only оценка по нативным EOD-итогам журнала и явно выбранным допущениям. Это не S3, не
        Close, не финансовый Apply и не годовая доходность. Неизвестные движения не считаются нулём:
        каждое допущение выбирается отдельно.
      </p>
      {intake.state.account_id === null && (
        <p role="status">
          Разбор не привязан к Hermes-счёту. Расчёт идёт в source-native гипотетической области
          одного выбранного оригинала: без финансового Apply, принятия счёта или утверждения полноты
          портфеля. Сопоставление с Hermes-счётом не выполняется.
        </p>
      )}
      {!file && (
        <p role="status">
          Оригинал XML не выбран. Выбери тот же неизменённый файл; после перезагрузки журнал хранит
          наблюдения, но не сами байты.
        </p>
      )}
      <button type="button" disabled={blocked || !file} onClick={() => void run("context")}>
        Рассчитать наблюдаемые величины
      </button>
      {busy && <p role="status">Перепроверяем оригинал и журнал…</p>}
      {error && <p role="alert">{error}</p>}
      {context && (
        <>
          <h4>Наблюдаемые величины брокера</h4>
          <div className={styles.facts}>
            <p>
              {formatDate(context.t0)} · бумаги:{" "}
              {statementMoney(context.observed.positions_value_opening_kopecks)} · RUB cash:{" "}
              {statementMoney(context.observed.cash_opening_kopecks)} · итого:{" "}
              {statementMoney(context.observed.total_opening_kopecks)}
            </p>
            <p>
              {formatDate(context.t1)} · бумаги:{" "}
              {statementMoney(context.observed.positions_value_closing_kopecks)} · RUB cash:{" "}
              {statementMoney(context.observed.cash_closing_kopecks)} · итого:{" "}
              {statementMoney(context.observed.total_closing_kopecks)}
            </p>
            <p>
              <strong>
                Изменение стоимости по отчёту брокера:{" "}
                {statementMoney(context.observed.reported_value_change_kopecks)}
              </strong>{" "}
              — это не доходность.
            </p>
            {context.observed.cash && (
              <p className={styles.note}>
                RUB cash source: {context.observed.cash.beginning_amount ?? "—"} →{" "}
                {context.observed.cash.ending_amount ?? "—"} RUB
              </p>
            )}
            <p className={styles.note}>
              Область сценария:{" "}
              {context.scope === "native_source"
                ? `нативный счёт строк ${context.native_source_account ?? "—"}; Hermes-счёт не задан`
                : `Hermes-счёт #${context.account_id ?? "—"}`}
            </p>
          </div>
          <details>
            <summary>Ограничения наблюдаемых величин ({context.limitations.length})</summary>
            <ul>
              {context.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          </details>
          {context.observed.positions.length > 0 && (
            <details open>
              <summary>Исходные стоимости бумаг</summary>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>ISIN</th>
                    <th>Начало, source</th>
                    <th>Конец, source</th>
                  </tr>
                </thead>
                <tbody>
                  {context.observed.positions.map((position) => (
                    <tr key={position.source_reference}>
                      <td>{position.isin}</td>
                      <td>{position.beginning_value ?? "—"}</td>
                      <td>{position.ending_value ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.note}>
                Source-значения показаны как в отчёте; итоги выше пересчитаны в копейки без
                округления.
              </p>
            </details>
          )}
          {context.known_payouts.length > 0 && (
            <details>
              <summary>Распознанные купоны/НКД (отдельно)</summary>
              <ul>
                {context.known_payouts.map((payout) => (
                  <li key={payout.source_reference}>
                    {payout.kind === "coupon_paid_candidate" ? "Купон" : "НКД"} ·{" "}
                    {formatDate(payout.event_date)} · {payout.source_amount} RUB · не добавлено к
                    внешним движениям
                  </li>
                ))}
              </ul>
            </details>
          )}
          <h4>Внешние движения</h4>
          {context.candidates.length === 0 ? (
            <p>Распознанных входящих кандидатов нет. Это не доказательство отсутствия движений.</p>
          ) : (
            <ul>
              {context.candidates.map((candidate) => (
                <li key={candidate.source_reference}>
                  {formatDate(candidate.event_date)} · +{candidate.source_amount} RUB · дата
                  проводки, внешность для портфеля не доказана
                </li>
              ))}
            </ul>
          )}
          {context.hard_blockers.length > 0 && (
            <div role="alert" className={styles.blocked}>
              <p>Предварительный расчёт заблокирован:</p>
              <ul>
                {context.hard_blockers.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
          <h4>Явные допущения</h4>
          {context.required_assumptions.map((requirement) => (
            <div key={requirement.requirement_id} className={styles.requirement}>
              <label>
                {SLOTS[requirement.slot]} · {requirement.subject}
                <select
                  aria-label={requirement.requirement_id}
                  value={selected[requirement.requirement_id] ?? ""}
                  disabled={disabled}
                  onChange={(event) => {
                    invalidate();
                    setSelected((current) => ({
                      ...current,
                      [requirement.requirement_id]: event.target.value as ProvisionalChoice,
                    }));
                  }}
                >
                  <option value="">Не выбрано</option>
                  {requirement.choices.map((choice) => (
                    <option key={choice} value={choice}>
                      {CHOICES[choice]}
                    </option>
                  ))}
                </select>
              </label>
              {selected[requirement.requirement_id] && (
                <p>{CHOICES[selected[requirement.requirement_id]]}</p>
              )}
              <details>
                <summary>Точный состав ссылок ({requirement.source_references.length})</summary>
                <ul>
                  {requirement.source_references.map((reference) => (
                    <li key={reference}>{reference}</li>
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
              disabled={disabled}
              onChange={(event) => {
                invalidate();
                setMode((event.target.value as typeof mode) || null);
              }}
            >
              <option value="">Не выбран</option>
              <option value="dated">Явный датированный график</option>
              <option value="explicit_empty">Явно пустой график</option>
            </select>
          </label>
          <button
            type="button"
            disabled={blocked || context.hard_blockers.length > 0}
            onClick={() => void run("evaluate")}
          >
            Рассчитать предварительный сценарий
          </button>
          {result && (
            <section aria-label="Результат предварительного расчёта">
              {result.status === "provisional" ? (
                <>
                  <p className={styles.rate}>
                    {formatStatementPercent(result.scenario_rate_fraction)} · за фактический период,
                    не аннулизировано
                  </p>
                  <p>
                    <strong>
                      Сценарный результат после выбранных внешних движений:{" "}
                      {statementMoney(result.scenario_result_kopecks)}
                    </strong>
                  </p>
                  <p>
                    Изменение по отчёту брокера:{" "}
                    {statementMoney(result.reported_value_change_kopecks)} — не доходность.
                    Сценарий: V1 − V0 − выбранные внешние движения; это не фактическая прибыль и не
                    V0 × ставка.
                  </p>
                  {result.alternatives.length > 0 && (
                    <div>
                      <h4>Альтернативная интерпретация</h4>
                      <ul>
                        {result.alternatives.map((alternative) => (
                          <li key={alternative.label}>
                            {alternative.label}:{" "}
                            {formatStatementPercent(alternative.scenario_rate_fraction)} ·{" "}
                            {statementMoney(alternative.scenario_result_kopecks)}. Это не граница
                            фактической доходности.
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <p>
                  {result.status === "needs_assumptions"
                    ? "Выбери все необходимые допущения и режим графика."
                    : `Расчёт заблокирован: ${result.reason_codes.join(", ")}`}
                </p>
              )}
              <h4>Выбранные допущения</h4>
              <ul>
                {result.assumptions.selections.map((selection) => (
                  <li key={selection.requirement_id}>{CHOICES[selection.choice]}</li>
                ))}
              </ul>
              <h4>Ограничения</h4>
              <ul>
                {result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </section>
          )}
          <button
            type="button"
            disabled={busy || result?.status !== "provisional"}
            onClick={() => void run("export")}
          >
            Экспорт предварительного расчёта JSON
          </button>
          <details>
            <summary>Полный контекст и fingerprints</summary>
            <pre>{JSON.stringify(context, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
