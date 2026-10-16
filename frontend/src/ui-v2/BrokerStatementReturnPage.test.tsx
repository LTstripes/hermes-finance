import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import {
  type BrokerStatementReturn,
  formatStatementPercent,
  getStatementReturn,
  listStatementSources,
  statementMoney,
} from "../api/brokerStatementReturn";
import BrokerStatementReturnPage from "./BrokerStatementReturnPage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/brokerStatementReturn", async (original) => ({
  ...(await original<typeof import("../api/brokerStatementReturn")>()),
  getStatementReturn: vi.fn(),
  listStatementSources: vi.fn(),
}));

function statementFixture(account = 1): BrokerStatementReturn {
  const endpoint = (day: string, value: string) => ({
    account_id: account,
    valuation_date: day,
    timing: "eod" as const,
    currency: "RUB",
    positions_value_kopecks: value,
    cash_kopecks: "0",
    total_value_kopecks: value,
    inventory_state: "complete" as const,
    positions: [],
  });
  return {
    method: "broker_statement_mwr_period_v1",
    scope: "account",
    account_id: account,
    t0: "2026-08-31",
    t1: "2026-09-30",
    currency: "RUB",
    annualized: false,
    status: "indicative",
    quality: "indicative",
    rate_fraction: "0.0201",
    reason_codes: [],
    warnings: [
      "Доходность за фактический период; не приведена к году",
      "По оценке брокера; учёт НКД в стоимости облигаций не подтверждён",
    ],
    opening: endpoint("2026-08-31", "1000000"),
    closing: endpoint("2026-09-30", "1121100"),
    material_fingerprint: "f".repeat(64),
    cash_coverage_state: "complete",
    cash_coverage_revision_id: 1,
    membership_state: "complete",
    exposure_state: "assessed",
    bond_nkd_basis: "unknown",
    sources: [
      {
        import_id: 1,
        document_sha256: "a".repeat(64),
        parser_version: "mybroker-s1-v2",
        source_signature: "b".repeat(64),
        request_id: `source-${account}`,
        confirmation_digest: "c".repeat(64),
      },
    ],
    crossings: [
      {
        event_id: "deposit-1",
        account_id: account,
        event_date: "2026-09-15",
        currency: "RUB",
        signed_amount_kopecks: "100000",
        revision_id: 1,
        material_signature: "e".repeat(64),
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listAccounts).mockResolvedValue([
    { id: 1, name: "Synthetic A", account_type: "brokerage" },
    { id: 2, name: "Synthetic B", account_type: "brokerage" },
  ] as Awaited<ReturnType<typeof listAccounts>>);
  vi.mocked(listStatementSources).mockImplementation(async (account) => [
    { request_id: `source-${account}`, account_id: account, t0: "2026-08-31", t1: "2026-09-30" },
  ]);
  vi.mocked(getStatementReturn).mockImplementation(async (account) => statementFixture(account));
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BrokerStatementReturnPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}
async function choose(user: ReturnType<typeof userEvent.setup>, account = "1") {
  await screen.findByRole("option", { name: "Synthetic A" });
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), account);
  await waitFor(() => expect(screen.getByLabelText("Принятая выписка")).toBeEnabled());
  await user.selectOptions(screen.getByLabelText("Принятая выписка"), `source-${account}`);
}

it.each([
  ["0.0201", "2,01%"],
  ["0", "0,00%"],
  ["0.028", "2,80%"],
  ["-0.2", "−20,00%"],
  [null, "Недоступна"],
  ["0.0201499999999999", "2,01%"],
  ["0.02015", "2,02%"],
])("formats fraction %s without annualizing or binary float", (value, expected) => {
  expect(formatStatementPercent(value)).toBe(expected);
});
it("preserves large exact kopecks and unknown cash", () => {
  expect(statementMoney("9007199254740993")).toBe("90 071 992 547 409,93 ₽");
  expect(statementMoney(null)).toBe("Не подтверждено");
});
it("displays account, EOD facts, sign, caveat, fraction and bound export", async () => {
  const user = setup();
  await choose(user);
  expect(await screen.findByText("2,01%")).toBeVisible();
  expect(
    screen.getByText("По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"),
  ).toBeVisible();
  expect(screen.getByText("Доходность за фактический период; не приведена к году")).toBeVisible();
  expect(screen.getByText(/15.09.2026: \+1/)).toBeVisible();
  expect(screen.getByRole("link", { name: /Экспорт результата/ })).toHaveAttribute(
    "href",
    `/api/broker-statement-returns/export?account_id=1&request_id=source-1&expected_fingerprint=${"f".repeat(64)}`,
  );
});
it("shows null with native facts and missing-flow reason, never guessed zero", async () => {
  vi.mocked(getStatementReturn).mockResolvedValue({
    ...statementFixture(),
    status: "unavailable",
    quality: "unavailable",
    rate_fraction: null,
    crossings: [],
    cash_coverage_state: "unknown",
    reason_codes: [
      "account_crossing_coverage_unproved",
      "money_disposition_unresolved",
      "future_h2_code",
    ],
  });
  const user = setup();
  await choose(user);
  expect(await screen.findByText("Недоступна")).toBeVisible();
  expect(
    screen.getByText("Не подтверждён полный список датированных пополнений и выводов счёта."),
  ).toBeVisible();
  expect(screen.queryByText("0,00%")).not.toBeInTheDocument();
  expect(screen.getByText(/H2 не может подтвердить назначение/)).toBeVisible();
  expect(screen.getByText(/Не подтверждено основание: future_h2_code/)).toBeVisible();
  expect(screen.getAllByText(/10\s000,00 ₽/)).toHaveLength(2);
});
it("rejects wrong account, period, endpoint and annualization responses", async () => {
  vi.mocked(getStatementReturn).mockResolvedValue({ ...statementFixture(), t1: "2026-10-31" });
  const user = setup();
  await choose(user);
  expect(await screen.findByRole("alert")).toHaveTextContent("Ответ не соответствует");
  expect(screen.queryByText("2,01%")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Экспорт результата/ })).not.toBeInTheDocument();
});
it("hides previous account immediately and ignores a late response after switching", async () => {
  let resolve!: (value: BrokerStatementReturn) => void;
  vi.mocked(getStatementReturn).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const user = setup();
  await choose(user);
  await screen.findByText("Проверяем актуальные основания…");
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "2");
  resolve(statementFixture());
  await waitFor(() => expect(screen.queryByText("2,01%")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Принятая выписка")).toHaveValue("");
  await choose(user, "2");
  expect(await screen.findByText("2,01%")).toBeVisible();
  expect(screen.getByRole("link", { name: /Экспорт результата/ }).getAttribute("href")).toContain(
    "account_id=2",
  );
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "1");
  expect(screen.queryByText("2,01%")).not.toBeInTheDocument();
});
