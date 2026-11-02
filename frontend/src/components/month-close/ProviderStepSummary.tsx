import type { GuidedCloseStep } from "../../api/monthCloseWorkflow";
import { Badge } from "../ui";
import { closeOwnerCopy } from "./ownerCopy";

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
  if (step.id !== "actual_payouts") return null;

  const available = step.evidence_summary.available === true;
  if (!available) {
    return (
      <div
        className={`monthly-close__step-summary${compact ? " monthly-close__step-summary--compact" : ""}`}
      >
        <Badge tone="info">Нужно действие</Badge>
        <span>{closeOwnerCopy(step.why)}</span>
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
        {staleCount} · отменены: {retractedCount}. Это выборочные строки из выписки, а не все данные
        внешнего источника.
      </span>
    </div>
  );
}
