import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getRiskAllocation,
  type RiskAllocationResponse,
  type RiskConcentrationMetric,
  type RiskMetricSupport,
} from "../api/riskAllocation";
import { listMonths } from "../api/months";
import { createQueryClient } from "../queryClient";
import { RiskAllocationPage } from "./RiskAllocationPage";

vi.mock("../api/riskAllocation", () => ({ getRiskAllocation: vi.fn() }));
vi.mock("../api/months", () => ({ listMonths: vi.fn() }));

const money = (amount: string) => ({ amount, currency: "RUB" });
const supported: RiskMetricSupport = { status: "supported", reason_codes: [] };

function allocationMetric(
  overrides: Partial<RiskAllocationResponse["allocation_by_asset_class"]> = {},
) {
  return {
    support: supported,
    denominator: money("100000.00"),
    covered_amount: money("99500.00"),
    unallocated_amount: money("500.00"),
    coverage_pct: "99.50",
    items: [
      {
        key: "stock",
        label: "stock",
        amount: money("75000.00"),
        share_pct: "75.00",
        account_id: null,
        instrument_id: null,
        instrument_type: "stock",
      },
      {
        key: "unknown_asset_class",
        label: "Unknown asset class",
        amount: money("500.00"),
        share_pct: "0.50",
        account_id: null,
        instrument_id: null,
        instrument_type: null,
      },
    ],
    excluded: [],
    ...overrides,
  };
}

function concentrationMetric(
  overrides: Partial<RiskConcentrationMetric> = {},
): RiskConcentrationMetric {
  return {
    support: supported,
    denominator: money("100000.00"),
    top_n: 5,
    top_amount: money("75000.00"),
    top_share_pct: "75.00",
    items: [
      {
        key: "position:1",
        label: "Брокер / Старый актив",
        amount: money("75000.00"),
        share_pct: "75.00",
        account_id: 1,
        account_name: "Брокер",
        instrument_id: 10,
        instrument_name: "Старый актив",
        instrument_type: "stock",
        position_id: 1,
        event_count: null,
        is_approximate: false,
      },
    ],
    excluded: [],
    is_approximate: false,
    ...overrides,
  };
}

function response(monthId: number, empty = false): RiskAllocationResponse {
  const emptyAllocation = allocationMetric({
    denominator: money("0.00"),
    covered_amount: money("0.00"),
    unallocated_amount: money("0.00"),
    coverage_pct: null,
    items: [],
  });
  const emptyConcentration = concentrationMetric({
    denominator: money("0.00"),
    top_amount: money("0.00"),
    top_share_pct: null,
    items: [],
  });
  return {
    reporting_month_id: monthId,
    as_of_date: `2031-0${monthId}-28`,
    base_currency: "RUB",
    liquid_assets_total: money(empty ? "0.00" : "100000.00"),
    allocation_by_asset_class: empty ? emptyAllocation : allocationMetric(),
    allocation_by_account: empty
      ? emptyAllocation
      : allocationMetric({
          items: [
            { ...allocationMetric().items[0], key: "account:1", label: "Брокер", account_id: 1 },
          ],
        }),
    top_positions: empty ? emptyConcentration : concentrationMetric(),
    payout_concentration: empty
      ? emptyConcentration
      : concentrationMetric({
          items: [],
          denominator: money("0.00"),
          top_amount: money("0.00"),
          top_share_pct: null,
        }),
    redemption_concentration: empty
      ? emptyConcentration
      : concentrationMetric({
          items: [],
          denominator: money("0.00"),
          top_amount: money("0.00"),
          top_share_pct: null,
        }),
    support: {
      asset_class: supported,
      account: supported,
      issuer: { status: "unavailable", reason_codes: ["issuer_not_persisted"] },
      currency: { status: "unknown", reason_codes: ["currency_not_persisted"] },
      maturity: { status: "unavailable", reason_codes: ["maturity_not_persisted"] },
      broker: { status: "unavailable", reason_codes: ["broker_identity_not_persisted"] },
      bank: { status: "unavailable", reason_codes: ["bank_identity_not_persisted"] },
      top_positions: supported,
      payout: supported,
      redemption: supported,
    },
  };
}

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <RiskAllocationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
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
  vi.mocked(getRiskAllocation).mockImplementation(async (monthId) => response(monthId));
});

describe("RiskAllocationPage", () => {
  it("renders backend amounts, percentages, partial coverage and support states", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Top-5 позиций" })).toBeInTheDocument();
    expect(screen.getAllByText(/75\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("75,00%").length).toBeGreaterThan(0);
    expect(screen.getByText("Неизвестный класс активов")).toBeInTheDocument();
    expect(screen.getAllByText("Не распределено").length).toBeGreaterThan(0);
    expect(screen.getByText("Эмитент")).toBeInTheDocument();
    expect(screen.getAllByText("Недоступно").length).toBeGreaterThan(0);
    expect(screen.getByText("Валюта")).toBeInTheDocument();
    expect(screen.getByText("Неизвестно")).toBeInTheDocument();
    expect(getRiskAllocation).toHaveBeenCalledWith(2, 5, "v1", expect.any(AbortSignal));
  });

  it("does not show the previous month under a newly selected month", async () => {
    const user = userEvent.setup();
    vi.mocked(getRiskAllocation).mockImplementation(async (monthId) => {
      if (monthId === 1) await new Promise((resolve) => setTimeout(resolve, 50));
      return Promise.resolve(response(monthId));
    });
    renderPage();
    expect(await screen.findByText("Брокер / Старый актив")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Месяц"), "1");
    expect(screen.queryByText("Брокер / Старый актив")).not.toBeInTheDocument();
    expect(screen.getByText("Загружаем распределение выбранного месяца…")).toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.queryByText("Загружаем распределение выбранного месяца…"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Брокер / Старый актив")).toBeInTheDocument();
  });

  it("shows a clear empty portfolio state", async () => {
    vi.mocked(listMonths).mockResolvedValue([
      {
        id: 1,
        year: 2031,
        month: 1,
        status: "draft",
        snapshot_date: "2031-01-31",
        source: "manual",
      },
    ]);
    vi.mocked(getRiskAllocation).mockResolvedValue(response(1, true));
    renderPage();

    expect(await screen.findByText("Портфель пуст")).toBeInTheDocument();
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThan(0);
  });
});
