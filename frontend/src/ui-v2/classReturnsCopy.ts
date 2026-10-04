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
const REASONS: Record<string, { state: State; detail: string }> = {
  unsupported_class: {
    state: "unsupported",
    detail:
      "Доходность этого класса пока не поддерживается. Дополнительные подтверждения не откроют расчёт.",
  },
  unsupported_currency: {
    state: "unsupported",
    detail: "Этот расчёт поддерживает только подтверждённые оценки в RUB.",
  },
  membership_incomplete_or_changed: {
    state: "incomplete",
    detail: "История участия счетов неполна или изменилась.",
  },
  historical_universe_empty: {
    state: "incomplete",
    detail: "Исторический состав портфеля не подтверждён.",
  },
  exact_endpoint_missing_or_ambiguous: {
    state: "incomplete",
    detail: "Нет однозначной оценки на точную дату границы периода.",
  },
  reporting_month_not_closed: {
    state: "incomplete",
    detail: "Отчёт на границе периода ещё не закрыт.",
  },
  historical_class_unknown: {
    state: "incomplete",
    detail: "Историческая принадлежность позиций к классу не подтверждена.",
  },
  historical_class_reclassified: {
    state: "corrected",
    detail: "Классификация позиций менялась в выбранном периоде.",
  },
  archived_position_incomplete: {
    state: "incomplete",
    detail: "Подтверждения по архивным позициям неполны.",
  },
  cash_flow_class_unknown: {
    state: "incomplete",
    detail: "Класс денежной операции не подтверждён.",
  },
  known_cash_crossing: {
    state: "corrected",
    detail:
      "Есть денежное движение через границу класса: интервал без таких движений не подтверждён.",
  },
  in_kind_class_unknown: {
    state: "incomplete",
    detail: "Класс неденежного движения не подтверждён.",
  },
  external_in_kind_crossing: {
    state: "corrected",
    detail: "Есть внешнее неденежное движение через границу класса.",
  },
  internal_transfer_ambiguous: {
    state: "incomplete",
    detail: "Внутреннее перемещение не подтверждено однозначно.",
  },
  position_set_changed: {
    state: "corrected",
    detail: "Состав позиций изменился: подтверждение интервала без движений неприменимо.",
  },
  position_quantity_changed: {
    state: "corrected",
    detail: "Количество позиций изменилось: подтверждение интервала без движений неприменимо.",
  },
  class_endpoint_empty: {
    state: "undefined",
    detail: "На границе периода нет позиций класса для расчёта доходности.",
  },
  no_crossing_coverage_missing_or_ambiguous: {
    state: "incomplete",
    detail:
      "Нет однозначного подтверждения отсутствия движений через границу класса за весь точный интервал.",
  },
  opening_class_inventory_not_complete: {
    state: "incomplete",
    detail: "Полный состав класса на начальную дату не подтверждён.",
  },
  closing_class_inventory_not_complete: {
    state: "incomplete",
    detail: "Полный состав класса на конечную дату не подтверждён.",
  },
  no_crossing_coverage_not_complete: {
    state: "incomplete",
    detail: "Подтверждение отсутствия движений через границу класса не имеет статуса «полное».",
  },
  no_crossing_material_changed: {
    state: "corrected",
    detail:
      "Исходные факты изменились после подтверждения интервала. Подтверждение больше не действует.",
  },
  not_computable_xirr_no_valid_root: {
    state: "undefined",
    detail: "Для подтверждённого ряда не существует допустимого значения XIRR.",
  },
  not_computable_twrr_zero_or_negative_denominator: {
    state: "undefined",
    detail: "TWRR не определён при нулевом или отрицательном начальном капитале.",
  },
  not_computable_xirr_convergence_failed: {
    state: "solver",
    detail: "Метод XIRR не сошёлся. Это численное ограничение, а не нехватка операций.",
  },
  not_computable_xirr_root_ambiguity: {
    state: "solver",
    detail:
      "Метод XIRR не может выбрать однозначный корень. Это ограничение метода, а не нехватка операций.",
  },
};

export function classReasonCopy(code: string): string {
  return REASONS[code]?.detail ?? "API сообщил причину недоступности без описания для этого кода.";
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
