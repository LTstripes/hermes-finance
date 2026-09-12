import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCapitalComposition } from "../api/analytics";
import { getDashboard } from "../api/dashboard";
import { listMonths } from "../api/months";
import { getPerformanceAttribution, getPortfolioTwrr, getPortfolioXirr } from "../api/performance";
import type { PerformanceAttribution } from "../api/types";
import { rub } from "../lib/money";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("../api/analytics", () => ({ getCapitalComposition: vi.fn() }));
vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/performance", () => ({
  getPerformanceAttribution: vi.fn(),
  getPortfolioTwrr: vi.fn(),
  getPortfolioXirr: vi.fn(),
}));

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

const closedMonths = [
  {
    id: 2,
    year: 2031,
    month: 2,
    status: "closed" as const,
    snapshot_date: "2031-02-28",
    source: "manual",
  },
  {
    id: 1,
    year: 2031,
    month: 1,
    status: "closed" as const,
    snapshot_date: "2031-01-31",
    source: "manual",
  },
];

function attribution(overrides: Partial<PerformanceAttribution> = {}): PerformanceAttribution {
  return {
    contract: "PERF04A",
    contract_version: 1,
    metric: "value_change_after_external_flows",
    grain: "selected_scope",
    scope: "portfolio",
    account_id: null,
    period: { start_date: "2031-01-31", end_date: "2031-02-28" },
    performance_currency: "RUB",
    availability: "not_computable",
    quality: "unavailable",
    opening_value: null,
    closing_value: null,
    value: null,
    external_flow_summary: { contributions: null, withdrawals: null, signed_total: null },
    evidence: {
      opening_valuation: { availability: "not_computable", reason_codes: [] },
      closing_valuation: { availability: "not_computable", reason_codes: [] },
      scope_membership: { status: "unknown", reason_codes: [] },
      cash_boundary_coverage: { status: "unknown", reason_codes: [] },
      in_kind_boundary_coverage: { status: "unknown", reason_codes: [] },
      external_flows: { status: "unknown", reason_codes: [] },
    },
    reason_codes: ["not_computable_valuation_boundary_missing"],
    ...overrides,
  };
}

beforeEach(() => {
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
    reason_codes: ["not_computable_valuation_boundary_missing"],
  });
  vi.mocked(getPortfolioTwrr).mockResolvedValue({
    metric: "twrr",
    scope: "portfolio",
    account_id: null,
    performance_currency: "RUB",
    value: null,
    value_unit: "percentage_points",
    annualized: false,
    period: { start_date: "2031-01-31", end_date: "2031-02-28" },
    availability: "not_computable",
    quality: "unavailable",
    reason_codes: ["not_computable_valuation_boundary_missing"],
  });
  vi.mocked(getPerformanceAttribution).mockResolvedValue(attribution());
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
    const user = userEvent.setup();
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

    const xirrHeading = await screen.findByRole("heading", { name: "XIRR портфеля" });
    const xirrPanel = xirrHeading.closest("section");
    expect(xirrPanel).not.toBeNull();
    if (!xirrPanel) throw new Error("XIRR panel was not rendered");
    expect(within(xirrPanel).queryByText(/однозначность корня/)).toBeNull();
    await user.click(within(xirrPanel).getByText("Почему недоступно"));
    expect(
      await within(xirrPanel).findByText(/однозначность корня для этой истории не подтверждена/),
    ).toBeInTheDocument();
    expect(screen.getByText("XIRR недоступен")).toBeInTheDocument();
    expect(screen.queryByText("not_computable_xirr_root_ambiguity", { exact: true })).toBeNull();
    expect(screen.queryByText("10,00%")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(getPortfolioXirr).toHaveBeenCalledWith("2031-01-31", "2031-02-28", expect.anything()),
    );
    expect(screen.getByText("TWRR недоступен")).toBeInTheDocument();
    expect(
      screen
        .getByRole("heading", { name: "Результат инвестиций" })
        .compareDocumentPosition(xirrHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await waitFor(() =>
      expect(getPortfolioTwrr).toHaveBeenCalledWith("2031-01-31", "2031-02-28", expect.anything()),
    );
  });

  it.each([
    { label: "positive", amount: "283.50", rendered: /\+283,50/ },
    { label: "negative", amount: "-42.75", rendered: /−42,75/ },
    { label: "zero", amount: "0.00", rendered: /0\s*RUB/ },
  ])("renders the backend's exact $label bridge value", async ({ amount, rendered }) => {
    vi.mocked(listMonths).mockResolvedValue(closedMonths);
    vi.mocked(getPerformanceAttribution).mockResolvedValue(
      attribution({
        availability: "available",
        quality: "exact",
        opening_value: { amount: "1000.00", currency: "RUB" },
        closing_value: { amount: "9999.00", currency: "RUB" },
        value: { amount, currency: "RUB" },
        external_flow_summary: {
          contributions: { amount: "100.00", currency: "RUB" },
          withdrawals: { amount: "50.00", currency: "RUB" },
          signed_total: { amount: "50.00", currency: "RUB" },
        },
        reason_codes: [],
      }),
    );

    render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Изменение стоимости после внешних потоков",
    });
    const panel = heading.closest("section");
    expect(panel).not.toBeNull();
    if (!panel) throw new Error("Value bridge panel was not rendered");

    await waitFor(() => expect(within(panel).getByText(rendered)).toBeInTheDocument());
    expect(
      within(panel).getByText("Это изменение стоимости, а не доходность."),
    ).toBeInTheDocument();
    expect(within(panel).queryByText("XIRR портфеля")).toBeNull();
    expect(within(panel).queryByText("TWRR портфеля")).toBeNull();
    expect(within(panel).queryByText("Прибыль")).toBeNull();
    expect(within(panel).queryByText(/8.?949/)).toBeNull();
    await waitFor(() =>
      expect(getPerformanceAttribution).toHaveBeenCalledWith(
        "2031-01-31",
        "2031-02-28",
        expect.anything(),
      ),
    );
  });

  it("shows unavailable attribution as unavailable and never as zero", async () => {
    vi.mocked(listMonths).mockResolvedValue(closedMonths);
    vi.mocked(getPerformanceAttribution).mockResolvedValue(
      attribution({
        reason_codes: ["not_computable_external_flows_incomplete"],
      }),
    );

    render(
      <MemoryRouter>
        <AnalyticsPage />
      </MemoryRouter>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Изменение стоимости после внешних потоков",
    });
    const panel = heading.closest("section");
    expect(panel).not.toBeNull();
    if (!panel) throw new Error("Value bridge panel was not rendered");

    await waitFor(() => expect(within(panel).getByText("Значение недоступно")).toBeInTheDocument());
    await userEvent.setup().click(within(panel).getByText("Почему недоступно"));
    expect(
      await within(panel).findByText("История внешних пополнений и выводов за период неполна."),
    ).toBeInTheDocument();
    expect(within(panel).queryByText(/0,00/)).toBeNull();
    expect(within(panel).queryByText("not_computable_external_flows_incomplete")).toBeNull();
  });
});
