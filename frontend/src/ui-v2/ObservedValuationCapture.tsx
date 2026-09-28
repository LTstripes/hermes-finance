import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiClientError } from "../api/client";
import { getPerformanceReadiness } from "../api/performance";
import {
  getValuationCaptures,
  submitValuationCapture,
  type ValuationCaptureRelation,
  type ValuationCaptureSide,
  type ValuationCaptures,
  type ValuationCaptureTarget,
} from "../api/valuationCapture";
import { queryKeys } from "../queryClient";
import { isReadinessFresh } from "./CapitalPerformanceSummary";
import type { PerformanceContext } from "./capitalPerformanceContext";
import { diagnosticCopy } from "./capitalPerformanceCopy";
import styles from "./UiV2CapitalPerformance.module.css";

/**
 * PUI-05 observed PRE/POST capture (issue #533). Values are entered exactly as
 * observed from a source; the client never derives them from a flow, a monthly
 * total or an interpolation, and never retries an ambiguous write.
 */

type CoverageChoice = "complete" | "unavailable" | "unknown";
type QualityChoice = "exact" | "unavailable" | "unknown";

export type CaptureDraft = {
  relation: ValuationCaptureRelation;
  total_value: string;
  performance_currency: string;
  coverage: CoverageChoice;
  quality: QualityChoice;
  provenance_kind: string;
  provenance_reference: string | null;
  notes: string | null;
};

const REASON_KEY: Record<string, string> = {
  not_computable_valuation_boundary_missing: "valuation_boundary",
  not_computable_valuation_boundary_order_unknown: "valuation_order",
};

function coverageLabel(value: ValuationCaptureSide["coverage"]): string {
  if (value === "complete") return "подтверждено";
  if (value === "unavailable") return "недоступно";
  return "не подтверждено";
}

function qualityLabel(value: ValuationCaptureSide["quality"]): string {
  if (value === "exact") return "точное";
  if (value === "unavailable") return "недоступно";
  return "не подтверждено";
}

function monthStatusLabel(value: string | null): string {
  if (value === "draft") return "черновик";
  if (value === "closed") return "закрыт";
  return "состояние отчёта неизвестно";
}

function targetKey(target: ValuationCaptureTarget): string {
  return target.boundary_group_id !== null
    ? `group:${target.boundary_group_id}`
    : `flow:${target.flow_ids.join(",")}`;
}

function targetTitle(target: ValuationCaptureTarget): string {
  return target.boundary_group_id !== null
    ? `Группа операций ${target.boundary_group_id}`
    : `Операция ${target.flow_ids.join(", ")}`;
}

function relationLabel(relation: ValuationCaptureRelation): string {
  return relation === "pre_external_flow" ? "PRE" : "POST";
}

function stateCopy(target: ValuationCaptureTarget, relation: ValuationCaptureRelation): string {
  const state = relation === "pre_external_flow" ? target.pre_state : target.post_state;
  if (state === "captured") return "записано и привязано к текущей версии цели";
  if (state === "stale")
    return "запись устарела: цель изменилась, при новом вводе она будет заменена";
  if (state === "ambiguous") return "несколько записей: пара неоднозначна";
  return "не записано";
}

function blockedCopy(reason: string | null): string {
  switch (reason) {
    case "ambiguous_sides":
      return "У цели уже несколько записей одной стороны. Пара неоднозначна; этот ввод её не исправляет.";
    case "group_membership_changed":
      return "Состав или дата группы изменились. Нужна явная замена группы; отдельного редактора групп пока нет.";
    case "target_identity_unavailable":
      return "Текущая идентичность цели недоступна (история участия или состав). Сначала исправьте её — ввод наблюдений заблокирован.";
    case "target_missing":
      return "Цель больше не существует в текущей версии данных. Перечитайте данные.";
    default:
      return "Ввод наблюдений для этой цели сейчас не поддерживается.";
  }
}

function SideEvidence({ side }: { side: ValuationCaptureSide }) {
  return (
    <p data-testid={`valuation-capture-side-${side.id}`}>
      {relationLabel(side.relation)}: {side.total_value.amount} {side.total_value.currency} ·
      покрытие: {coverageLabel(side.coverage)} · качество: {qualityLabel(side.quality)} · источник:{" "}
      {side.provenance_kind}
      {side.bound ? "" : " · не привязано к текущей версии"}
    </p>
  );
}

function CaptureForm({
  target,
  locked,
  save,
}: {
  target: ValuationCaptureTarget;
  locked: boolean;
  save: (target: ValuationCaptureTarget, draft: CaptureDraft) => Promise<void>;
}) {
  const relations = target.missing_relations;
  const [relation, setRelation] = useState<ValuationCaptureRelation | "">(
    relations.length === 1 ? relations[0] : "",
  );
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(target.performance_currency);
  const [coverageChoice, setCoverageChoice] = useState<CoverageChoice | "">("");
  const [provenanceKind, setProvenanceKind] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [attested, setAttested] = useState(false);

  const quality: QualityChoice | "" =
    coverageChoice === "complete" ? "exact" : coverageChoice === "" ? "" : coverageChoice;
  const valid =
    relation !== "" &&
    relations.includes(relation) &&
    /^\d+(\.\d{1,2})?$/.test(amount) &&
    /^[A-Za-z]{3}$/.test(currency.trim()) &&
    quality !== "" &&
    provenanceKind.trim().length > 0 &&
    provenanceKind.trim().length <= 64 &&
    reference.trim().length <= 128;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || !attested || locked || !coverageChoice || !quality) return;
        void save(target, {
          relation,
          total_value: amount,
          performance_currency: currency.trim().toUpperCase(),
          coverage: coverageChoice,
          quality,
          provenance_kind: provenanceKind.trim(),
          provenance_reference: reference.trim() || null,
          notes: notes.trim() || null,
        });
      }}
    >
      <fieldset disabled={locked} className={styles.compositionBlock}>
        <legend>Новое наблюдение для «{targetTitle(target)}»</legend>
        <p>
          Значение должно быть фактически наблюдённой стоимостью из источника до или после операции.
          Оно не рассчитывается из суммы потока, месячного итога или интерполяции.
        </p>
        <div className={styles.controls} onChange={() => setAttested(false)}>
          <label>
            Сторона
            <select
              aria-label="Сторона наблюдения"
              value={relation}
              onChange={(event) => setRelation(event.target.value as ValuationCaptureRelation | "")}
            >
              <option value="">Выберите явно</option>
              {relations.map((candidate) => (
                <option key={candidate} value={candidate}>
                  {relationLabel(candidate)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Точная сумма
            <input
              aria-label="Сумма наблюдения"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <label>
            Валюта
            <input
              aria-label="Валюта наблюдения"
              maxLength={3}
              value={currency}
              onChange={(event) => setCurrency(event.target.value)}
            />
          </label>
          <label>
            Полнота и точность
            <select
              aria-label="Полнота наблюдения"
              value={coverageChoice}
              onChange={(event) => setCoverageChoice(event.target.value as CoverageChoice | "")}
            >
              <option value="">Выберите явно</option>
              <option value="complete">Подтверждено полностью и точно (complete/exact)</option>
              <option value="unknown">Источник не подтверждён (unknown)</option>
              <option value="unavailable">Источник недоступен (unavailable)</option>
            </select>
          </label>
          <label>
            Источник (provenance)
            <input
              aria-label="Источник наблюдения"
              maxLength={64}
              value={provenanceKind}
              onChange={(event) => setProvenanceKind(event.target.value)}
            />
          </label>
          <label>
            Ссылка на источник (необязательно)
            <input
              aria-label="Ссылка на источник наблюдения"
              maxLength={128}
              value={reference}
              onChange={(event) => setReference(event.target.value)}
            />
          </label>
          <label className={styles.controlsFull}>
            Примечание (необязательно)
            <input
              aria-label="Примечание наблюдения"
              maxLength={2000}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
        </div>
        <label>
          <input
            type="checkbox"
            checked={attested}
            onChange={(event) => setAttested(event.target.checked)}
          />{" "}
          Я ввёл(а) фактически наблюдённую стоимость из источника; она не вычислена из потока и не
          взята из месячного итога
        </label>
        {target.reporting_month_status === "closed" ? (
          <p role="alert">
            Отчёт закрыт: сначала явно откройте его, затем введите наблюдение и закройте отчёт
            заново. Автоматического reopen нет.
          </p>
        ) : null}
        <button type="submit" className={styles.inlineButton} disabled={!valid || !attested}>
          Сохранить наблюдение
        </button>
      </fieldset>
    </form>
  );
}

function TargetBlock({
  target,
  locked,
  save,
}: {
  target: ValuationCaptureTarget;
  locked: boolean;
  save: (target: ValuationCaptureTarget, draft: CaptureDraft) => Promise<void>;
}) {
  const capability = target.capture_capability;
  const reasons = [...new Set(target.reason_codes)].map((code) =>
    diagnosticCopy(REASON_KEY[code] ?? "unknown_reason"),
  );
  const canCapture =
    capability === "available" && target.form_token !== null && target.missing_relations.length > 0;
  return (
    <article
      className={styles.compositionBlock}
      data-testid={`valuation-capture-target-${targetKey(target)}`}
    >
      <h4>{targetTitle(target)}</h4>
      <p className={styles.periodLine}>
        {target.event_date} ·{" "}
        {target.scope === "account" ? `счёт ${target.account_id}` : "портфель"} · отчёт{" "}
        {target.reporting_month_id ?? "—"} ({monthStatusLabel(target.reporting_month_status)}) ·
        валюта расчёта: {target.performance_currency}
      </p>
      {reasons.map((reason) => (
        <p className={styles.capabilityNote} key={reason.title}>
          {reason.title}: {reason.detail}
        </p>
      ))}
      <p>
        PRE — {stateCopy(target, "pre_external_flow")}; POST —{" "}
        {stateCopy(target, "post_external_flow")}.
      </p>
      {target.pre_external_flow.map((side) => (
        <SideEvidence key={side.id} side={side} />
      ))}
      {target.post_external_flow.map((side) => (
        <SideEvidence key={side.id} side={side} />
      ))}
      {target.missing_relations.length > 0 ? (
        <p data-testid={`valuation-capture-missing-${targetKey(target)}`}>
          Не хватает: {target.missing_relations.map(relationLabel).join(", ")}. Нужен ввод
          фактически наблюдённой стоимости из источника.
        </p>
      ) : null}
      {canCapture ? <CaptureForm target={target} locked={locked} save={save} /> : null}
      {capability === "requires_reopen" ? (
        <p role="status">
          Отчёт закрыт. Явно откройте затронутые отчёты, перечитайте данные, введите наблюдение и
          закройте отчёты заново. Автоматического reopen/reclose нет.
        </p>
      ) : null}
      {capability === "not_implemented" || capability === "unsupported" ? (
        <p role="status">{blockedCopy(target.blocked_reason)}</p>
      ) : null}
      {capability === null && target.missing_relations.length === 0 ? (
        <p>Обе стороны записаны для текущей версии цели.</p>
      ) : null}
    </article>
  );
}

export function ObservedValuationCapture({ context }: { context: PerformanceContext }) {
  const client = useQueryClient();
  const busy = useRef(false);
  const [locked, setLocked] = useState(false);
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["valuation-captures", context.start, context.end, context.scope, context.accountId],
    queryFn: ({ signal }) =>
      getValuationCaptures(context.start, context.end, context.scope, context.accountId, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const fresh = (data: ValuationCaptures | undefined) =>
    data !== undefined &&
    data.start_date === context.start &&
    data.end_date === context.end &&
    data.scope === context.scope &&
    data.account_id === context.accountId &&
    isReadinessFresh(data.readiness, context);

  const save = async (target: ValuationCaptureTarget, draft: CaptureDraft) => {
    const before = query.data;
    if (
      busy.current ||
      locked ||
      !before ||
      !fresh(before) ||
      query.isFetching ||
      query.isError ||
      target.form_token === null ||
      target.material_signature === null
    ) {
      return;
    }
    busy.current = true;
    setLocked(true);
    setNotice("Сохраняем наблюдение и перечитываем диагностику…");
    let writeAcknowledged = false;
    try {
      const saved = await submitValuationCapture({
        scope: context.scope,
        account_id: context.scope === "account" ? context.accountId : null,
        start_date: context.start,
        end_date: context.end,
        form_token: target.form_token,
        external_flow_id: target.boundary_group_id === null ? (target.flow_ids[0] ?? null) : null,
        boundary_group_id: target.boundary_group_id,
        relation: draft.relation,
        expected_material_signature: target.material_signature,
        total_value: draft.total_value,
        performance_currency: draft.performance_currency,
        coverage: draft.coverage,
        quality: draft.quality,
        provenance_kind: draft.provenance_kind,
        provenance_reference: draft.provenance_reference,
        notes: draft.notes,
        attested: true,
      });
      writeAcknowledged = true;
      // Reread the capture targets and both canonical final solvers; a save is
      // never displayed as a successful calculation.
      await client.invalidateQueries();
      const result = await query.refetch();
      const reread = result.data;
      if (result.isError || !reread || !fresh(reread)) throw new Error("readback");
      const rereadTarget = reread.targets.find(
        (candidate) => targetKey(candidate) === targetKey(target),
      );
      const savedId = saved.captured?.id;
      const savedSide =
        rereadTarget && savedId !== undefined
          ? [...rereadTarget.pre_external_flow, ...rereadTarget.post_external_flow].find(
              (side) => side.id === savedId,
            )
          : undefined;
      if (!savedSide?.bound || savedSide.relation !== draft.relation) {
        throw new Error("readback");
      }
      const readiness = await client.fetchQuery({
        queryKey: queryKeys.performanceReadiness(
          context.start,
          context.end,
          context.scope,
          context.accountId,
        ),
        queryFn: ({ signal }) =>
          getPerformanceReadiness(
            context.start,
            context.end,
            context.scope,
            context.accountId,
            signal,
          ),
        staleTime: 0,
      });
      if (!isReadinessFresh(readiness, context)) throw new Error("readback");
      setNotice(
        "Запись подтверждена: значение сохранено как фактически наблюдённое и привязано к текущей версии цели. Готовность и итоговые XIRR/TWRR перечитаны; сохранение не означает доступность расчёта.",
      );
      setLocked(false);
    } catch (error) {
      await client.invalidateQueries();
      setNotice(
        writeAcknowledged
          ? "Сервер принял запись, но повторная проверка не завершилась. Перечитайте данные и проверьте результат перед следующим действием."
          : error instanceof ApiClientError && error.status === 409
            ? "Форма устарела, отчёт закрыт или такая сторона уже записана. Вслепую не повторяйте: перечитайте данные и проверьте состояние."
            : "Результат записи не подтверждён. Не повторяйте запись вслепую: перечитайте данные и проверьте наличие изменения.",
      );
    } finally {
      busy.current = false;
    }
  };

  const data = query.data;
  return (
    <section
      id="performance-capture"
      aria-label="Наблюдения PRE/POST"
      className={`${styles.composition} ${styles.preparation}`}
    >
      <h3>Наблюдения стоимости до и после операции (PRE/POST)</h3>
      <p>
        Фактически наблюдённые стоимости на дату операции. Пары PRE/POST привязываются к текущей
        версии одной операции или явной группы; устаревшая форма будет отклонена. Ввод не
        выполняется, пока источник, валюта и полнота не подтверждены явно.
      </p>
      {notice ? <p role="status">{notice}</p> : null}
      <button
        type="button"
        className={styles.inlineButton}
        disabled={busy.current || query.isFetching}
        onClick={() =>
          void query.refetch().then((result) => {
            if (!result.isError && result.data && fresh(result.data)) {
              setLocked(false);
              setNotice(
                "Данные перечитаны. Проверьте результат предыдущей записи перед новым подтверждением.",
              );
            }
          })
        }
      >
        Перечитать данные наблюдений
      </button>
      {query.isError ? (
        <p role="alert">
          Не удалось прочитать цели наблюдений. Запись недоступна; прошлые данные не показываются
          как текущие.
        </p>
      ) : query.isFetching ? (
        <p>Читаем цели наблюдений…</p>
      ) : data && fresh(data) ? (
        data.targets.length === 0 ? (
          <p className={styles.periodLine}>
            Для выбранного интервала и охвата нет операций, которым нужна пара PRE/POST. Пустой
            список не подтверждает полноту истории.
          </p>
        ) : (
          data.targets.map((target) => (
            <TargetBlock
              key={`${targetKey(target)}:${target.material_signature ?? "none"}:${target.form_token ?? "none"}`}
              target={target}
              locked={locked || query.isFetching}
              save={save}
            />
          ))
        )
      ) : (
        <p role="alert">Ответ не соответствует выбранному интервалу и охвату.</p>
      )}
      <p className={styles.periodLine}>
        Оставшиеся причины недоступности показаны в диагностике выше. Сохранение наблюдения не
        гарантирует TWRR, пока есть другие блокеры; XIRR остаётся доступным независимо.
      </p>
    </section>
  );
}
