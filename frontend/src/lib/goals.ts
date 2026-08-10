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
    return "Прогресс считается по backend-прогнозу чистого пассивного дохода в месяц.";
  }
  if (goalType === "capital" && calculationMode === "liquid_capital_net") {
    return "Прогресс считается по ликвидному капиталу выбранного отчётного месяца.";
  }
  return "Для этого типа/режима backend пока не рассчитывает прогресс и дату достижения.";
}
