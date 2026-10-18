import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  type ProvisionalAssumptions,
  type ProvisionalContext,
  type ProvisionalResult,
  provisionalRequest,
} from "../../api/brokerStatementProvisional";
import type { SourceIntake } from "../../api/sourceIntake";
import { BrokerProvisionalEstimate } from "./BrokerProvisionalEstimate";

vi.mock("../../api/brokerStatementProvisional", async (original) => ({
  ...(await original<typeof import("../../api/brokerStatementProvisional")>()),
  provisionalRequest: vi.fn(),
}));

const intake: SourceIntake = {
  contract_version: "source_intake_v1",
  id: 1,
  document_sha256: "a".repeat(64),
  generation: 1,
  head_seq: 2,
  manifest_digest: "c".repeat(64),
  original_required: true,
  covered_from: "2030-04-01",
  covered_to: "2030-04-30",
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
    covered_from: "2030-04-01",
    covered_to: "2030-04-30",
    source_accounts: ["synthetic"],
    positions: [],
    rub_money: [],
    trades: [],
    money: [],
    section_inventory: {},
  },
  proposals: [],
  observations: [],
  exceptions: [],
  financial_authority: "none",
  finance_link: null,
  history: [],
};
const context: ProvisionalContext = {
  kind: "broker_source_provisional_context_v1",
  method: "broker_source_provisional_mwr_period_v1",
  scope: "account",
  authority: "provisional",
  currency: "RUB",
  annualized: false,
  intake_id: 1,
  account_id: 7,
  t0: "2030-03-31",
  t1: "2030-04-30",
  journal: {
    intake_id: 1,
    head_seq: 2,
    manifest_digest: "c".repeat(64),
    document_sha256: "a".repeat(64),
    parser: "mybroker-s1-v2",
    finance_link_present: false,
    exceptions: [],
  },
  observed: {
    positions_value_opening_kopecks: "900000",
    cash_opening_kopecks: "100000",
    total_opening_kopecks: "1000000",
    positions_value_closing_kopecks: "1021100",
    cash_closing_kopecks: "100000",
    total_closing_kopecks: "1121100",
    reported_value_change_kopecks: "121100",
    positions: [
      {
        source_reference: "position:1:0:synthetic",
        isin: "RU000A000000",
        ordinal: 0,
        beginning_quantity: "10",
        ending_quantity: "10",
        beginning_value: "9000",
        ending_value: "10211",
        beginning_value_kopecks: "900000",
        ending_value_kopecks: "1021100",
      },
    ],
    cash: {
      source_reference: "cash:1:0:synthetic",
      beginning_amount: "1000",
      ending_amount: "1000",
      beginning_kopecks: "100000",
      ending_kopecks: "100000",
    },
  },
  candidates: [
    {
      source_reference: `money:1:money:0:${"e".repeat(64)}`,
      event_date: "2030-04-15",
      signed_amount_kopecks: "100000",
      source_amount: "1000",
      provenance: "assumed_native_incoming",
    },
  ],
  known_payouts: [],
  required_assumptions: [
    {
      requirement_id: "native_basis",
      subject: "Нативные EOD-итоги выбранного счёта",
      slot: "native_basis",
      source_references: ["source:1"],
      choices: ["native_totals_continuously"],
    },
    {
      requirement_id: "candidate:0:eeeeeeeeeeee",
      subject: "2030-04-15 · входящий кандидат · +1000 RUB",
      slot: "candidate",
      source_references: [`money:1:money:0:${"e".repeat(64)}`],
      choices: ["include_as_account_inflow", "exclude_from_external_schedule"],
    },
    {
      requirement_id: "schedule",
      subject: "Явный график выбранных внешних движений",
      slot: "schedule",
      source_references: [`money:1:money:0:${"e".repeat(64)}`],
      choices: ["use_displayed_schedule"],
    },
    {
      requirement_id: "remaining_crossings",
      subject: "Только выбранный счёт и его точный период",
      slot: "remaining_crossings",
      source_references: ["source:1", `money:1:money:0:${"e".repeat(64)}`],
      choices: ["no_other_account_crossings"],
    },
  ],
  hard_blockers: [],
  limitations: [
    "Предварительная оценка, не факт: не S3, не Close, не XIRR/TWRR и не финансовый Apply.",
    "Комиссии, НКД, купоны, расчёты по сделкам и pending не приравниваются к нулю.",
  ],
  context_fingerprint: "d".repeat(64),
};
const resultFingerprint = "f".repeat(64);

function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Missing test input");
  return value;
}
function result(assumptions: ProvisionalAssumptions): ProvisionalResult {
  const ready =
    assumptions.schedule_mode !== null &&
    assumptions.selections.length === context.required_assumptions.length;
  return {
    kind: "broker_source_provisional_result_v1",
    method: context.method,
    scope: "account",
    authority: "provisional",
    currency: "RUB",
    annualized: false,
    status: ready ? "provisional" : "needs_assumptions",
    intake_id: 1,
    account_id: 7,
    t0: context.t0,
    t1: context.t1,
    reported_value_change_kopecks: context.observed.reported_value_change_kopecks,
    scenario_result_kopecks: ready ? "21100" : null,
    scenario_rate_fraction: ready ? "0.0201" : null,
    assumed_schedule: ready ? context.candidates : [],
    assumptions,
    context,
    alternatives: ready
      ? [
          {
            label: "Альтернатива: кандидат исключён из внешних движений",
            scenario_result_kopecks: "121100",
            scenario_rate_fraction: "0.1211",
            included_candidate_references: [],
          },
        ]
      : [],
    limitations: context.limitations,
    reason_codes: [],
    context_fingerprint: context.context_fingerprint,
    assumption_fingerprint: "1".repeat(64),
    result_fingerprint: resultFingerprint,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(provisionalRequest).mockImplementation(
    async (operation, _i, _f, _s, _c, assumptions) =>
      operation === "context" ? context : (result(required(assumptions)) as never),
  );
  URL.createObjectURL = vi.fn(() => "blob:synthetic");
  URL.revokeObjectURL = vi.fn();
});

async function load() {
  const user = userEvent.setup();
  render(
    <BrokerProvisionalEstimate
      intake={intake}
      file={new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" })}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Рассчитать наблюдаемые величины" }));
  await screen.findByText("Наблюдаемые величины брокера");
  return user;
}
async function choose(user: ReturnType<typeof userEvent.setup>) {
  for (const requirement of context.required_assumptions) {
    await user.selectOptions(
      screen.getByLabelText(requirement.requirement_id),
      requirement.choices[0],
    );
  }
  await user.selectOptions(screen.getByLabelText("Режим графика"), "dated");
}

it("separates observed broker values from an explicit nonannualized scenario", async () => {
  const user = await load();
  expect(screen.getByText(/Изменение стоимости по отчёту брокера: 1.211,00/)).toBeVisible();
  expect(screen.getByLabelText("native_basis")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Рассчитать предварительный сценарий" }));
  expect(
    await screen.findByText("Выбери все необходимые допущения и режим графика."),
  ).toBeVisible();
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать предварительный сценарий" }));
  expect(await screen.findByText(/2,01%/)).toBeVisible();
  expect(
    screen.getByText(/Сценарный результат после выбранных внешних движений: 211,00/),
  ).toBeVisible();
  expect(screen.getByText(/за фактический период, не аннулизировано/)).toBeVisible();
  expect(
    within(screen.getByRole("region", { name: "Результат предварительного расчёта" })).getByText(
      /не факт: не S3/,
    ),
  ).toBeVisible();
  expect(screen.getByText(/Альтернатива: кандидат исключён/)).toBeVisible();
});

it("clears the result and disables export on every assumption edit", async () => {
  const user = await load();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать предварительный сценарий" }));
  await screen.findByText(/2,01%/);
  await user.selectOptions(
    screen.getByLabelText("candidate:0:eeeeeeeeeeee"),
    "exclude_from_external_schedule",
  );
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Экспорт предварительного расчёта JSON" }),
  ).toBeDisabled();
});

it("downloads only a fresh bound full result", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const user = await load();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать предварительный сценарий" }));
  await screen.findByText(/2,01%/);
  await user.click(screen.getByRole("button", { name: "Экспорт предварительного расчёта JSON" }));
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(vi.mocked(provisionalRequest).mock.calls.at(-1)?.[0]).toBe("export");
  expect(vi.mocked(provisionalRequest).mock.calls.at(-1)?.[6]?.result_fingerprint).toBe(
    resultFingerprint,
  );
  click.mockRestore();
});

it("rejects a late evaluation after an assumption edit", async () => {
  const user = await load();
  await choose(user);
  let resolve: (value: ProvisionalResult) => void = () => {};
  let captured: ProvisionalAssumptions;
  vi.mocked(provisionalRequest).mockImplementationOnce((_op, _i, _f, _s, _c, assumptions) => {
    captured = required(assumptions);
    return new Promise((r) => {
      resolve = r as typeof resolve;
    });
  });
  await user.click(screen.getByRole("button", { name: "Рассчитать предварительный сценарий" }));
  await user.selectOptions(
    screen.getByLabelText("candidate:0:eeeeeeeeeeee"),
    "exclude_from_external_schedule",
  );
  await act(async () => resolve(result(captured)));
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
});

it("requires the exact original and never calculates without it", async () => {
  render(<BrokerProvisionalEstimate intake={intake} file={null} />);
  expect(screen.getByRole("button", { name: "Рассчитать наблюдаемые величины" })).toBeDisabled();
  expect(screen.getByText(/Оригинал XML не выбран/)).toBeVisible();
});
