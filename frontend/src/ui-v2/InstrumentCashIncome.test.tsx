import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getKnownPayouts, type KnownPayouts } from "../api/instrumentCashIncome";
import { listInstruments } from "../api/instruments";
import type { Account, Instrument } from "../api/types";
import { InstrumentCashIncome } from "./InstrumentCashIncome";

vi.mock("../api/instrumentCashIncome", () => ({ getKnownPayouts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
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
beforeEach(() => {
  vi.mocked(listInstruments).mockResolvedValue([
    { id: 9, name: "Exited bond", is_active: false },
  ] as Instrument[]);
  vi.mocked(getKnownPayouts).mockResolvedValue(fixture());
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
  expect(getKnownPayouts).not.toHaveBeenCalled();
  expect(listInstruments).not.toHaveBeenCalled();
  await select();
  fireEvent.change(screen.getByLabelText("Выплаты после даты"), {
    target: { value: "2030-02-01" },
  });
  expect(screen.getByRole("button", { name: "Прочитать выплаты" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Выплаты после даты"), {
    target: { value: "2030-01-01" },
  });
  expect(getKnownPayouts).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  const result = await screen.findByTestId("known-payouts-result");
  expect(within(result).getByText(/купоны 120,00 ₽; дивиденды Неизвестно/)).toBeInTheDocument();
  expect(within(result).getByText("Источник подтверждён")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Детали записи ICF #7"));
  expect(screen.getByText(/налог: Неизвестно/)).toBeInTheDocument();
  expect(screen.getByText(/Подтверждение: money:synthetic/)).toBeInTheDocument();
  expect(getKnownPayouts).toHaveBeenCalledWith(
    { accountId: 1, instrumentId: 9, t0: "2030-01-01", t1: "2030-01-31" },
    expect.any(AbortSignal),
  );
});
it("discards late A after account/period changes and A→B→A requires a fresh request", async () => {
  let resolve!: (value: KnownPayouts) => void;
  vi.mocked(getKnownPayouts).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await waitFor(() => expect(getKnownPayouts).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: "2030-01-30" } });
  await act(async () => resolve(fixture()));
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: "2030-01-31" } });
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await screen.findByTestId("known-payouts-result");
  expect(getKnownPayouts).toHaveBeenCalledTimes(2);
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
  vi.mocked(getKnownPayouts)
    .mockResolvedValueOnce(gap)
    .mockResolvedValueOnce({ ...gap, events: [], event_count: 0 });
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await screen.findByTestId("known-payouts-result");
  expect(screen.queryByText("Источник подтверждён")).not.toBeInTheDocument();
  expect(screen.getByText("В известную сумму не включено")).toBeInTheDocument();
  expect(screen.getByText(/Не подтверждена историческая RUB-идентичность/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await screen.findByText(/Это не подтверждает нулевой доход/);
});
it("hides previous values during refresh failure and rejects wrong-scope response", async () => {
  vi.mocked(getKnownPayouts).mockRejectedValueOnce(new Error("unavailable"));
  mount();
  await select();
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await screen.findByRole("alert");
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  vi.mocked(getKnownPayouts).mockResolvedValueOnce({ ...fixture(), account: { id: 2, name: "B" } });
  fireEvent.click(screen.getByRole("button", { name: "Прочитать выплаты" }));
  await screen.findByText(/Ответ не соответствует/);
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
});
