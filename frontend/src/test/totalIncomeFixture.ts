import type { TotalIncome, TotalIncomeWindow } from "../api/totalIncome";

const m = (amount: string) => ({ amount, currency: "RUB" });

/** Echoes the requested latest CLOSED id like the real API; defaults to the income fixture. */
export function totalIncomeFixture(latestClosedReportId = 91): TotalIncome {
  const window: TotalIncomeWindow = {
    from: "2031-01",
    to: "2031-07",
    months_observed: 4,
    months_used: ["2031-02", "2031-04", "2031-05", "2031-07"],
    salary_months: 4,
    passive_months: 3,
    bonus_months: 4,
    bonus_target_months: 12,
    estimate_months: 1,
    salary_sum: m("400000.00"),
    passive_sum: m("60000.00"),
    bonus_sum: m("0.00"),
    other_sum: m("900.00"),
    salary_monthly_average: m("100000.00"),
    passive_monthly_average: m("20000.00"),
    bonus_smoothed_monthly: m("0.00"),
    monthly_average: m("120000.00"),
    current_level: m("125000.00"),
    current_passive_months: 3,
    total_net: m("460000.00"),
    passive_share_pct: "16.7",
    warnings: [
      "Зарплата за 1 мес оценена по апрельской (04.2031)",
      "Пассивка учитывается с 04.2031",
    ],
  };
  return {
    latest_closed_report_id: latestClosedReportId,
    configured_start_month: "2031-04",
    points: [2, 4, 5, 7].map((month, index) => ({
      reporting_month_id: 88 + index,
      year: 2031,
      month,
      salary_net: m("100000.00"),
      salary_is_estimate: index === 0,
      bonus_net: m("0.00"),
      passive_actual: index === 0 ? null : m("20000.00"),
      other_net: m("225.00"),
    })),
    windows: {
      calendar_year: structuredClone(window),
      rolling_12: { ...structuredClone(window), from: "2030-08" },
      all: { ...structuredClone(window), from: "2031-02" },
    },
  };
}
