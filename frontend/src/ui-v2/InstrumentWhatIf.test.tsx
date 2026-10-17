import { focusManager, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  getInstrumentObservations,
  type InstrumentObservations,
} from "../api/instrumentEodObservations";
import {
  type InstrumentWhatIfResult,
  type WhatIfRequest,
  evaluateInstrumentWhatIf,
} from "../api/instrumentWhatIf";
import { listInstruments } from "../api/instruments";
import type { Account, Instrument } from "../api/types";
import { createQueryClient } from "../queryClient";
import { InstrumentCashIncome } from "./InstrumentCashIncome";
import { InstrumentWhatIf } from "./InstrumentWhatIf";

vi.mock("../api/instrumentWhatIf", async (original) => ({
  ...(await original<typeof import("../api/instrumentWhatIf")>()),
  evaluateInstrumentWhatIf: vi.fn(),
}));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/instrumentEodObservations", () => ({ getInstrumentObservations: vi.fn() }));
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
  focusManager.setFocused(undefined);
  vi.resetAllMocks();
});
function mount(parent = false) {
  vi.mocked(evaluateInstrumentWhatIf).mockImplementation(async (r) => fixture(r));
  vi.mocked(listInstruments).mockResolvedValue([
    { id: 9, name: "Synthetic stock", is_active: true },
  ] as Instrument[]);
  const client = createQueryClient();
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
  return client;
}
const calculate = () =>
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
function chooseAll() {
  for (const checkbox of screen.getAllByRole("checkbox")) fireEvent.click(checkbox);
}
function parentEvidence(): InstrumentObservations {
  const d = fixture({
    scope,
    nonce: "parent-fixture",
    chosen: {
      no_unobserved_movements: false,
      no_unobserved_payouts: false,
      no_other_costs_or_taxes: false,
    },
  });
  if (!d.observed || !d.accepted_known.payouts) throw new Error("Incomplete synthetic fixture");
  return {
    method: "persisted-instrument-eod-pair",
    version: 1,
    account: d.account,
    instrument: d.instrument,
    t0: d.t0,
    t1: d.t1,
    currency: "RUB",
    opening: d.observed.opening,
    closing: d.observed.closing,
    comparable: true,
    observed_position_value_difference: "-100.00",
    reason_codes: [],
    dependency_fingerprint: "e".repeat(64),
    valuation_dependency_fingerprint: "f".repeat(64),
    known_payouts: d.accepted_known.payouts,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function mountWithEvidence() {
  vi.mocked(getInstrumentObservations).mockResolvedValue(parentEvidence());
  const client = mount(true);
  fireEvent.click(screen.getByRole("button", { name: "Выбрать бумагу и период" }));
  await screen.findByRole("option", { name: "Synthetic stock" });
  fireEvent.change(screen.getByLabelText("Бумага выплат"), { target: { value: "9" } });
  fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
  await screen.findByTestId("known-payouts-result");
  return client;
}
function expectReset() {
  expect(screen.queryByTestId("instrument-what-if-result")).not.toBeInTheDocument();
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
  for (const c of screen.getAllByRole("checkbox")) expect(c).not.toBeChecked();
}
async function focusRefresh() {
  await act(async () => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => expect(getInstrumentObservations).toHaveBeenCalledTimes(2));
}

it("focus refresh retracts payouts before late A; only an explicit new evaluation may return", async () => {
  await mountWithEvidence();
  chooseAll();
  const a = deferred<InstrumentWhatIfResult>();
  let requestA!: WhatIfRequest;
  // Deliberately ignore abort: invalidation must also reject an already received late response.
  vi.mocked(evaluateInstrumentWhatIf).mockImplementationOnce((r) => {
    requestA = r;
    return a.promise;
  });
  calculate();
  await waitFor(() => expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce());
  const b = deferred<InstrumentObservations>();
  vi.mocked(getInstrumentObservations).mockReturnValueOnce(b.promise);
  await focusRefresh();
  expect(
    screen.queryByRole("region", { name: "Условный результат бумаги" }),
  ).not.toBeInTheDocument();
  const retracted = parentEvidence();
  Object.assign(retracted.known_payouts, {
    events: [],
    event_count: 0,
    known_event_count: 0,
    known_booked_net: { coupon: null, dividend: null },
    dependency_fingerprint: "0".repeat(64),
  });
  await act(async () => b.resolve(retracted));
  await screen.findByText(/Записей не обнаружено/);
  expectReset();
  await act(async () => a.resolve(fixture(requestA)));
  expectReset();
  expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce();
  expect(screen.getByTestId("known-payouts-result")).toHaveTextContent("дивиденды Неизвестно");
  chooseAll();
  vi.mocked(evaluateInstrumentWhatIf).mockImplementationOnce(async (r) => {
    const blocked = fixture(r);
    blocked.accepted_known.payouts = retracted.known_payouts;
    blocked.hard_blockers = ["dividend_source_unproven"];
    Object.assign(blocked.hypothetical_result, {
      conditional_result: null,
      conditional_period_fraction: null,
      conditional_period_percent: null,
    });
    return blocked;
  });
  calculate();
  expect(await screen.findByTestId("instrument-what-if-result")).toHaveTextContent(
    "Расчёт заблокирован",
  );
  expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument();
});

it.each(["revised proof", "identical evidence", "failure"])(
  "hides shown A as focus B starts and never restores it after %s",
  async (outcome) => {
    const client = await mountWithEvidence();
    chooseAll();
    calculate();
    await screen.findByText("Условно: +50,00 ₽ / +5% за период");
    const b = deferred<InstrumentObservations>();
    vi.mocked(getInstrumentObservations).mockReturnValueOnce(b.promise);
    await focusRefresh();
    await waitFor(() => expect(screen.queryByText(/Условно:/)).not.toBeInTheDocument());
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    // Focus must not automatically evaluate the hypothetical query as it is being invalidated.
    expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce();
    const revised = parentEvidence();
    if (outcome === "revised proof") {
      revised.known_payouts.events[0].receipt_ids = ["statement:1:revision:2"];
      revised.known_payouts.dependency_fingerprint = "2".repeat(64);
    }
    await act(async () => {
      if (outcome === "failure") b.reject(new Error("synthetic refresh failure"));
      else b.resolve(revised);
    });
    if (outcome === "failure") {
      await screen.findByText("Не удалось проверить выплаты. Повторите чтение.");
      // React Query retains the old data on failed refresh; it must not re-authorize A.
      expect(
        client
          .getQueryCache()
          .find({ queryKey: ["instrument-observations-and-payouts"], exact: false })?.state.data,
      ).toBeDefined();
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Прочитать оценки и выплаты" }));
    }
    await screen.findByTestId("known-payouts-result");
    expectReset();
    expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce();
    chooseAll();
    calculate();
    await screen.findByText("Условно: +50,00 ₽ / +5% за период");
    expect(evaluateInstrumentWhatIf).toHaveBeenCalledTimes(2);
    expect(vi.mocked(evaluateInstrumentWhatIf).mock.calls[1][0].nonce).not.toBe(
      vi.mocked(evaluateInstrumentWhatIf).mock.calls[0][0].nonce,
    );
  },
);

it("batched identical parent refetches reset choices even without an observed fetching render", async () => {
  const client = await mountWithEvidence();
  chooseAll();
  calculate();
  await screen.findByText(/Условно:/);
  await act(async () => {
    await client.refetchQueries({ queryKey: ["instrument-observations-and-payouts"] });
    await client.refetchQueries({ queryKey: ["instrument-observations-and-payouts"] });
  });
  await waitFor(expectReset);
  expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce();
});

it("B then B2 returning original evidence cannot resurrect pending A or C across A→B→A scope", async () => {
  const client = await mountWithEvidence();
  const a = deferred<InstrumentWhatIfResult>();
  const c = deferred<InstrumentWhatIfResult>();
  let requestA!: WhatIfRequest;
  let requestC!: WhatIfRequest;
  vi.mocked(evaluateInstrumentWhatIf).mockImplementationOnce((r) => {
    requestA = r;
    return a.promise;
  });
  chooseAll();
  calculate();
  await waitFor(() => expect(evaluateInstrumentWhatIf).toHaveBeenCalledOnce());
  const revised = parentEvidence();
  revised.known_payouts.dependency_fingerprint = "2".repeat(64);
  revised.known_payouts.events[0].receipt_ids = ["statement:1:revision:2"];
  vi.mocked(getInstrumentObservations).mockResolvedValueOnce(revised);
  await act(async () => {
    await client.refetchQueries({ queryKey: ["instrument-observations-and-payouts"] });
  });
  await waitFor(expectReset);
  vi.mocked(evaluateInstrumentWhatIf).mockImplementationOnce((r) => {
    requestC = r;
    return c.promise;
  });
  chooseAll();
  calculate();
  await waitFor(() => expect(evaluateInstrumentWhatIf).toHaveBeenCalledTimes(2));
  await act(async () => {
    await client.refetchQueries({ queryKey: ["instrument-observations-and-payouts"] });
  });
  await waitFor(expectReset);
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: "2030-02-27" } });
  fireEvent.change(screen.getByLabelText("Счёт выплат"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Выплаты по дату"), { target: { value: scope.t1 } });
  await act(async () => {
    a.resolve(fixture(requestA));
    c.resolve(fixture(requestC));
  });
  expectReset();
  expect(screen.queryByTestId("known-payouts-result")).not.toBeInTheDocument();
  expect(evaluateInstrumentWhatIf).toHaveBeenCalledTimes(2);
});
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
