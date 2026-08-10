import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AssetAllocationPoint } from "../../api/types";
import { formatMoney } from "../../lib/format";
import { rub } from "../../lib/money";
import { AssetAllocationChart } from "./AssetAllocationChart";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ height: 240, width: 400 }}>{children}</div>
    ),
  };
});

function allocation(entries: Array<[string, string]>): AssetAllocationPoint[] {
  return entries.map(([asset_class, amount]) => ({ asset_class, amount: rub(amount) }));
}

const sample = allocation([
  ["cash", "20000.00"],
  ["deposits", "100000.00"],
  ["stocks", "30000.00"],
  ["bonds", "11000.00"],
  ["gold_other", "5000.00"],
]);

describe("AssetAllocationChart", () => {
  it("renders the donut section and the accessibility table", () => {
    render(<AssetAllocationChart allocation={sample} />);
    expect(
      screen.getByRole("region", {
        name: /Распределение ликвидных активов по классам/,
      }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Акции")).toBeInTheDocument();
    expect(within(table).getByText("Облигации")).toBeInTheDocument();
    expect(within(table).getByText("Депозиты")).toBeInTheDocument();
    expect(within(table).getByText("Наличные")).toBeInTheDocument();
    expect(within(table).getByText("Золото и прочее")).toBeInTheDocument();
  });

  it("hides zero-value classes from the table and the chart", () => {
    const withZero = allocation([
      ["cash", "0.00"],
      ["deposits", "100000.00"],
      ["stocks", "0.00"],
    ]);
    render(<AssetAllocationChart allocation={withZero} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("Депозиты")).toBeInTheDocument();
    expect(within(table).queryByText("Наличные")).not.toBeInTheDocument();
    expect(within(table).queryByText("Акции")).not.toBeInTheDocument();
  });

  it("shows formatted amounts, shares and a 100% total row", () => {
    render(<AssetAllocationChart allocation={sample} />);
    const cellWithText = (text: string) => screen.getByText((_, el) => el?.textContent === text);
    expect(cellWithText(formatMoney("166000.00"))).toBeInTheDocument(); // total
    expect(cellWithText("100%")).toBeInTheDocument();
    expect(cellWithText("60,2%")).toBeInTheDocument(); // deposits share
  });

  it("keeps totals and shares exact above Number.MAX_SAFE_INTEGER kopecks", () => {
    render(
      <AssetAllocationChart
        allocation={allocation([
          ["cash", "90071992547409.93"],
          ["deposits", "90071992547409.93"],
        ])}
      />,
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText(formatMoney("180143985094819.86"))).toBeInTheDocument();
    expect(within(table).getAllByText("50,0%")).toHaveLength(2);
  });

  it("renders an empty state when every class is zero", () => {
    render(
      <AssetAllocationChart
        allocation={allocation([
          ["cash", "0.00"],
          ["stocks", "0.00"],
        ])}
      />,
    );
    expect(screen.getByText("Нет активов")).toBeInTheDocument();
  });

  it("renders an empty state for an empty allocation", () => {
    render(<AssetAllocationChart allocation={[]} />);
    expect(screen.getByText("Нет активов")).toBeInTheDocument();
  });

  it("falls back to the raw class name for unknown classes", () => {
    const unknown = allocation([["crypto", "1234.00"]]);
    render(<AssetAllocationChart allocation={unknown} />);
    expect(within(screen.getByRole("table")).getByText("crypto")).toBeInTheDocument();
  });
});
