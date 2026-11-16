import type { IncomeEntry, MonthSummary } from "../api/types";

const money = (amount: string) => ({ amount, currency: "RUB" });
export function salaryFixture(monthId: number) {
  const summary: MonthSummary = {
    month: {
      id: monthId,
      year: 2031,
      month: 5,
      status: "closed",
      snapshot_date: "2031-05-31",
      source: "manual",
    },
    salary_tax: {
      tax: money("14000.01"),
      calculated_net: money("85999.99"),
      parts: [
        { rate_bps: 1300, taxable: money("49999.50"), tax: money("6499.94") },
        { rate_bps: 1500, taxable: money("50000.50"), tax: money("7500.07") },
      ],
    },
    salary_actual_net: money("85999.99"),
  };
  const salary: IncomeEntry = {
    id: 1,
    reporting_month_id: monthId,
    income_type: "salary",
    name: "Зарплата",
    gross_amount: money("100000.00"),
    tax_amount: money("1.00"),
    net_amount: money("85999.99"),
    received_at: null,
    is_recurring: true,
    include_in_cash_flow: true,
    include_in_passive_income: false,
    notes: null,
  };
  return { summary, salary };
}
