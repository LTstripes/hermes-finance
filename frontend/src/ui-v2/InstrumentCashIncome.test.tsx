import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { KnownPayouts } from "../api/instrumentCashIncome";
import {
  getInstrumentObservations,
  type InstrumentObservations,
} from "../api/instrumentEodObservations";
import { listInstruments } from "../api/instruments";
import type { Account, Instrument } from "../api/types";
import { InstrumentCashIncome } from "./InstrumentCashIncome";

vi.mock("../api/instrumentEodObservations", () => ({ getInstrumentObservations: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("./InstrumentTrades", () => ({ InstrumentTrades: () => null }));
const accounts = [
  { id: 1, name: "Synthetic A", account_type: "brokerage" },
  { id: 2, name: "Synthetic B", account_type: "iis" },
] as Account[];
function fixture(): KnownPayouts {
  return {
    method: "known-booked-net-payouts",
    version: 1,
    account: { id: 1, name: "Synthetic A" },
    instrument: { id: 9, name: "Exited bond" },
    t0: "2030-01-01",
    t1: "2030-01-31",
    currency: "RUB",
    coverage: "unknown",
    completeness: "unknown",
    known_booked_net: { coupon: "120.00", dividend: null },
    event_count: 1,
    known_event_count: 1,
    dependency_fingerprint: "a".repeat(64),
    reason_codes: [],
    events: [
      {
        cash_flow_id: 7,
        kind: "coupon",
        date: "2030-01-17",
        booked_net: "120.00",
        included_in_known_net: true,
        proof_state: "source_accepted",
        currentness: "current",
        gross: null,
        tax: null,
        fee: null,
        tax_available: false,
        receipt_ids: ["money:synthetic"],
        provenance: ["accepted_money_coupon"],
        reason_codes: [],
      },
    ],
  };
}
function observations(payouts = fixture()): InstrumentObservations {
  const boundary = {
    date: payouts.t0,
    account_id: payouts.account.id,
    instrument_id: payouts.instrument.id,
    availability: "available" as const,
    quantity: "10",
    market_value: "1000.00",
    currency: "RUB" as const,
    historical_identity: {
      isin: "RU000A000001",
      instrument_type: "bond" as const,
      denomination: "RUB" as const,
    },
    bond_nkd_basis: "unknown" as const,
    price_date: payouts.t0,
    position_id: 5,
    price_source: "broker_statement_native",
    source_import_id: 1,
    source_row_key: "a".repeat(64),
    receipt_ids: ["eod-receipt"],
    revision_generation: 1,
    proof_state: "source_accepted" as const,
    currentness: "current" as const,
    dependency_fingerprint: "b".repeat(64),
    reason_codes: [],
  };
  return {
    method: "persisted-instrument-eod-pair",
    version: 1,
    account: payouts.account,
    instrument: payouts.instrument,
    t0: payouts.t0,
    t1: payouts.t1,
    currency: "RUB",
    opening: boundary,
    closing: { ...boundary, date: payouts.t1, price_date: payouts.t1, market_value: "950.00" },
    comparable: null,
    observed_position_value_difference: null,
    reason_codes: ["bond_nkd_basis_unknown"],
    dependency_fingerprint: "c".repeat(64),
    valuation_dependency_fingerprint: "d".repeat(64),
    known_payouts: payouts,
  };
}
beforeEach(() => {
  vi.mocked(listInstruments).mockResolvedValue([
    { id: 9, name: "Exited bond", is_active: false },
  ] as Instrument[]);
  vi.mocked(getInstrumentObservations).mockResolvedValue(observations());
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function mount() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <InstrumentCashIncome accounts={accounts} start="2030-01-01" end="2030-01-31" accountId={1} />
    </QueryClientProvider>,
  );
}
async function select() {
  fireEvent.click(screen.getByRole("button", { name: "Выбрать бумагу и период" }));
  await screen.findByRole("option", { name: "Exited bond (неактивна)" });
  fireEvent.change(screen.getByLabelText("Бумага выплат"), { target: { value: "9" } });
}
it("fetches on demand only, validates selectors and renders exact net / unknown tax / provenance", async () => {
  mount();
  expect(getInstrumentObservations).not.toHaveBeenCalled();
  expect(listInstruments).not.toHaveBeenCalled();
  await select();
  fireEvent.change(screen.getByLabelText("Выплаты после даты"), {
    target: { value: "2030-02-01" },
  });
  expect(screen.getByRole("button", { name: "Прочитать оценки и выплаты" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Выплаты после даты"), {
    target: { value: "2030-01-01" },
  });
  expect(getInstrumentObservations).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  const result = await screen.findByTestId("known-payouts-result");
  expect(within(result).getByText(/купоны 120,00 ₽; дивиденды Неизвестно/)).toBeInTheDocument();
  expect(within(result).getByText("Источник подтверждён")).toBeInTheDocument();
  const eod = screen.getByRole("region", { name: "Наблюдаемые EOD-оценки" });
  expect(within(eod).getByText("1000,00 ₽")).toBeInTheDocument();
  expect(within(eod).getByText("950,00 ₽")).toBeInTheDocument();
  expect(within(eod).getByText(/Полная доходность RUB\/% пока недоступна/)).toBeInTheDocument();
  expect(within(eod).queryByText(/70,00|7%/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Детали записи ICF #7"));
  expect(screen.getByText(/налог: Неизвестно/)).toBeInTheDocument();
  expect(screen.getByText(/Подтверждение: money:synthetic/)).toBeInTheDocument();
  expect(getInstrumentObservations).toHaveBeenCalledWith(
    { accountId: 1, instrumentId: 9, t0: "2030-01-01", t1: "2030-01-31" },
    expect.any(AbortSignal),
  );
});
it("discards late A after account/period changes and A→B→A requires a fresh request", async () => {
  let resolve!: (value: InstrumentObservations) => void;
  vi.mocked(getInstrumentObservations).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await waitFor(() => expect(getInstrumentObservations).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: "2030-01-30" } });
  await act(async () => resolve(observations()));
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  expect(screen.queryByTestId("instrument-eod-result")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: "2030-01-31" } });
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByTestId("known-payouts-result");
  expect(getInstrumentObservations).toHaveBeenCalledTimes(2);
});

it("a missing boundary is unknown, never zero; quantity difference is not profit", async () => {
  const value = observations();
  value.comparable = true;
  value.observed_position_value_difference = "-50.00";
  value.closing.quantity = "5";
  value.reason_codes = ["quantity_changed_not_profit"];
  vi.mocked(getInstrumentObservations).mockResolvedValueOnce(value);
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByTestId("instrument-eod-result");
  expect(
    screen.getByText(
      /Разница наблюдаемых стоимостей позиции: -50,00 ₽. Это не прибыль и не доходность/,
    ),
  ).toBeInTheDocument();
  const missing = observations();
  Object.assign(missing.closing, {
    availability: "unavailable",
    currentness: "unavailable",
    proof_state: "unavailable",
    market_value: null,
    quantity: null,
    reason_codes: ["exact_eod_position_missing"],
  });
  vi.mocked(getInstrumentObservations).mockResolvedValueOnce(missing);
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByText(/На эту точную дату нет сохранённой позиции/);
  expect(screen.queryByText(/Разница наблюдаемых стоимостей позиции/)).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("article", { name: /Конечная оценка EOD/ })).getByText("Неизвестно"),
  ).toBeInTheDocument();
});

it("rejects mismatched boundary scope even if outer response and payouts match", async () => {
  const value = observations();
  value.closing.account_id = 999;
  vi.mocked(getInstrumentObservations).mockResolvedValueOnce(value);
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByText(/Ответ не соответствует/);
  expect(screen.queryByTestId("instrument-eod-result")).not.toBeInTheDocument();
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
});
it("shows gaps/manual without promoting source authority; no events never means zero income", async () => {
  const gap = fixture();
  gap.known_booked_net.coupon = null;
  gap.known_event_count = 0;
  Object.assign(gap.events[0], {
    proof_state: "manual_booked",
    currentness: "unavailable",
    included_in_known_net: false,
    provenance: ["manual"],
    reason_codes: ["historical_instrument_identity_unknown"],
  });
  vi.mocked(getInstrumentObservations)
    .mockResolvedValueOnce(observations(gap))
    .mockResolvedValueOnce(observations({ ...gap, events: [], event_count: 0 }));
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByTestId("known-payouts-result");
  expect(screen.queryByText("Источник подтверждён")).not.toBeInTheDocument();
  expect(screen.getByText("В известную сумму не включено")).toBeInTheDocument();
  expect(screen.getByText(/Не подтверждена историческая RUB-идентичность/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByText(/Это не подтверждает нулевой доход/);
});
it("hides previous values during refresh failure and rejects wrong-scope response", async () => {
  vi.mocked(getInstrumentObservations).mockRejectedValueOnce(new Error("unavailable"));
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByRole("alert");
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  vi.mocked(getInstrumentObservations).mockResolvedValueOnce({
    ...observations(),
    account: { id: 2, name: "B" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByText(/Ответ не соответствует/);
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
});
