import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CapitalHistoryPoint } from "../../api/types";
import { rub } from "../../lib/money";
import { buildCapitalChartData, CapitalChart } from "./CapitalChart";

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

describe("buildCapitalChartData", () => {
  it("keeps contiguous months as one continuous series", () => {
    const data = buildCapitalChartData([point(2031, 1, "100000.00"), point(2031, 2, "120000.00")]);
    expect(data).toHaveLength(2);
    expect(data.every((d) => d.rubles != null)).toBe(true);
    expect(data.map((d) => d.key)).toEqual(["2031-01", "2031-02"]);
  });

  it("breaks the line when a month is missing (no interpolation)", () => {
    const data = buildCapitalChartData([point(2031, 1, "100000.00"), point(2031, 3, "140000.00")]);
    expect(data).toHaveLength(3);
    expect(data[1].rubles).toBeNull();
    expect(data[0].rubles).not.toBeNull();
    expect(data[2].rubles).not.toBeNull();
  });

  it("treats December→January of next year as contiguous", () => {
    const data = buildCapitalChartData([point(2030, 12, "90000.00"), point(2031, 1, "100000.00")]);
    expect(data).toHaveLength(2);
    expect(data.every((d) => d.rubles != null)).toBe(true);
  });

  it("breaks December→February (January skipped)", () => {
    const data = buildCapitalChartData([point(2030, 12, "90000.00"), point(2031, 2, "110000.00")]);
    expect(data).toHaveLength(3);
    expect(data[1].rubles).toBeNull();
  });

  it("returns an empty array for no points", () => {
    expect(buildCapitalChartData([])).toEqual([]);
  });
});

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
