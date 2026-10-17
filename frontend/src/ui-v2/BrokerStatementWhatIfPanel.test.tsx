import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  type BrokerStatementReturn,
  formatStatementPercent,
  statementMoney,
} from "../api/brokerStatementReturn";
import {
  type WhatIfAssumptions,
  type WhatIfContext,
  type WhatIfResult,
  whatIfRequest,
} from "../api/brokerStatementWhatIf";
import { BrokerStatementWhatIfPanel } from "./BrokerStatementWhatIfPanel";

vi.mock("../api/brokerStatementWhatIf", async (original) => ({
  ...(await original<typeof import("../api/brokerStatementWhatIf")>()),
  whatIfRequest: vi.fn(),
}));
const endpoint = (day: string, value: string) => ({
  account_id: 1,
  valuation_date: day,
  timing: "eod" as const,
  currency: "RUB",
  positions_value_kopecks: value,
  cash_kopecks: "0",
  total_value_kopecks: value,
  inventory_state: "complete" as const,
  positions: [],
});
const actual: BrokerStatementReturn = {
  method: "broker_statement_mwr_period_v1",
  scope: "account",
  account_id: 1,
  t0: "2030-08-31",
  t1: "2030-09-30",
  currency: "RUB",
  annualized: false,
  status: "unavailable",
  quality: "unavailable",
  rate_fraction: null,
  reason_codes: ["account_crossing_coverage_unproved"],
  warnings: ["По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"],
  opening: endpoint("2030-08-31", "1000000"),
  closing: endpoint("2030-09-30", "1121100"),
  material_fingerprint: "a".repeat(64),
  cash_coverage_state: "unknown",
  cash_coverage_revision_id: null,
  membership_state: "complete",
  exposure_state: "unknown",
  bond_nkd_basis: "unknown",
  crossings: [],
  sources: [
    {
      import_id: 1,
      document_sha256: "b".repeat(64),
      parser_version: "mybroker-s1-v2",
      source_signature: "c".repeat(64),
      request_id: "synthetic",
      confirmation_digest: "d".repeat(64),
    },
  ],
};
const context: WhatIfContext = {
  kind: "broker_statement_what_if_context_v1",
  method: "broker_statement_what_if_mwr_period_v1",
  scope: "account",
  account_id: 1,
  request_id: "synthetic",
  t0: actual.t0,
  t1: actual.t1,
  actual_result: actual,
  observed: { opening: actual.opening, closing: actual.closing, capital_delta_kopecks: "121100" },
  diagnostic_inventory: {},
  fixed_schedule: [],
  optional_candidate: {
    source_reference: "native:1",
    event_date: "2030-09-15",
    signed_amount_kopecks: "100000",
    provenance: "assumed_native_incoming",
  },
  required_assumptions: [
    {
      requirement_id: "basis",
      subject: "Synthetic basis",
      slot: "native_basis",
      source_references: ["source:1"],
      choices: ["native_totals_continuously"],
    },
    {
      requirement_id: "candidate",
      subject: "Synthetic candidate",
      slot: "schedule",
      source_references: ["native:1"],
      choices: ["include_as_account_inflow", "exclude_from_external_schedule"],
    },
    {
      requirement_id: "schedule",
      subject: "Synthetic schedule",
      slot: "schedule",
      source_references: ["native:1"],
      choices: ["use_displayed_schedule"],
    },
  ],
  hard_blockers: [],
  limitations: ["Не фактическая доходность; полнота периода неизвестна.", ...actual.warnings],
  context_fingerprint: "e".repeat(64),
};
function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Missing test input");
  return value;
}
function result(assumptions: WhatIfAssumptions): WhatIfResult {
  const ready = assumptions.selections.length === 3 && assumptions.schedule_mode !== null;
  return {
    kind: "broker_statement_what_if_result_v1",
    method: context.method,
    scope: "account",
    authority: "hypothetical",
    currency: "RUB",
    annualized: false,
    status: ready ? "hypothetical" : "needs_assumptions",
    account_id: 1,
    request_id: "synthetic",
    t0: actual.t0,
    t1: actual.t1,
    scenario_result_kopecks: ready ? "21100" : null,
    scenario_rate_fraction: ready ? "0.0201" : null,
    assumed_schedule: context.optional_candidate ? [context.optional_candidate] : [],
    assumptions,
    actual_result: actual,
    context,
    limitations: context.limitations,
    reason_codes: [],
    context_fingerprint: context.context_fingerprint,
    assumption_fingerprint: "f".repeat(64),
    result_fingerprint: "1".repeat(64),
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(whatIfRequest).mockImplementation(
    async (operation, _actual, _file, _signal, _context, assumptions) =>
      operation === "context" ? context : (result(required(assumptions)) as never),
  );
  URL.createObjectURL = vi.fn(() => "blob:synthetic");
  URL.revokeObjectURL = vi.fn();
});
async function load() {
  const user = userEvent.setup();
  await user.upload(
    screen.getByLabelText("Оригинал WHAT-IF"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить контекст сценария" }));
  await screen.findByText("Наблюдаемые нативные факты");
  return user;
}
async function choose(user: ReturnType<typeof userEvent.setup>) {
  for (const r of context.required_assumptions)
    await user.selectOptions(screen.getByLabelText(r.requirement_id), r.choices[0]);
  await user.selectOptions(screen.getByLabelText("Режим графика"), "dated");
}

it("never defaults missing assumptions to zero and keeps actual unavailable beside the scenario", async () => {
  render(<BrokerStatementWhatIfPanel actual={actual} />);
  const user = await load();
  expect(screen.getByLabelText("basis")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
  expect(
    await screen.findByText("Выбери все необходимые допущения и режим графика."),
  ).toBeVisible();
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
  expect(await screen.findByText(/2,01%/)).toBeVisible();
  expect(
    screen.getByText(/Условный результат после учёта выбранных внешних движений: 211,00/),
  ).toBeVisible();
  expect(screen.getByText(/Фактический S3: Недоступна/)).toBeVisible();
  expect(screen.getByText("Не фактическая доходность; полнота периода неизвестна.")).toBeVisible();
});

it("clears the displayed result and disables export on every assumption edit", async () => {
  render(<BrokerStatementWhatIfPanel actual={actual} />);
  const user = await load();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
  await screen.findByText(/2,01%/);
  await user.selectOptions(screen.getByLabelText("candidate"), "exclude_from_external_schedule");
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Экспорт сценария JSON с перепроверкой" }),
  ).toBeDisabled();
});

it("rejects a late evaluation after an edit even if transport ignores abort", async () => {
  render(<BrokerStatementWhatIfPanel actual={actual} />);
  const user = await load();
  await choose(user);
  let resolve: (value: WhatIfResult) => void = () => {};
  let captured: WhatIfAssumptions;
  vi.mocked(whatIfRequest).mockImplementationOnce((_op, _a, _f, _s, _c, assumptions) => {
    captured = required(assumptions);
    return new Promise((r) => {
      resolve = r as typeof resolve;
    });
  });
  await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
  await user.selectOptions(screen.getByLabelText("candidate"), "exclude_from_external_schedule");
  await act(async () => resolve(result(captured)));
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
});

it.each(["method", "period", "fingerprint", "assumptions"])(
  "refuses mismatched %s and clears the context",
  async (mismatch) => {
    render(<BrokerStatementWhatIfPanel actual={actual} />);
    const user = await load();
    await choose(user);
    vi.mocked(whatIfRequest).mockImplementationOnce(async (_op, _a, _f, _s, _c, assumptions) => {
      const value = result(required(assumptions));
      if (mismatch === "method") Object.assign(value, { method: "wrong" });
      if (mismatch === "period") value.t0 = "2030-09-01";
      if (mismatch === "fingerprint") value.context_fingerprint = "0".repeat(64);
      if (mismatch === "assumptions")
        value.assumptions = { ...required(assumptions), selections: [] };
      return value as never;
    });
    await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("basis")).not.toBeInTheDocument();
  },
);

it("downloads only a fresh bound full DTO and clears on export failure", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  render(<BrokerStatementWhatIfPanel actual={actual} />);
  const user = await load();
  await choose(user);
  await user.click(screen.getByRole("button", { name: "Рассчитать условную оценку" }));
  await screen.findByText(/2,01%/);
  await user.click(screen.getByRole("button", { name: "Экспорт сценария JSON с перепроверкой" }));
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(vi.mocked(whatIfRequest).mock.calls.at(-1)?.[0]).toBe("export");
  expect(vi.mocked(whatIfRequest).mock.calls.at(-1)?.[6]?.result_fingerprint).toBe("1".repeat(64));
  vi.mocked(whatIfRequest).mockRejectedValueOnce(new Error("what_if_context_stale"));
  await user.click(screen.getByRole("button", { name: "Экспорт сценария JSON с перепроверкой" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(/2,01%/)).not.toBeInTheDocument();
  click.mockRestore();
});

it("does not revive a late context across source A → B → A or original replacement", async () => {
  let resolve: (value: WhatIfContext) => void = () => {};
  vi.mocked(whatIfRequest).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r as typeof resolve;
      }),
  );
  const view = render(<BrokerStatementWhatIfPanel key="A" actual={actual} />);
  const user = userEvent.setup();
  await user.upload(screen.getByLabelText("Оригинал WHAT-IF"), new File(["A"], "a.xml"));
  await user.click(screen.getByRole("button", { name: "Проверить контекст сценария" }));
  view.rerender(<BrokerStatementWhatIfPanel key="B" actual={{ ...actual, account_id: 2 }} />);
  view.rerender(<BrokerStatementWhatIfPanel key="A" actual={actual} />);
  await act(async () => resolve(context));
  expect(screen.queryByText("Наблюдаемые нативные факты")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Проверить контекст сценария" })).toBeDisabled();
  await load();
  await user.upload(screen.getByLabelText("Оригинал WHAT-IF"), new File(["B"], "b.xml"));
  expect(screen.queryByText("Наблюдаемые нативные факты")).not.toBeInTheDocument();
});

it("preserves BigInt, HALF_UP fraction units and negative-zero formatting", () => {
  expect(statementMoney("9007199254740993")).toBe("90 071 992 547 409,93 ₽");
  expect(formatStatementPercent("0.02015")).toBe("2,02%");
  expect(formatStatementPercent("-0.0000001")).toBe("0,00%");
});
