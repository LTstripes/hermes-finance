import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthFlowsSection } from "./MonthFlowsSection";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = {
  id: 11,
  name: "Synthetic Broker",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const instrument = {
  id: 21,
  name: "Synthetic Bond",
  instrument_type: "bond",
  isin: null,
  ticker: "SYNB",
  moex_secid: null,
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const mergedCalendar = [
  {
    year: 2031,
    month: 6,
    coupon: { amount: "0.00", currency: "RUB" },
    dividend: { amount: "0.00", currency: "RUB" },
    interest: { amount: "0.00", currency: "RUB" },
    redemption: { amount: "10000.00", currency: "RUB" },
    other: { amount: "0.00", currency: "RUB" },
    passive_net: { amount: "0.00", currency: "RUB" },
    total_net: { amount: "10000.00", currency: "RUB" },
    items: [
      {
        source_kind: "provider",
        source_id: 90,
        expected_date: "2031-06-15",
        flow_type: "redemption",
        account_id: 11,
        account_name: "Synthetic Broker",
        instrument_id: 21,
        instrument_name: "Synthetic Bond",
        expected_net_amount: { amount: "10000.00", currency: "RUB" },
        is_confirmed: null,
        is_approximate: false,
        manual_source: null,
        provider: "t_invest",
        provider_instrument_uid: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        provider_identity_key: "mty:1",
        provider_lifecycle: "active",
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: 90,
      },
    ],
  },
];

function setup(calendar: unknown[] = []) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (method === "GET" && url === "/api/accounts") return jsonResponse([account]);
    if (method === "GET" && url === "/api/instruments?active=true")
      return jsonResponse([instrument]);
    if (method === "GET" && url === "/api/investment-flows?month_id=7") return jsonResponse([]);
    if (method === "GET" && url === "/api/expected-flows?month_id=7&forecast_version=v1") {
      return jsonResponse([]);
    }
    if (method === "GET" && url === "/api/payouts/calendar?month_id=7&forecast_version=v1") {
      return jsonResponse(calendar);
    }
    if (method === "POST" && url === "/api/investment-flows") {
      return jsonResponse({ id: 31 }, 201);
    }

    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
      404,
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  render(<MonthFlowsSection defaultDate="2031-01-31" monthId={7} readOnly={false} />);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthFlowsSection actual-flow instrument", () => {
  it("starts empty and resets to empty after an actual flow is created", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();

    const instrumentSelect = await screen.findByLabelText("Инструмент (необязательно)");
    expect(instrumentSelect).toHaveValue("");

    await user.selectOptions(instrumentSelect, "21");
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "1000");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));

    await waitFor(() => expect(instrumentSelect).toHaveValue(""));

    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
    );
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      flow_type: "coupon",
    });
  });

  it("uses the merged payout calendar and exposes provider provenance", async () => {
    const fetchMock = setup(mergedCalendar);

    expect(await screen.findByText("T-Invest")).toBeInTheDocument();
    expect(screen.getByText("возврат капитала, не доход")).toBeInTheDocument();
    expect(screen.getByText(/весь денежный поток/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([input]) => String(input) === "/api/payouts/calendar?month_id=7&forecast_version=v1",
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/expected-flows/calendar")),
    ).toBe(false);
  });
});
