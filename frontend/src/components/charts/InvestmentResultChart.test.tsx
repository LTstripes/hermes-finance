import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AccountResultPoint, InstrumentClassResultPoint } from "../../api/types";
import { formatMoneyDelta } from "../../lib/format";
import { rub, sumMoneyAmounts } from "../../lib/money";
import { InvestmentResultChart } from "./InvestmentResultChart";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ height: 260, width: 420 }}>{children}</div>
    ),
  };
});

const broker: AccountResultPoint = {
  account_id: 1,
  account_name: "Брокер",
  account_type: "brokerage",
  cash_income: rub("870.00"),
  unrealized_result: rub("1000.00"),
};

const iis: AccountResultPoint = {
  account_id: 2,
  account_name: "ИИС",
  account_type: "iis",
  cash_income: rub("0.00"),
  unrealized_result: rub("-500.00"),
};

const bondClass: InstrumentClassResultPoint = {
  instrument_type: "bond",
  market_value: rub("11000.00"),
  cost_basis: rub("10000.00"),
  unrealized_result: rub("1000.00"),
  realized_result: rub("870.00"),
};

describe("InvestmentResultChart", () => {
  it("renders the chart section and both accessibility tables", () => {
    render(<InvestmentResultChart accounts={[broker, iis]} classes={[bondClass]} />);
    expect(
      screen.getByRole("region", { name: /Результат по счетам и классам активов/ }),
    ).toBeInTheDocument();
    const accountTable = screen.getByRole("table", { name: "Результат по счетам" });
    expect(within(accountTable).getByText("Брокер (Брокерский)")).toBeInTheDocument();
    expect(within(accountTable).getByText("ИИС (ИИС)")).toBeInTheDocument();
    const classTable = screen.getByRole("table", { name: "Результат по классам активов" });
    expect(within(classTable).getByText("Облигации")).toBeInTheDocument();
  });

  it("shows signed formatted amounts and per-row totals", () => {
    render(<InvestmentResultChart accounts={[broker, iis]} classes={[]} />);
    const cellWithText = (text: string) => screen.getByText((_, el) => el?.textContent === text);
    // broker: cash +870, unrealized +1000, total +1870
    expect(cellWithText(formatMoneyDelta("870.00"))).toBeInTheDocument();
    expect(cellWithText(formatMoneyDelta("1000.00"))).toBeInTheDocument();
    expect(cellWithText(formatMoneyDelta("1870.00"))).toBeInTheDocument();
    // iis: cash 0, unrealized −500, total −500 (two cells with the same value)
    expect(
      screen.getAllByText((_, el) => el?.textContent === formatMoneyDelta("-500.00")),
    ).toHaveLength(2);
  });

  it("shows a concise result interpretation note without implementation references", () => {
    render(<InvestmentResultChart accounts={[broker]} classes={[bondClass]} />);
    expect(
      screen.getByText(/Здесь показан денежный результат: полученные купоны, дивиденды и проценты/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Погашения облигаций и пополнения не считаются доходом/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/MASTER_SPEC|модифицированному Дитцу/)).toBeNull();
  });

  it("renders an empty state without accounts and classes", () => {
    render(<InvestmentResultChart accounts={[]} classes={[]} />);
    expect(screen.getByText("Нет данных о результате")).toBeInTheDocument();
  });

  it("shows the class table with realized and unrealized results", () => {
    render(<InvestmentResultChart accounts={[]} classes={[bondClass]} />);
    const classTable = screen.getByRole("table", { name: "Результат по классам активов" });
    const cellWithText = (text: string) =>
      within(classTable).getByText((_, el) => el?.textContent === text);
    expect(cellWithText(formatMoneyDelta("870.00"))).toBeInTheDocument();
    expect(cellWithText(formatMoneyDelta("1000.00"))).toBeInTheDocument();
    expect(
      cellWithText(formatMoneyDelta(sumMoneyAmounts(["870.00", "1000.00"]))),
    ).toBeInTheDocument();
  });
});
