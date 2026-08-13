import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CapitalHistoryPoint } from "../../api/types";
import { formatMoney } from "../../lib/format";
import { rub } from "../../lib/money";
import { PassiveIncomeChart } from "./PassiveIncomeChart";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="bar-chart">{children}</div>
  ),
  Bar: ({ name }: { name?: string }) => <div data-name={name} data-testid="actual-bars" />,
  ReferenceLine: ({ y }: { y?: number }) => <div data-testid="reference-line" data-y={y} />,
  CartesianGrid: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

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

  it("renders monthly actual as bars while forecast and goal remain references", () => {
    render(<PassiveIncomeChart {...baseProps} />);

    expect(
      screen.getByRole("region", {
        name: /Фактический пассивный доход по закрытым месяцам с прогнозом и целью/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("actual-bars")).toHaveAttribute("data-name", "Факт");
    expect(screen.getAllByTestId("reference-line")).toHaveLength(3);
  });

  it("keeps incomplete rolling-window detail behind compact help", async () => {
    const user = userEvent.setup();
    render(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={3} />);

    expect(screen.getByText(/Среднее: 3 месяца из 12/)).toBeInTheDocument();
    expect(screen.queryByText(/rolling-окно/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Как считается среднее пассивного дохода" }));
    expect(
      screen.getByText(/Среднее рассчитано по закрытым месяцам в окне до 12 месяцев/),
    ).toBeInTheDocument();
  });

  it("uses correct plural forms for the compact month count", () => {
    const { rerender } = render(
      <PassiveIncomeChart {...baseProps} complete12m={false} countMonths={11} />,
    );
    expect(screen.getByText(/Среднее: 11 месяцев из 12/)).toBeInTheDocument();

    rerender(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={2} />);
    expect(screen.getByText(/Среднее: 2 месяца из 12/)).toBeInTheDocument();

    rerender(<PassiveIncomeChart {...baseProps} complete12m={false} countMonths={1} />);
    expect(screen.getByText(/Среднее: 1 месяц из 12/)).toBeInTheDocument();
  });

  it("omits the incomplete-window indicator when the rolling window is complete", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m countMonths={12} />);
    expect(screen.queryByText(/Среднее: 12 месяцев из 12/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Как считается среднее пассивного дохода" })).toBeNull();
  });

  it("labels fact-derived average separately from forecast and goal", () => {
    render(<PassiveIncomeChart {...baseProps} complete12m countMonths={12} />);
    const legendValue = (text: string) =>
      screen.getByText((_, element) => element?.tagName === "STRONG" && element.textContent === text);

    expect(screen.getByText("Факт по месяцам")).toBeInTheDocument();
    expect(screen.getByText(/Среднее факта/)).toBeInTheDocument();
    expect(screen.getByText(/Прогноз/)).toBeInTheDocument();
    expect(screen.getByText(/Цель/)).toBeInTheDocument();
    expect(legendValue(formatMoney("50000.00"))).toBeInTheDocument();
    expect(legendValue(formatMoney("62000.00"))).toBeInTheDocument();
    expect(legendValue(formatMoney("100000.00"))).toBeInTheDocument();
  });

  it("keeps missing closed months as visible gaps without interpolation", async () => {
    const user = userEvent.setup();
    const gapped = [point(2031, 1, "45000.00"), point(2031, 3, "53000.00")];
    render(<PassiveIncomeChart {...baseProps} points={gapped} />);

    expect(screen.getByText("Есть пропуски в истории")).toBeInTheDocument();
    expect(screen.queryByText(/не интерполируется/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Как отображаются пропуски в истории" }));
    expect(screen.getByText(/Значение между соседними месяцами не интерполируется/)).toBeInTheDocument();
  });
});
