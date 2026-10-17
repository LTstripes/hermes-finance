import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getKnownTrades, type KnownTrades } from "../api/instrumentTrades";
import { InstrumentTrades } from "./InstrumentTrades";

vi.mock("../api/instrumentTrades", () => ({ getKnownTrades: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const scope = { accountId: 1, instrumentId: 9, t0: "2030-01-01", t1: "2030-01-31" };
function fixture(): KnownTrades {
  return {
    method: "known-instrument-trades",
    version: 1,
    account: { id: 1, name: "Synthetic account" },
    instrument: { id: 9, name: "Exited bond" },
    t0: scope.t0,
    t1: scope.t1,
    currency: "RUB",
    status: "available",
    capacity: 250,
    known_count: 1,
    trade_history_completeness: "unknown",
    financial_coverage: "unknown",
    dependency_digest: "a".repeat(64),
    dependency_fingerprint: null,
    currentness: "unavailable",
    reason_codes: ["source_inventory_gap"],
    events: [
      {
        trade_id: 7,
        account_id: 1,
        instrument_id: 9,
        source_identity: "native-a",
        native_ids: ["101", "202"],
        proof_class: "observed_native_execution",
        revision: 2,
        currentness: "current",
        historical_identity: { isin: "RU000A000001", instrument_type: "bond", denomination: "RUB" },
        side: "BUY",
        signed_quantity: "0.123456789012345678901234567890",
        execution_date: "2030-01-15",
        execution_in_interval: true,
        settlement_date: "2030-02-01",
        settlement_in_interval: false,
        depository_date: null,
        depository_in_interval: null,
        planned_settlement_date: null,
        lifecycle: "settled",
        source_occurrences: [],
        reason_codes: [],
        cash_legs: [
          {
            role: "settlement",
            proof_class: "effective_cash_leg_authority",
            signed_rub: "-10000.01",
            signed_kopecks: "-1000001",
            effective_date: "2030-02-01",
            in_interval: false,
            basis: "excludes_paid_nkd",
            receipt_id: "synthetic-proof",
            occurrences: [],
            reason_codes: ["effective_money_role_proof"],
          },
          {
            role: "commission",
            proof_class: "unavailable",
            signed_rub: null,
            signed_kopecks: null,
            effective_date: null,
            in_interval: null,
            basis: null,
            receipt_id: null,
            occurrences: [],
            reason_codes: ["effective_money_proof_unavailable"],
          },
        ],
      },
    ],
  };
}
function mount(
  request: { scope: typeof scope; generation: number } | null = { scope, generation: 1 },
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const element = (r: typeof request) => (
    <QueryClientProvider client={client}>
      <InstrumentTrades request={r} />
    </QueryClientProvider>
  );
  const view = render(element(request));
  return { rerender: (r: typeof request) => view.rerender(element(r)) };
}
it("keeps exact quantity and signed money; labels independent dates and NULL proof", async () => {
  vi.mocked(getKnownTrades).mockResolvedValue(fixture());
  mount();
  await screen.findByTestId("known-trades-result");
  expect(screen.getByText("BUY · 0.123456789012345678901234567890")).toBeVisible();
  expect(screen.getByText("Расчёт по сделке: -10000,01 ₽")).toBeVisible();
  expect(screen.getByText("Комиссия: Неизвестно")).toBeVisible();
  expect(screen.getAllByText(/вне \(t0,t1\]/).length).toBe(2);
  expect(screen.getByText(/Полнота сделок и денежных расчётов неизвестна/)).toBeVisible();
});
it("is on demand and discards a late response after scope invalidation", async () => {
  let finish!: (v: KnownTrades) => void;
  vi.mocked(getKnownTrades).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = mount(null);
  expect(getKnownTrades).not.toHaveBeenCalled();
  view.rerender({ scope, generation: 1 });
  await waitFor(() => expect(getKnownTrades).toHaveBeenCalledOnce());
  view.rerender(null);
  await act(async () => finish(fixture()));
  expect(screen.queryByTestId("known-trades-result")).not.toBeInTheDocument();
});
it.each(["account", "instrument", "t0", "method", "nested"])(
  "rejects mismatched %s scope",
  async (kind) => {
    const data = fixture();
    if (kind === "account") data.account.id = 99;
    if (kind === "instrument") data.instrument.id = 99;
    if (kind === "t0") data.t0 = "2029-01-01";
    if (kind === "method") data.version = 2 as 1;
    if (kind === "nested") data.events[0].account_id = 99;
    vi.mocked(getKnownTrades).mockResolvedValue(data);
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
    expect(screen.queryByTestId("known-trades-result")).not.toBeInTheDocument();
  },
);
it("shows error and a new request generation can retry", async () => {
  vi.mocked(getKnownTrades)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(fixture());
  const view = mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось прочитать сделки");
  view.rerender({ scope, generation: 2 });
  await screen.findByTestId("known-trades-result");
});
it("empty and capacity states never imply no trades", async () => {
  const data = fixture();
  data.events = [];
  data.known_count = 0;
  vi.mocked(getKnownTrades)
    .mockResolvedValueOnce(data)
    .mockResolvedValueOnce({ ...data, known_count: null, status: "capacity_exceeded" });
  const view = mount();
  expect(await screen.findByText(/Это не доказывает отсутствия сделок/)).toBeVisible();
  view.rerender({ scope, generation: 2 });
  expect(await screen.findByRole("alert")).toHaveTextContent("список не усечён");
});
