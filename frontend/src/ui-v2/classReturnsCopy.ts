import { reasonCopy } from "../lib/reasonCopy";
import type { ClassReturnMetric, ClassReturns } from "../api/types";

type State = "unsupported" | "incomplete" | "corrected" | "solver" | "undefined";

const STATE_LABELS: Record<State, string> = {
  unsupported: "Расчёт не поддерживается",
  incomplete: "Подтверждения неполны",
  corrected: "Подтверждения изменены или отозваны",
  solver: "Ограничение расчётного метода",
  undefined: "Доходность не определена",
};

// Exact accepted codes, never substring classification or financial inference.
const REASONS: Record<string, { state: State }> = {
  mybroker_class_reconciliation_required: {
    state: "incomplete",
  },
  unsupported_class: {
    state: "unsupported",
  },
  unsupported_currency: {
    state: "unsupported",
  },
  membership_incomplete_or_changed: {
    state: "incomplete",
  },
  historical_universe_empty: {
    state: "incomplete",
  },
  exact_endpoint_missing_or_ambiguous: {
    state: "incomplete",
  },
  reporting_month_not_closed: {
    state: "incomplete",
  },
  historical_class_unknown: {
    state: "incomplete",
  },
  historical_class_reclassified: {
    state: "corrected",
  },
  archived_position_incomplete: {
    state: "incomplete",
  },
  cash_flow_class_unknown: {
    state: "incomplete",
  },
  known_cash_crossing: {
    state: "corrected",
  },
  in_kind_class_unknown: {
    state: "incomplete",
  },
  external_in_kind_crossing: {
    state: "corrected",
  },
  internal_transfer_ambiguous: {
    state: "incomplete",
  },
  position_set_changed: {
    state: "corrected",
  },
  position_quantity_changed: {
    state: "corrected",
  },
  class_endpoint_empty: {
    state: "undefined",
  },
  no_crossing_coverage_missing_or_ambiguous: {
    state: "incomplete",
  },
  opening_class_inventory_not_complete: {
    state: "incomplete",
  },
  closing_class_inventory_not_complete: {
    state: "incomplete",
  },
  no_crossing_coverage_not_complete: {
    state: "incomplete",
  },
  no_crossing_material_changed: {
    state: "corrected",
  },
  not_computable_xirr_no_valid_root: {
    state: "undefined",
  },
  not_computable_twrr_zero_or_negative_denominator: {
    state: "undefined",
  },
  not_computable_xirr_convergence_failed: {
    state: "solver",
  },
  not_computable_xirr_root_ambiguity: {
    state: "solver",
  },
};

export function classReasonCopy(code: string): string {
  return reasonCopy(code, { surface: "class" }).message;
}

export function classMetricState(metric: ClassReturnMetric, row: ClassReturns): string {
  if (metric.availability === "available" && metric.quality === "exact") return "Доступна";
  if (metric.reason_source === "solver") {
    const states = metric.reason_codes.map((code) => REASONS[code]?.state);
    return STATE_LABELS[states.includes("undefined") ? "undefined" : "solver"];
  }
  if (row.eligibility_status === "unsupported") return STATE_LABELS.unsupported;
  if (
    row.coverage_state === "invalidated" ||
    row.coverage_state === "revoked" ||
    (row.coverage_state === "unknown" && row.coverage_provenance.length > 0)
  ) {
    return STATE_LABELS.corrected;
  }
  const states = metric.reason_codes.map((code) => REASONS[code]?.state);
  const state = (["unsupported", "corrected", "undefined", "incomplete"] as const).find(
    (candidate) => states.includes(candidate),
  );
  return state ? STATE_LABELS[state] : "Причина недоступности не распознана";
}

export function classCoverageCopy(state: string): string {
  switch (state) {
    case "complete":
      return "Полное";
    case "unknown":
      return "Не подтверждено";
    case "revoked":
      return "Отозвано";
    case "invalidated":
      return "Недействительно после изменения фактов";
    default:
      return "Статус не распознан";
  }
}

/** Reject another class/period/currency/basis; never shorten the requested interval. */
export function isClassReturnsFresh(
  row: ClassReturns,
  assetClass: string,
  start: string,
  end: string,
): boolean {
  if (
    row.asset_class !== assetClass ||
    row.requested_period.start_date !== start ||
    row.requested_period.end_date !== end ||
    row.performance_currency !== "RUB" ||
    row.valuation_basis !== "persisted_rub_market_value_kopecks" ||
    (row.actual_covered_period.start_date !== null &&
      row.actual_covered_period.start_date !== start) ||
    (row.actual_covered_period.end_date !== null && row.actual_covered_period.end_date !== end)
  )
    return false;
  return (["xirr", "twrr"] as const).every((kind) => {
    const metric = row[kind];
    if (metric.value_unit !== "percentage_points" || metric.annualized !== (kind === "xirr"))
      return false;
    if (metric.availability !== "available") return true;
    return (
      row.eligibility_status === "eligible" &&
      row.actual_covered_period.start_date === start &&
      row.actual_covered_period.end_date === end &&
      metric.quality === "exact" &&
      typeof metric.value === "string" &&
      /^-?\d+(\.\d+)?$/.test(metric.value)
    );
  });
}
