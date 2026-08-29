import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCapitalComposition } from "../api/analytics";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import { getPortfolioXirr } from "../api/performance";
import { rub } from "../lib/money";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("../api/analytics", () => ({ getCapitalComposition: vi.fn() }));
vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/performance", () => ({ getPortfolioXirr: vi.fn() }));

const capitalHistory = {
  asset_classes: ["cash", "deposits", "stocks", "bonds", "gold_other"],
  points: [
    {
      reporting_month_id: 2,
      year: 2031,
      month: 2,
      snapshot_date: "2031-02-28",
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
    },
  ],
};

beforeEach(() => {
  vi.mocked(getCapitalComposition).mockResolvedValue(capitalHistory);
  vi.mocked(listMonths).mockResolvedValue([
    {
      id: 1,
      year: 2031,
      month: 1,
      status: "closed",
      snapshot_date: "2031-01-31",
      source: "manual",
    },
    { id: 2, year: 2031, month: 2, status: "draft", snapshot_date: "2031-02-28", source: "manual" },
  ]);
  vi.mocked(getDashboard).mockResolvedValue({
    mortgage: { mortgage_balance: rub("0.00"), coverage_pct: null, gap: rub("0.00") },
    asset_allocation: [{ asset_class: "cash", amount: rub("100.00") }],
    result_by_account: [],
    result_by_instrument_class: [],
  });
});

describe("AnalyticsPage", () => {
  it("loads the history route and exposes amount/share modes plus drill-downs", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Состав капитала во времени" }),
    ).toBeInTheDocument();
    expect(getCapitalComposition).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(getDashboard).toHaveBeenCalledWith(2, expect.anything()));
    expect(screen.getByRole("heading", { name: "Текущее распределение" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Результат инвестиций" })).toBeInTheDocument();

    const shareButton = screen.getByRole("button", { name: "Доля %" });
    await user.click(shareButton);
    expect(shareButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Сумма ₽" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("shows backend XIRR unavailability without calculating a value", async () => {
    vi.mocked(listMonths).mockResolvedValue([
      {
        id: 2,
        year: 2031,
        month: 2,
        status: "closed",
        snapshot_date: "2031-02-28",
        source: "manual",
      },
      {
        id: 1,
        year: 2031,
        month: 1,
        status: "closed",
        snapshot_date: "2031-01-31",
        source: "manual",
      },
    ]);
    vi.mocked(getPortfolioXirr).mockResolvedValue({
      metric: "xirr",
      scope: "portfolio",
      performance_currency: "RUB",
      value: null,
      value_unit: "percentage_points",
      annualized: true,
      period: { start_date: "2031-01-31", end_date: "2031-02-28" },
      availability: "not_computable",
      quality: "unavailable",
      reason_codes: ["not_computable_xirr_root_ambiguity"],
    });

    render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/однозначность корня для этой истории не подтверждена/),
    ).toBeInTheDocument();
    expect(screen.getByText("XIRR недоступен")).toBeInTheDocument();
    expect(screen.queryByText("not_computable_xirr_root_ambiguity", { exact: true })).toBeNull();
    expect(screen.queryByText("10,00%")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(getPortfolioXirr).toHaveBeenCalledWith("2031-01-31", "2031-02-28", expect.anything()),
    );
  });
});
