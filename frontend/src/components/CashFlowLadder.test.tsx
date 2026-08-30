import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CashFlowLadder } from "../api/types";
import { rub } from "../lib/money";
import { CashFlowLadder as CashFlowLadderView } from "./CashFlowLadder";

function event(overrides: Partial<CashFlowLadder["months"][number]["items"][number]> = {}) {
  return {
    source_kind: "manual",
    source_id: 1,
    expected_date: "2030-06-15",
    flow_type: "coupon",
    component: "coupon",
    account_id: 1,
    account_name: "Synthetic Brokerage",
    instrument_id: 1,
    instrument_name: "Synthetic Bond",
    expected_net_amount: rub("100.00"),
    is_approximate: false,
    source: "synthetic owner forecast",
    provider: null,
    provider_instrument_uid: null,
    provider_identity_key: null,
    reconciliation_id: null,
    counting_decision: null,
    linked_manual_id: null,
    linked_provider_payout_id: null,
    source_as_of_date: "2030-05-12",
    ...overrides,
  };
}

function ladder(): CashFlowLadder {
  const months = Array.from({ length: 12 }, (_, index) => ({
    year: index < 8 ? 2030 : 2031,
    month: index < 8 ? index + 5 : index - 7,
    coupon: rub(index === 1 ? "100.00" : "0.00"),
    dividend: rub("0.00"),
    deposit_interest: rub(index === 0 ? "1200.00" : "0.00"),
    other_capital_income: rub("0.00"),
    redemption_principal: rub(index === 2 ? "10000.00" : "0.00"),
    passive_income: rub(index === 0 ? "1200.00" : index === 1 ? "100.00" : "0.00"),
    total_cash_flow: rub(
      index === 2 ? "10000.00" : index === 0 ? "1200.00" : index === 1 ? "100.00" : "0.00",
    ),
    is_approximate: index === 0,
    items:
      index === 1
        ? [event()]
        : index === 2
          ? [
              event({
                component: "redemption_principal",
                flow_type: "redemption",
                expected_net_amount: rub("10000.00"),
              }),
            ]
          : [],
  }));
  const window = {
    days: 14,
    from_date: "2030-05-12",
    to_date: "2030-05-26",
    passive_income: rub("1200.00"),
    redemption_principal: rub("0.00"),
    total_cash_flow: rub("1200.00"),
    items: [
      event({
        source_kind: "deposit_forecast",
        source: "deposit_snapshot",
        instrument_name: "Synthetic deposit",
        is_approximate: true,
      }),
    ],
  };
  return {
    as_of_date: "2030-05-12",
    forecast_version: "v1",
    months,
    upcoming_14_days: window,
    upcoming_30_days: { ...window, days: 30, to_date: "2030-06-11" },
    warnings: ["Проценты по вкладам — приблизительная оценка."],
  };
}

describe("CashFlowLadder", () => {
  it("shows compact windows, all twelve months, capital redemption and deferred details", async () => {
    const user = userEvent.setup();
    render(<CashFlowLadderView ladder={ladder()} />);

    expect(screen.getByRole("heading", { name: "Ближайшие 14 дней" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ближайшие 30 дней" })).toBeInTheDocument();
    expect(screen.getByText("12-месячная лестница ожидаемых денежных потоков")).toBeInTheDocument();
    expect(screen.getAllByText("есть оценка")).toHaveLength(1);
    expect(screen.getByText("Погашение")).toBeInTheDocument();
    const details = screen.getByText("Подробнее о данных").closest("details");
    expect(details).not.toBeNull();
    if (!details) throw new Error("Cash-flow details were not rendered");
    expect(details).not.toHaveAttribute("open");
    await user.click(screen.getByText("Подробнее о данных"));
    expect(screen.getByText(/Проценты по вкладам/)).toBeInTheDocument();
    expect(screen.getAllByText(/Synthetic Bond/).length).toBeGreaterThan(0);
  });
});
