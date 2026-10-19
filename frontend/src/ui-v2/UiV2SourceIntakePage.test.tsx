import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { listAllSourceIntakes, readSourceIntake, type SourceIntake } from "../api/sourceIntake";
import UiV2SourceIntakePage from "./UiV2SourceIntakePage";

vi.mock("../api/sourceIntake", async (original) => ({
  ...(await original<typeof import("../api/sourceIntake")>()),
  listAllSourceIntakes: vi.fn(),
  readSourceIntake: vi.fn(),
}));
vi.mock("../components/month-close/BrokerProvisionalEstimate", () => ({
  BrokerProvisionalEstimate: ({ intake, file }: { intake: SourceIntake; file: File | null }) => (
    <div data-testid="provisional-panel">
      {intake.id}:{file?.name ?? "no-file"}
    </div>
  ),
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
    account_id: null,
    reporting_month_id: null,
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
  observations: [{ id: 1, section: "positions", ordinal: 0, row_class: "recognized" }],
  exceptions: ["source_intake_pending"],
  financial_authority: "none",
  finance_link: null,
  history: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listAllSourceIntakes).mockResolvedValue([structuredClone(intake)]);
  vi.mocked(readSourceIntake).mockResolvedValue(structuredClone(intake));
});

it("selects an existing unbound intake and reattaches the exact original without a month", async () => {
  const user = userEvent.setup();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <UiV2SourceIntakePage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByRole("heading", { name: "Разбор источника" })).toBeVisible();
  await user.selectOptions(await screen.findByLabelText("Сохранённый разбор"), "1");
  expect(await screen.findByText(/без привязки к Hermes-счёту или отчётному месяцу/)).toBeVisible();
  await user.upload(
    screen.getByLabelText("Точный оригинал XML"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  expect(await screen.findByTestId("provisional-panel")).toHaveTextContent("1:synthetic.xml");
  expect(vi.mocked(listAllSourceIntakes)).toHaveBeenCalledOnce();
  expect(vi.mocked(readSourceIntake)).toHaveBeenCalledWith(1, expect.any(AbortSignal));
});
