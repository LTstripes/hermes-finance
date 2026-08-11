export const GOAL_TYPES = [
  "passive_income",
  "capital",
  "expense_coverage",
  "mortgage_coverage",
  "other",
] as const;

export const GOAL_TYPE_LABELS: Record<string, string> = {
  passive_income: "Пассивный доход",
  capital: "Капитал",
  expense_coverage: "Покрытие расходов",
  mortgage_coverage: "Покрытие ипотеки",
  other: "Другая цель",
};

export const GOAL_STATUS_LABELS: Record<string, string> = {
  achieved: "Достигнута",
  not_projectable: "Без прогноза",
  inactive: "Неактивна",
  unsupported: "Без расчёта",
};

export const GOAL_CALCULATION_MODE_LABELS: Record<string, string> = {
  monthly_net_passive_income: "Чистый пассивный доход в месяц",
  liquid_capital_net: "Ликвидный капитал",
  expense_coverage_ratio: "Покрытие расходов пассивным доходом",
  mortgage_coverage_ratio: "Покрытие ипотеки ликвидными активами",
  custom: "Другой способ расчёта",
};

export const GOAL_REASON_LABELS: Record<string, string> = {
  no_trajectory_model: "Недостаточно данных, чтобы надёжно спрогнозировать будущую дату.",
  goal_inactive: "Цель сейчас неактивна.",
  unsupported_goal_type: "Для этого типа цели автоматический расчёт пока не поддерживается.",
  unsupported_calculation_mode: "Для выбранного способа расчёта прогноз пока не поддерживается.",
};

export function goalCalculationModeLabel(value: string): string {
  return GOAL_CALCULATION_MODE_LABELS[value] ?? "Другой способ расчёта";
}

export function goalReasonLabel(value: string): string {
  return GOAL_REASON_LABELS[value] ?? "Для текущих параметров дополнительный прогноз недоступен.";
}

export function defaultCalculationMode(goalType: string): string {
  switch (goalType) {
    case "passive_income":
      return "monthly_net_passive_income";
    case "capital":
      return "liquid_capital_net";
    case "expense_coverage":
      return "expense_coverage_ratio";
    case "mortgage_coverage":
      return "mortgage_coverage_ratio";
    default:
      return "custom";
  }
}

export function goalForecastSupportLabel(goalType: string, calculationMode: string): string {
  if (goalType === "passive_income" && calculationMode === "monthly_net_passive_income") {
    return "Прогресс считается по прогнозу чистого пассивного дохода в месяц.";
  }
  if (goalType === "capital" && calculationMode === "liquid_capital_net") {
    return "Прогресс считается по ликвидному капиталу выбранного отчётного месяца.";
  }
  return "Для этого типа или способа расчёта прогресс и дата достижения пока не рассчитываются.";
}
