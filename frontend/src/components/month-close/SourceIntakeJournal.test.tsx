import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  confirmIntakeReview,
  listSourceIntakes,
  previewIntakeReview,
  readSourceIntake,
  type SourceIntake,
  saveSourceIntake,
} from "../../api/sourceIntake";
import { brokerOriginalSession } from "./brokerOriginalSession";
import { SourceIntakeJournal } from "./SourceIntakeJournal";

vi.mock("../../api/sourceIntake", () => ({
  listSourceIntakes: vi.fn(),
  readSourceIntake: vi.fn(),
  saveSourceIntake: vi.fn(),
  previewIntakeReview: vi.fn(),
  confirmIntakeReview: vi.fn(),
}));

const original = new File(["synthetic original"], "synthetic.xml", { type: "application/xml" });
const stored: SourceIntake = {
  contract_version: "source_intake_v1",
  id: 1,
  document_sha256: "a".repeat(64),
  generation: 1,
  head_seq: 2,
  manifest_digest: "c".repeat(64),
  original_required: true,
  covered_from: "2030-01-01",
  covered_to: "2030-01-31",
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
    covered_from: "2030-01-01",
    covered_to: "2030-01-31",
    source_accounts: ["synthetic"],
    positions: [],
    rub_money: [],
    trades: [],
    money: [],
    section_inventory: {},
  },
  proposals: [
    {
      isin: "RU000A000001",
      source_name: "Synthetic pending",
      intake_status: "pending_review",
      hermes_id: null,
      instrument_type: "bond",
      currency: null,
      action: "stage_create",
      mapping_id: null,
      mapping_action: "stage_create",
      evidence_gaps: ["instrument_currency_unproven"],
      review_reasons: ["instrument_currency_unproven"],
      candidates: [],
      currency_assessment: {
        observed_denomination: null,
        effective_currency: "RUB",
        basis: "owner_default_rub",
        denomination_proven: false,
        provisional: true,
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

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listSourceIntakes).mockResolvedValue([structuredClone(stored)]);
  vi.mocked(previewIntakeReview).mockResolvedValue({
    confirmation_digest: "b".repeat(64),
    financial_effects: 0,
  });
});

function setup(file: File | null = original) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  brokerOriginalSession(client).select(file, 1, "7");
  const changed = vi.fn();
  const content = (
    <QueryClientProvider client={client}>
      <SourceIntakeJournal
        monthId={1}
        closed={false}
        disabled={false}
        preview={null}
        receipts={[]}
        onReview={vi.fn()}
        onChanged={changed}
      />
    </QueryClientProvider>
  );
  return { ...render(content), client, changed };
}

it("retains the grouped queue after reload without bytes; no browser storage or financial command", async () => {
  const user = userEvent.setup();
  setup(null);
  await user.selectOptions(await screen.findByLabelText("Сохранённый разбор"), "1");
  expect(screen.getByText(/RUB — допущение Owner/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  expect(screen.getByLabelText("Валюта предложения RU000A000001")).toHaveValue("");
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(previewIntakeReview).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("acknowledged save recovers only by GET and verifies the command in history", async () => {
  const user = userEvent.setup();
  vi.mocked(saveSourceIntake).mockImplementation(async (_file, requestId) => ({
    intake_id: 1,
    request_id: requestId,
    head_seq: 2,
    duplicate: false,
  }));
  vi.mocked(readSourceIntake).mockRejectedValueOnce(new Error("synthetic lost GET"));
  vi.mocked(readSourceIntake).mockImplementationOnce(async () => {
    const requestId = vi.mocked(saveSourceIntake).mock.calls[0][1];
    return {
      ...structuredClone(stored),
      history: [{ ...stored.history[0], request_id: requestId }],
    };
  });
  setup();
  await user.click(screen.getByRole("button", { name: "Сохранить разбор" }));
  expect(await screen.findByRole("button", { name: "Повторить чтение журнала" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Сохранить разбор" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Повторить чтение журнала" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Повторить чтение журнала" })).toBeNull(),
  );
  expect(saveSourceIntake).toHaveBeenCalledTimes(1);
  expect(readSourceIntake).toHaveBeenCalledTimes(2);
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("currency override is only a reviewed journal proposal and context ABA retires its confirmation", async () => {
  const user = userEvent.setup();
  const { client } = setup();
  await user.selectOptions(await screen.findByLabelText("Сохранённый разбор"), "1");
  await user.type(screen.getByLabelText("Валюта предложения RU000A000001"), "USD");
  await user.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  expect(
    await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }),
  ).toBeEnabled();
  expect(vi.mocked(previewIntakeReview).mock.calls[0][2].overrides).toEqual([
    { isin: "RU000A000001", currency: "USD" },
  ]);
  act(() => {
    brokerOriginalSession(client).select(original, 1, "8");
    brokerOriginalSession(client).select(original, 1, "7");
  });
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Подтвердить сохранение разбора" })).toBeNull(),
  );
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("mounts the provisional estimate for the selected saved intake", async () => {
  setup();
  expect(await screen.findByText("Предварительная доходность по source-intake")).toBeVisible();
});
