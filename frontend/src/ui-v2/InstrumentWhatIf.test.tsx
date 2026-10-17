import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  type InstrumentWhatIfResult,
  type WhatIfRequest,
  evaluateInstrumentWhatIf,
} from "../api/instrumentWhatIf";
import { listInstruments } from "../api/instruments";
import type { Account, Instrument } from "../api/types";
import { InstrumentCashIncome } from "./InstrumentCashIncome";
import { InstrumentWhatIf } from "./InstrumentWhatIf";

vi.mock("../api/instrumentWhatIf", async (original) => ({
  ...(await original<typeof import("../api/instrumentWhatIf")>()),
  evaluateInstrumentWhatIf: vi.fn(),
}));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("./InstrumentTrades", () => ({ InstrumentTrades: () => null }));
const scope = { accountId: 1, instrumentId: 9, t0: "2030-01-31", t1: "2030-02-28" };
function fixture(r: WhatIfRequest): InstrumentWhatIfResult {
  const a = { id: 1, name: "Synthetic account" },
    i = { id: 9, name: "Synthetic stock" };
  const common = {
    account: a,
    instrument: i,
    t0: scope.t0,
    t1: scope.t1,
    currency: "RUB" as const,
  };
  const boundary = {
    date: scope.t0,
    account_id: 1,
    instrument_id: 9,
    availability: "available" as const,
    quantity: "10",
    market_value: "1000.00",
    currency: "RUB" as const,
    historical_identity: {
      isin: "SYN-STOCK",
      instrument_type: "stock" as const,
      denomination: "RUB" as const,
    },
    bond_nkd_basis: "not_applicable" as const,
    price_date: scope.t0,
    position_id: 1,
    price_source: "broker_statement_native",
    source_import_id: 1,
    source_row_key: "a".repeat(64),
    receipt_ids: ["synthetic-eod"],
    revision_generation: 1,
    proof_state: "source_accepted" as const,
    currentness: "current" as const,
    dependency_fingerprint: "b".repeat(64),
    reason_codes: [],
  };
  const missing = Object.keys(r.chosen).filter((k) => !r.chosen[k as keyof typeof r.chosen]);
  return {
    ...common,
    method: "hypothetical-fixed-stock-hpr",
    version: 1,
    authority: "hypothetical",
    request_nonce: r.nonce,
    interval: "(t0,t1]",
    chosen_assumptions: r.chosen,
    missing_assumptions: missing,
    hard_blockers: [],
    source_checks: [{ source_import_id: 1, reason_codes: [] }],
    observed: {
      opening: boundary,
      closing: { ...boundary, date: scope.t1, price_date: scope.t1, market_value: "900.00" },
      comparable: true,
    },
    accepted_known: {
      payouts: {
        ...common,
        method: "known-booked-net-payouts",
        version: 1,
        coverage: "unknown",
        completeness: "unknown",
        known_booked_net: { coupon: null, dividend: "150.00" },
        event_count: 1,
        known_event_count: 1,
        dependency_fingerprint: "c".repeat(64),
        reason_codes: [],
        events: [
          {
            cash_flow_id: 1,
            kind: "dividend",
            date: "2030-02-20",
            booked_net: "150.00",
            included_in_known_net: true,
            proof_state: "source_accepted",
            currentness: "current",
            gross: "150.00",
            tax: null,
            fee: null,
            tax_available: false,
            receipt_ids: ["statement:1:revision:1"],
            provenance: ["typed_depository"],
            reason_codes: [],
          },
        ],
      },
      trades: {
        ...common,
        method: "known-instrument-trades",
        version: 1,
        trade_history_completeness: "unknown",
        financial_coverage: "unknown",
        status: "available",
        capacity: 250,
        known_count: 0,
        events: [],
        dependency_digest: "d".repeat(64),
        dependency_fingerprint: null,
        currentness: "unavailable",
        reason_codes: [],
      },
    },
    hypothetical_result: {
      conditional_result: missing.length ? null : "50.00",
      conditional_period_fraction: missing.length ? null : "0.05",
      conditional_period_percent: missing.length ? null : "5",
      percent_unit: "percentage_points",
      annualized: false,
      formula: "V1-V0+P",
      decimal_precision: 100,
    },
    actual_instrument_return: null,
    whole_period_completeness: "unknown",
    dependency_fingerprint: null,
  };
}
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
function mount(parent = false) {
  vi.mocked(evaluateInstrumentWhatIf).mockImplementation(async (r) => fixture(r));
  vi.mocked(listInstruments).mockResolvedValue([
    { id: 9, name: "Synthetic stock", is_active: true },
  ] as Instrument[]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      {parent ? (
        <InstrumentCashIncome
          accounts={
            [
              { id: 1, name: "A", account_type: "brokerage" },
              { id: 2, name: "B", account_type: "iis" },
            ] as Account[]
          }
          start={scope.t0}
          end={scope.t1}
          accountId={1}
        />
      ) : (
        <InstrumentWhatIf scope={scope} />
      )}
    </QueryClientProvider>,
  );
}
const calculate = () =>
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
function chooseAll() {
  for (const checkbox of screen.getAllByRole("checkbox")) fireEvent.click(checkbox);
}
it("requires three explicit choices and shows exact hypothetical amount, fraction and percent", async () => {
  mount();
  expect(evaluateInstrumentWhatIf).not.toHaveBeenCalled();
  for (const c of screen.getAllByRole("checkbox")) expect(c).not.toBeChecked();
  calculate();
  expect(await screen.findByTestId("instrument-what-if-result")).toHaveTextContent(
    "Выбраны не все три допущения",
  );
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
  chooseAll();
  expect(screen.queryByTestId("instrument-what-if-result")).not.toBeInTheDocument();
  calculate();
  expect(await screen.findByText("Условно: +50,00 ₽ / +5% за период")).toBeVisible();
  expect(screen.getByText("Фактическая доходность пока недоступна")).toBeVisible();
  fireEvent.click(screen.getByText("Источники и метод сценария"));
  expect(screen.getByText(/Доля за период: 0.05; процент: 5/)).toBeVisible();
  expect(screen.getByText(/ICF #1: statement:1:revision:1/)).toBeVisible();
  expect(screen.getByText(/Удержания, уже включённые в net/)).toBeVisible();
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
});
it.each([
  "bond",
  "money_economic_effect_unproven",
  "known_execution_or_crossing",
  "source_calendar_gap",
])("preserves hard blocker %s despite all choices", async (reason) => {
  mount();
  chooseAll();
  vi.mocked(evaluateInstrumentWhatIf).mockImplementation(async (r) => {
    const d = fixture(r);
    d.hard_blockers = [reason === "bond" ? "bond_dirty_basis_source_unproven" : reason];
    d.hypothetical_result.conditional_result =
      d.hypothetical_result.conditional_period_fraction =
      d.hypothetical_result.conditional_period_percent =
        null;
    return d;
  });
  calculate();
  expect(await screen.findByTestId("instrument-what-if-result")).toHaveTextContent(
    "Расчёт заблокирован источниками",
  );
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
});
it.each([
  "nonce",
  "method",
  "assumption",
  "nested_scope",
  "currency",
  "actual",
  "annualized",
  "forged_bond",
  "fingerprint",
])("rejects forged or late %s response", async (kind) => {
  mount();
  chooseAll();
  vi.mocked(evaluateInstrumentWhatIf).mockImplementation(async (r) => {
    const d = fixture(r);
    if (kind === "nonce") d.request_nonce = "old-request";
    if (kind === "method") d.version = 2 as 1;
    if (kind === "assumption") d.chosen_assumptions = { ...r.chosen, no_unobserved_payouts: false };
    if (kind === "nested_scope" && d.accepted_known.trades) d.accepted_known.trades.account.id = 99;
    if (kind === "currency") d.currency = "USD" as "RUB";
    if (kind === "actual") d.actual_instrument_return = "5" as unknown as null;
    if (kind === "annualized") d.hypothetical_result.annualized = true as false;
    if (kind === "forged_bond" && d.observed?.opening.historical_identity)
      d.observed.opening.historical_identity.instrument_type = "bond";
    if (kind === "fingerprint" && d.accepted_known.trades)
      d.accepted_known.trades.dependency_fingerprint = "invented-certification";
    return d;
  });
  calculate();
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
});
it("hides prior value during refresh and after failure, recomputes with a new nonce", async () => {
  mount();
  chooseAll();
  calculate();
  await screen.findByText(/Условно:/);
  const first = vi.mocked(evaluateInstrumentWhatIf).mock.calls[0][0].nonce;
  vi.mocked(evaluateInstrumentWhatIf).mockRejectedValueOnce(new Error("unavailable"));
  calculate();
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось проверить сценарий");
  calculate();
  await screen.findByText(/Условно:/);
  expect(vi.mocked(evaluateInstrumentWhatIf).mock.calls[2][0].nonce).not.toBe(first);
});
it("selector A→B→A discards late response and resets assumptions without persistence", async () => {
  mount(true);
  fireEvent.click(screen.getByRole("button", { name: "Выбрать бумагу и период" }));
  await screen.findByRole("option", { name: "Synthetic stock" });
  fireEvent.change(screen.getByLabelText("Бумага выплат"), { target: { value: "9" } });
  chooseAll();
  let release!: () => void;
  vi.mocked(evaluateInstrumentWhatIf).mockImplementationOnce(
    (r) =>
      new Promise((resolve) => {
        release = () => resolve(fixture(r));
      }),
  );
  calculate();
  await waitFor(() => expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce());
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "1" } });
  await act(async () => release());
  const panel = screen.getByRole("region", { name: "Условный результат бумаги" });
  expect(within(panel).queryByTestId("instrument-what-if-result")).not.toBeInTheDocument();
  for (const c of within(panel).getAllByRole("checkbox")) expect(c).not.toBeChecked();
  expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce();
});
