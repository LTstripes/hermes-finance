import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CapitalHistoryPoint } from "../../api/types";
import { rub } from "../../lib/money";
import { CapitalChart } from "./CapitalChart";

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
    liquid_capital_net: rub(amount),
    passive_income_actual: rub("0.00"),
  };
}

describe("CapitalChart", () => {
  it("renders an empty state when there are no closed months", () => {
    render(<CapitalChart points={[]} />);
    expect(screen.getByText("Нет закрытых месяцев")).toBeInTheDocument();
  });

  it("renders the chart region for closed-month history", () => {
    render(<CapitalChart points={[point(2031, 1, "100000.00"), point(2031, 2, "120000.00")]} />);
    expect(
      screen.getByRole("region", {
        name: /Динамика ликвидного капитала по закрытым месяцам/,
      }),
    ).toBeInTheDocument();
  });

  it("shows the gap note when the history has a missing month", () => {
    render(<CapitalChart points={[point(2031, 1, "100000.00"), point(2031, 3, "140000.00")]} />);
    expect(screen.getByText(/без интерполяции/)).toBeInTheDocument();
  });

  it("omits the gap note for a continuous history", () => {
    render(<CapitalChart points={[point(2031, 1, "100000.00"), point(2031, 2, "120000.00")]} />);
    expect(screen.queryByText(/без интерполяции/)).not.toBeInTheDocument();
  });
});
