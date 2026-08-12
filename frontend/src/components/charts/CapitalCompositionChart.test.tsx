import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CapitalCompositionPoint } from "../../api/types";
import { rub } from "../../lib/money";
import { CapitalCompositionChart, CapitalCompositionTooltip } from "./CapitalCompositionChart";
import { buildCapitalCompositionSeries } from "../../lib/capitalComposition";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ height: 360, width: 600 }}>{children}</div>
    ),
  };
});

function point(month: number): CapitalCompositionPoint {
  return {
    reporting_month_id: month,
    year: 2031,
    month,
    snapshot_date: `2031-${String(month).padStart(2, "0")}-28`,
    allocation: [
      { asset_class: "cash", amount: rub("100.00") },
      { asset_class: "deposits", amount: rub("300.00") },
      { asset_class: "stocks", amount: rub("100.00") },
      { asset_class: "bonds", amount: rub("0.00") },
      { asset_class: "gold_other", amount: rub("0.00") },
    ],
    liquid_assets_total: rub("500.00"),
    included_debts: rub("50.00"),
    liquid_capital_net: rub("450.00"),
  };
}

describe("CapitalCompositionChart", () => {
  it("renders the primary composition region and explicit gap note", () => {
    render(
      <CapitalCompositionChart
        assetClasses={["cash", "deposits", "stocks", "bonds", "gold_other"]}
        mode="amount"
        points={[point(1), point(3)]}
      />,
    );

    expect(
      screen.getByRole("region", { name: "Состав ликвидных активов по закрытым месяцам" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Пропуски означают неизвестную историю/)).toBeInTheDocument();
  });

  it("renders an empty state when the API has no closed points", () => {
    render(<CapitalCompositionChart assetClasses={[]} mode="share" points={[]} />);

    expect(screen.getByText("Нет закрытых месяцев")).toBeInTheDocument();
  });

  it("shows the month breakdown and separate net/debt values in the tooltip", () => {
    const datum = buildCapitalCompositionSeries(
      [point(1)],
      ["cash", "deposits", "stocks", "bonds", "gold_other"],
    )[0];
    const tooltipProps = {
      active: true,
      assetClasses: ["cash", "deposits", "stocks", "bonds", "gold_other"],
      mode: "amount" as const,
      payload: [{ payload: datum }],
    } as unknown as Parameters<typeof CapitalCompositionTooltip>[0];
    const { container } = render(<CapitalCompositionTooltip {...tooltipProps} />);

    expect(container.querySelector(".composition-tooltip > strong")?.textContent).toContain(
      "Январь",
    );
    expect(screen.getByText("Всего активов")).toBeInTheDocument();
    expect(screen.getByText("Капитал нетто")).toBeInTheDocument();
    expect(screen.getByText("Включённые долги")).toBeInTheDocument();
  });
});
