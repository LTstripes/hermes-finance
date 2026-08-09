import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CapitalHistoryPoint } from "../../api/types";
import { formatMoney } from "../../lib/format";
import { rub } from "../../lib/money";
import { PassiveIncomeChart } from "./PassiveIncomeChart";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ height: 280, width: 600 }}>{children}</div>
    ),
  };
});

function point(year: number, month: number, amount: string): CapitalHistoryPoint {
  return {
    year,
    month,
    reporting_month_id: year * 100 + month,
    liquid_capital_net: rub("0.00"),
    passive_income_actual: rub(amount),
  };
}

const baseProps = {
  average: "50000.00",
  complete12m: false,
  countMonths: 3,
  forecast: "62000.00",
  goal: "100000.00",
  points: [point(2031, 1, "45000.00"), point(2031, 2, "52000.00"), point(2031, 3, "53000.00")],
};

describe("PassiveIncomeChart", () => {
  it("renders an empty state when there are no closed months", () => {
    render(<PassiveIncomeChart {...baseProps} points={[]} />);
    expect(screen.getByText("Нет закрытых месяцев")).toBeInTheDocument();
  });

  it("renders the chart region for closed-month history", () => {
    render(<PassiveIncomeChart {...baseProps} />);
    expect(
      screen.getByRole("region", {
        name: /Фактический и прогнозный пассивный доход по закрытым месяцам/,
      }),
    ).toBeInTheDocument();
  });

  it("shows the incomplete-history note with the month count", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={3} />);
    expect(
      screen.getByText(/Среднее за доступный период\. Учтено 3 месяца из 12\./),
    ).toBeInTheDocument();
  });

  it("uses correct plural forms for the month count", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={11} />);
    expect(screen.getByText(/Учтено 11 месяцев из 12\./)).toBeInTheDocument();
    render(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={2} />);
    expect(screen.getByText(/Учтено 2 месяца из 12\./)).toBeInTheDocument();
  });

  it("omits the incomplete-history note when the window is complete", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m={true} countMonths={12} />);
    expect(screen.queryByText(/Среднее за доступный период/)).not.toBeInTheDocument();
  });

  it("shows legend values for average, forecast and goal", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m={true} countMonths={12} />);
    const legendValue = (text: string) =>
      screen.getByText((_, el) => el?.tagName === "STRONG" && el.textContent === text);
    expect(screen.getByText("Факт")).toBeInTheDocument();
    expect(screen.getByText(/Среднее/)).toBeInTheDocument();
    expect(screen.getByText(/Прогноз/)).toBeInTheDocument();
    expect(screen.getByText(/Цель/)).toBeInTheDocument();
    expect(legendValue(formatMoney("50000.00"))).toBeInTheDocument();
    expect(legendValue(formatMoney("62000.00"))).toBeInTheDocument();
    expect(legendValue(formatMoney("100000.00"))).toBeInTheDocument();
  });

  it("shows the gap note when the history has a missing month", () => {
    const gapped = [point(2031, 1, "45000.00"), point(2031, 3, "53000.00")];
    render(<PassiveIncomeChart {...baseProps} points={gapped} />);
    expect(screen.getByText(/без интерполяции/)).toBeInTheDocument();
  });
});
