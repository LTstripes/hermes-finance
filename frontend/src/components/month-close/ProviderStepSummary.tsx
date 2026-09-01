import type { BrokerReconciliationResponse } from "../../api/brokerReconciliation";
import type { BrokerPositionRow, BrokerSnapshotPreview } from "../../api/brokerSnapshot";
import type { GuidedCloseStep } from "../../api/monthCloseWorkflow";
import { Badge, DataValue } from "../ui";

export type AlfaSnapshotCounts = {
  matched: number;
  providerOnly: number;
  unresolved: number;
  money: number;
};

export type AlfaApplyOutcome = {
  selectedCount: number;
  unchangedCount: number;
  attentionCount: number;
};

function isSafePosition(row: BrokerPositionRow): boolean {
  return (
    Boolean(row.fingerprint) &&
    !row.is_money &&
    (row.status === "matched" || row.status === "provider_only")
  );
}

export function summarizeAlfaSnapshot(preview: BrokerSnapshotPreview): AlfaSnapshotCounts {
  const money =
    preview.positions.filter((row) => row.is_money === true).length + preview.cash.length;
  const matched = preview.positions.filter(
    (row) => row.status === "matched" && isSafePosition(row),
  ).length;
  const providerOnly = preview.positions.filter(
    (row) => row.status === "provider_only" && isSafePosition(row),
  ).length;
  const unresolved = preview.positions.filter(
    (row) => row.is_money !== true && !isSafePosition(row),
  ).length;
  return { matched, providerOnly, unresolved, money };
}

function alfaPreviewHasError(preview: BrokerSnapshotPreview): boolean {
  return Boolean(
    preview.error_code ||
      preview.status === "non_applicable" ||
      !preview.eligible_for_apply ||
      preview.snapshot_status !== "complete" ||
      (preview.diagnostics.compatibility_state !== "compatible" &&
        preview.diagnostics.compatibility_state !== ""),
  );
}

function alfaTone(state: "success" | "partial" | "error"): "ok" | "info" | "stale" {
  if (state === "success") return "ok";
  if (state === "partial") return "info";
  return "stale";
}

export function AlfaSnapshotSummary({
  preview,
  outcome,
  error,
}: {
  preview: BrokerSnapshotPreview | null;
  outcome: AlfaApplyOutcome | null;
  error: string | null;
}) {
  if (!preview && !outcome && !error) return null;

  const counts = preview ? summarizeAlfaSnapshot(preview) : null;
  const state = outcome
    ? outcome.attentionCount > 0
      ? "partial"
      : "success"
    : error || (preview && alfaPreviewHasError(preview))
      ? "error"
      : counts && (preview?.status === "conflicts" || counts.unresolved > 0)
        ? "partial"
        : "success";

  const copy = outcome
    ? outcome.attentionCount > 0
      ? `Выбранные позиции применены: ${outcome.selectedCount}. Ещё ${outcome.attentionCount} строк требуют внимания; они не изменены.`
      : `Выбранные позиции применены: ${outcome.selectedCount}. Из них без изменений: ${outcome.unchangedCount}.`
    : state === "error"
      ? "Пригодный базовый срез не получен. Повтори явный запрос Alfa PRO; данные месяца не изменены."
      : state === "partial"
        ? "Предпросмотр содержит безопасные и требующие внимания строки. Применяй только выбранные безопасные позиции; весь портфель не синхронизируется автоматически."
        : "Предпросмотр готов. Данные месяца ещё не изменены: применение остаётся отдельным явным действием.";

  return (
    <aside
      className="monthly-close__provider-summary"
      aria-label="Результат шага Alfa PRO"
      role="status"
    >
      <div className="monthly-close__provider-summary-heading">
        <strong>Базовый срез Alfa PRO</strong>
        <Badge tone={alfaTone(state)}>
          {state === "success"
            ? "Готово"
            : state === "partial"
              ? "Частичный результат"
              : "Нужно внимание"}
        </Badge>
      </div>
      <p>{copy}</p>
      {counts ? (
        <div className="monthly-close__provider-summary-grid">
          <DataValue label="Сопоставлено" value={counts.matched} />
          <DataValue label="Нет локальной позиции" value={counts.providerOnly} />
          <DataValue label="Требуют внимания" value={counts.unresolved} />
          <DataValue label="Денежные строки исключены" value={counts.money} />
        </div>
      ) : null}
      {error ? <span className="muted">Подробности доступны в диагностике панели.</span> : null}
    </aside>
  );
}

const RECONCILIATION_STATES = [
  "matched",
  "differs",
  "missing_local",
  "missing_provider",
  "unresolved",
] as const;

function reconciliationCounts(result: BrokerReconciliationResponse): Record<string, number> {
  return result.rows.reduce<Record<string, number>>((counts, row) => {
    counts[row.state] = (counts[row.state] ?? 0) + 1;
    return counts;
  }, {});
}

function reconciliationHasError(result: BrokerReconciliationResponse): boolean {
  return Boolean(
    result.error_code ||
      result.status === "non_applicable" ||
      result.stale ||
      result.compatibility_state !== "compatible" ||
      result.snapshot_status !== "complete",
  );
}

export function ReconciliationSummary({
  result,
  error,
}: {
  result: BrokerReconciliationResponse | null;
  error: string | null;
}) {
  if (!result && !error) return null;

  const counts = result ? reconciliationCounts(result) : {};
  const attentionCount = RECONCILIATION_STATES.filter((state) => state !== "matched").reduce(
    (sum, state) => sum + (counts[state] ?? 0),
    0,
  );
  const state =
    error || (result && reconciliationHasError(result))
      ? "error"
      : attentionCount > 0
        ? "partial"
        : "success";
  const copy =
    state === "error"
      ? "Сверка не признана применимой. Повтори явную проверку после устранения причины; локальные данные не изменены."
      : state === "partial"
        ? `Сверка выполнена: совпадает ${counts.matched ?? 0}, требуют внимания ${attentionCount}. Это только сравнение; данные не изменены.`
        : "Сверка выполнена: все полученные строки совпадают. Это только сравнение; данные не изменены.";

  return (
    <aside
      className="monthly-close__provider-summary"
      aria-label="Результат сверки Alfa PRO"
      role="status"
    >
      <div className="monthly-close__provider-summary-heading">
        <strong>Сверка Alfa PRO</strong>
        <Badge tone={alfaTone(state)}>
          {state === "success"
            ? "Совпадает"
            : state === "partial"
              ? "Требует внимания"
              : "Не применима"}
        </Badge>
      </div>
      <p>{copy}</p>
      {result ? (
        <div className="monthly-close__provider-summary-grid">
          <DataValue label="Совпадает" value={counts.matched ?? 0} />
          <DataValue label="Отличается" value={counts.differs ?? 0} />
          <DataValue label="Нет локальной позиции" value={counts.missing_local ?? 0} />
          <DataValue label="Нет позиции у брокера" value={counts.missing_provider ?? 0} />
          <DataValue label="Не сопоставлено" value={counts.unresolved ?? 0} />
        </div>
      ) : null}
      {error ? <span className="muted">Подробности доступны в диагностике сверки.</span> : null}
    </aside>
  );
}

function evidenceCount(step: GuidedCloseStep, key: string): number {
  const value = step.evidence_summary[key];
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : 0;
}

export function MonthlyCloseStepSummary({
  step,
  compact = false,
}: {
  step: GuidedCloseStep;
  compact?: boolean;
}) {
  if (
    step.id !== "alfa_baseline" &&
    step.id !== "actual_payouts" &&
    step.id !== "broker_reconciliation"
  ) {
    return null;
  }

  if (step.id === "broker_reconciliation") {
    return (
      <div
        className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
      >
        <Badge tone="info">Только по запросу</Badge>
        <span>
          Проверка запускается отдельной кнопкой и не сохраняется в этом экране. После перезапуска
          её нужно запросить снова.
        </span>
      </div>
    );
  }

  if (step.id === "actual_payouts") {
    const available = step.evidence_summary.available === true;
    if (!available) {
      return (
        <div
          className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
        >
          <Badge tone="info">Нужно действие</Badge>
          <span>{step.why}</span>
        </div>
      );
    }

    const selectedCount = evidenceCount(step, "selected_count");
    const matchingCount = evidenceCount(step, "matching_count");
    const staleCount = evidenceCount(step, "stale_count");
    const retractedCount = evidenceCount(step, "retracted_count");
    const attentionCount = staleCount + retractedCount;
    return (
      <div
        className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
      >
        <Badge tone={attentionCount > 0 ? "stale" : "ok"}>
          {attentionCount > 0 ? "Нужно обновить" : "Сохранено"}
        </Badge>
        <span>
          Выплат сохранено: {selectedCount} · совпадают: {matchingCount} · требуют внимания:{" "}
          {staleCount} · отменены: {retractedCount}. Это выборочные данные PDF, не полный охват
          провайдера.
        </span>
      </div>
    );
  }

  const available = step.evidence_summary.available === true;
  if (!available) {
    return (
      <div
        className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
      >
        <Badge tone="info">Нужно действие</Badge>
        <span>{step.why}</span>
      </div>
    );
  }

  const selectedCount = evidenceCount(step, "selected_count");
  const matchingCount = evidenceCount(step, "matching_count");
  const staleCount = evidenceCount(step, "stale_count");
  return (
    <div
      className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
    >
      <Badge tone={staleCount > 0 ? "stale" : "ok"}>
        {staleCount > 0 ? "Нужно обновить" : "Сохранено"}
      </Badge>
      <span>
        Выбранных позиций: {selectedCount} · совпадают: {matchingCount} · требуют внимания:{" "}
        {staleCount}. Это не полное покрытие провайдера.
      </span>
    </div>
  );
}
