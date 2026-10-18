import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { SourceIntake } from "../../api/sourceIntake";
import {
  assumptionKeys,
  readSourceIntakeResult,
  type SourceIntakeResult,
  type SourceIntakeResultRequest,
} from "../../api/sourceIntakeResult";
import { SourceIntakeInstrumentResult } from "./SourceIntakeInstrumentResult";

vi.mock("../../api/sourceIntakeResult", async (original) => ({
  ...(await original<typeof import("../../api/sourceIntakeResult")>()),
  readSourceIntakeResult: vi.fn(),
}));

const stored: SourceIntake = {
  contract_version: "source_intake_v1",
  id: 1,
  document_sha256: "a".repeat(64),
  generation: 1,
  head_seq: 2,
  original_required: true,
  covered_from: "2030-02-01",
  covered_to: "2030-02-28",
  state: {
    account_id: 7,
    reporting_month_id: 1,
    default_enabled: true,
    account_currency: null,
    policy_revision: 1,
    overrides: {},
    instrument_decisions: [],
    deferred_isins: [],
  },
  document: {
    provider: "alfa_mybroker",
    parser: "mybroker-s1-v2",
    document_sha256: "a".repeat(64),
    filename_account: "synthetic",
    covered_from: "2030-02-01",
    covered_to: "2030-02-28",
    source_accounts: ["synthetic"],
    positions: [],
    rub_money: [],
    trades: [],
    money: [],
    section_inventory: {},
  },
  proposals: [
    {
      isin: "RU000A000000",
      source_name: "Synthetic stock",
      intake_status: "matched",
      hermes_id: 9,
      instrument_type: "stock",
      currency: "RUB",
      action: "reuse",
      mapping_id: 3,
      mapping_action: "reuse",
      evidence_gaps: [],
      review_reasons: [],
      candidates: [],
      currency_assessment: {
        observed_denomination: "RUB",
        effective_currency: "RUB",
        basis: "existing_catalogue",
        denomination_proven: false,
        provisional: false,
        policy_revision: 1,
        override_revision: null,
        reasons: [],
      },
    },
  ],
  observations: [{ id: 1, section: "positions", ordinal: 0, row_class: "recognized" }],
  exceptions: ["source_intake_pending"],
  financial_authority: "none",
  finance_link: null,
  history: [{ seq: 2, operation: "manifest", request_id: "saved", reviewer: "owner_local" }],
};

function fixture(r: SourceIntakeResultRequest): SourceIntakeResult {
  const missing = assumptionKeys.filter((key) => !r.chosen[key]);
  return {
    method: "source-intake-fixed-holding-result",
    version: 1,
    authority: "hypothetical",
    request_nonce: r.nonce,
    intake: {
      id: r.intakeId,
      head_seq: 2,
      manifest_digest: "b".repeat(64),
      document_sha256: "a".repeat(64),
      covered_from: "2030-02-01",
      covered_to: "2030-02-28",
      finance_link: "absent",
      exceptions: ["source_intake_pending"],
    },
    account: { id: 7, name: "Synthetic account" },
    instrument: {
      isin: r.isin,
      instrument_type: "stock",
      hermes_id: 9,
      name: "Synthetic stock",
    },
    currency_assessment: {
      observed_denomination: "RUB",
      effective_currency: "RUB",
      basis: "existing_catalogue",
      provisional: false,
    },
    t0: r.t0,
    t1: r.t1,
    interval: "(t0,t1]",
    currency: "RUB",
    observed: {
      availability: "available",
      quantity: "10",
      beginning_quantity: "10",
      forward_quantity: "10",
      beginning_value: "1000.00",
      ending_value: "900.00",
      beginning_basis: "previous_day_eod",
      ending_basis: "covered_to_eod",
      value_change: "-100.00",
      value_change_fraction: "-0.1",
      value_change_percent: "-10",
      bond_nkd_basis: "not_applicable",
      source_row: { ordinal: 0, locator: "0", row_fingerprint: "c".repeat(64) },
      reason_codes: [],
    },
    known: {
      payouts: null,
      trades: null,
      net_distributions: missing.length ? null : "150.00",
      confirmed_cost_legs: [],
      cost_coverage: "unknown",
      reason_codes: [],
    },
    chosen_assumptions: r.chosen,
    missing_assumptions: missing,
    hard_blockers: missing.length ? ["proven_net_dividend_required"] : [],
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

function mount(intake: SourceIntake = stored) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SourceIntakeInstrumentResult intake={intake} />
    </QueryClientProvider>,
  );
}

async function chooseAll(user: ReturnType<typeof userEvent.setup>) {
  for (const key of assumptionKeys) {
    await user.click(screen.getByLabelText(new RegExp(labels(key))));
  }
}

function labels(key: (typeof assumptionKeys)[number]): string {
  if (key === "no_unobserved_movements") return "отсутствие дополнительных ненаблюдаемых сделок";
  if (key === "no_unobserved_payouts") return "отсутствие дополнительных ненаблюдаемых выплат";
  return "отсутствие других отдельно относимых расходов";
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("requires all three assumptions and then shows RUB and percent separately from the quote", async () => {
  const user = userEvent.setup();
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => fixture(request));
  mount();
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledOnce());
  expect(await screen.findByText(/недоступен \(RUB и % неизвестны\)/)).toBeVisible();
  expect(screen.getByText(/Выбраны не все три допущения/)).toBeVisible();
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("+50,00 ₽ / +5% за период")).toBeVisible();
  expect(screen.getByText(/-100,00 ₽ \/ -10%/)).toBeVisible();
  expect(screen.getByText(/Разбор #1, версия 2/)).toBeVisible();
  expect(
    screen.getByText(/Подтверждённых отдельных комиссий и НКД не найдено/),
  ).toBeInTheDocument();
});

it("keeps a blocked bond request numeric-free with an explicit reason", async () => {
  const user = userEvent.setup();
  const bond: SourceIntake = {
    ...structuredClone(stored),
    proposals: [
      {
        ...structuredClone(stored.proposals[0]),
        isin: "RU000A000001",
        source_name: "Synthetic bond",
        instrument_type: "bond",
        hermes_id: 10,
      },
    ],
  };
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => {
    const result = fixture(request);
    return {
      ...result,
      instrument: { ...result.instrument, isin: "RU000A000001", instrument_type: "bond" },
      observed: { ...result.observed, bond_nkd_basis: "unknown" },
      known: { ...result.known, net_distributions: null },
      hard_blockers: ["bond_dirty_basis_source_unproven"],
      hypothetical_result: {
        ...result.hypothetical_result,
        conditional_result: null,
        conditional_period_fraction: null,
        conditional_period_percent: null,
      },
    };
  });
  mount(bond);
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledOnce());
  expect(await screen.findByText(/Облигации заблокированы/)).toBeVisible();
  expect(screen.getByText(/недоступен \(RUB и % неизвестны\)/)).toBeVisible();
});

it("rejects a response that does not match the requested evaluation", async () => {
  const user = userEvent.setup();
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => ({
    ...fixture(request),
    request_nonce: "other-nonce",
  }));
  mount();
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledOnce());
  expect(
    await screen.findByText("Ответ не соответствует выбранному сценарию. Повторите расчёт."),
  ).toBeVisible();
  expect(screen.queryByTestId("source-intake-result")).toBeNull();
});

it("rejects a numeric response while the identity decision is deferred", async () => {
  const user = userEvent.setup();
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => ({
    ...fixture(request),
    intake: {
      ...fixture(request).intake,
      exceptions: ["source_intake_identity_deferred", "source_intake_pending"],
    },
  }));
  mount();
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledOnce());
  expect(
    await screen.findByText("Ответ не соответствует выбранному сценарию. Повторите расчёт."),
  ).toBeVisible();
  expect(screen.queryByTestId("source-intake-result")).toBeNull();
});

it("surfaces a failed read and uses a new nonce on retry", async () => {
  const user = userEvent.setup();
  vi.mocked(readSourceIntakeResult).mockRejectedValueOnce(new Error("unavailable"));
  mount();
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  const first = vi.mocked(readSourceIntakeResult).mock.calls[0][0].nonce;
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => fixture(request));
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledTimes(2));
  expect(vi.mocked(readSourceIntakeResult).mock.calls[1][0].nonce).not.toBe(first);
  expect(await screen.findByText("+50,00 ₽ / +5% за период")).toBeVisible();
});

it("hides the previous result after the selection changes", async () => {
  const user = userEvent.setup();
  vi.mocked(readSourceIntakeResult).mockImplementation(async (request) => fixture(request));
  mount();
  await chooseAll(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условный результат" }));
  await waitFor(() => expect(readSourceIntakeResult).toHaveBeenCalledOnce());
  expect(await screen.findByTestId("source-intake-result")).toBeVisible();
  await user.click(screen.getByLabelText(new RegExp(labels("no_unobserved_payouts"))));
  expect(screen.queryByTestId("source-intake-result")).toBeNull();
});
