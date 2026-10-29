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

function setup(
  file: File | null = original,
  intakeSelection?: Parameters<typeof SourceIntakeJournal>[0]["intakeSelection"],
  existingClient?: QueryClient,
) {
  const client =
    existingClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  brokerOriginalSession(client).select(file, 1, "7");
  const changed = vi.fn();
  const dirty = vi.fn();
  const content = (
    <QueryClientProvider client={client}>
      <SourceIntakeJournal
        intakeSelection={intakeSelection}
        monthId={1}
        closed={false}
        disabled={false}
        preview={null}
        receipts={[]}
        onReview={vi.fn()}
        onChanged={changed}
        onDirtyChange={dirty}
      />
    </QueryClientProvider>
  );
  return { ...render(content), client, changed, dirty };
}

it("reports unsaved currency/default changes even after Reload without File", async () => {
  const user = userEvent.setup();
  const { dirty } = setup(null);
  await screen.findByLabelText("Валюта предложения счёта");
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  await user.type(screen.getByLabelText("Валюта предложения счёта"), "USD");
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  expect(screen.getByLabelText("Сохранённый разбор")).toBeDisabled();
  await user.clear(screen.getByLabelText("Валюта предложения счёта"));
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  await user.click(screen.getByRole("checkbox", { name: /RUB по умолчанию/ }));
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  await user.click(screen.getByRole("checkbox", { name: /RUB по умолчанию/ }));
  expect(screen.getByLabelText("Валюта предложения RU000A000001")).toBeDisabled();
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("keeps Save binding unchanged while explicit source review can propose account classification", async () => {
  const user = userEvent.setup();
  const unbound = {
    ...structuredClone(stored),
    state: { ...stored.state, account_id: null, reporting_month_id: null },
  };
  vi.mocked(listSourceIntakes).mockResolvedValue([unbound]);
  setup();
  await screen.findByLabelText("Валюта предложения счёта");
  await user.type(screen.getByLabelText("Валюта предложения счёта"), "USD");
  await user.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  await waitFor(() => expect(previewIntakeReview).toHaveBeenCalled());
  expect(vi.mocked(previewIntakeReview).mock.calls[0][2]).toMatchObject({
    account_id: 7,
    reporting_month_id: 1,
    account_currency: "USD",
  });
  expect(confirmIntakeReview).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Сохранить разбор" }));
  await waitFor(() => expect(saveSourceIntake).toHaveBeenCalled());
  expect(vi.mocked(saveSourceIntake).mock.calls[0][3]).toBeNull();
});

it("reattaches an exact original after Reload without losing dirty currency or using an old journal head", async () => {
  const user = userEvent.setup();
  const view = setup(null);
  await user.type(await screen.findByLabelText("Валюта предложения счёта"), "USD");
  const snapshot = { ...structuredClone(stored), head_seq: 3 };
  view.rerender(
    <QueryClientProvider client={view.client}>
      <SourceIntakeJournal
        monthId={1}
        closed={false}
        disabled={false}
        preview={null}
        receipts={[]}
        onChanged={view.changed}
        onReview={vi.fn()}
        onDirtyChange={view.dirty}
        intakeSelection={{ id: 1, file: original, snapshot, preserveDraft: true }}
      />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByLabelText("Валюта предложения счёта")).toHaveValue("USD"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Проверить изменения разбора" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  await waitFor(() => expect(previewIntakeReview).toHaveBeenCalled());
  expect(vi.mocked(previewIntakeReview).mock.calls[0][2]).toMatchObject({
    expected_head_seq: 3,
    account_currency: "USD",
  });
  expect(saveSourceIntake).not.toHaveBeenCalled();
});

it("uses the newer confirmed list revision when reopening an older upload snapshot", async () => {
  const user = userEvent.setup();
  const current = { ...structuredClone(stored), head_seq: 3 };
  vi.mocked(listSourceIntakes).mockResolvedValue([current]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["source-intakes", 1], [current]);
  setup(null, { id: 1, file: original, snapshot: stored }, client);
  await user.click(await screen.findByRole("button", { name: "Проверить изменения разбора" }));
  await waitFor(() => expect(previewIntakeReview).toHaveBeenCalled());
  expect(vi.mocked(previewIntakeReview).mock.calls[0][2].expected_head_seq).toBe(3);
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("rejects a newer foreign-month binding before attaching an older upload's file", async () => {
  const current = {
    ...structuredClone(stored),
    head_seq: 3,
    state: { ...stored.state, reporting_month_id: 2 },
  };
  vi.mocked(listSourceIntakes).mockResolvedValue([current]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["source-intakes", 1], [current]);
  setup(null, { id: 1, file: original, snapshot: stored }, client);
  await screen.findByText(
    "Сохранённый источник не подтвердил текущий месяц и счёт. Выбери разбор явно.",
  );
  expect(brokerOriginalSession(client).snapshot().file).toBeNull();
  expect(previewIntakeReview).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("does not replace an unsaved identity choice when the same XML is supplied again", async () => {
  const user = userEvent.setup();
  const source = structuredClone(stored);
  source.proposals[0].candidates = [
    {
      hermes_id: 4,
      name: "Synthetic bond",
      isin: "RU000A000001",
      currency: "RUB",
      instrument_type: "bond",
      reasons: [],
    },
  ];
  vi.mocked(listSourceIntakes).mockResolvedValue([source]);
  const view = setup();
  const choice = await screen.findByLabelText("Решение для RU000A000001");
  await user.selectOptions(choice, "card:4");
  await waitFor(() => expect(view.dirty).toHaveBeenLastCalledWith(true));
  const before = brokerOriginalSession(view.client).snapshot().epoch;
  view.rerender(
    <QueryClientProvider client={view.client}>
      <SourceIntakeJournal
        monthId={1}
        closed={false}
        disabled={false}
        preview={null}
        receipts={[]}
        onChanged={view.changed}
        onReview={vi.fn()}
        onDirtyChange={view.dirty}
        intakeSelection={{
          id: 1,
          file: original,
          snapshot: { ...source, head_seq: 3 },
          preserveDraft: true,
        }}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Твой выбор сохранён в форме");
  expect(choice).toHaveValue("card:4");
  expect(brokerOriginalSession(view.client).snapshot().epoch).toBe(before);
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("retains only the selected ID across workflow remount and rereads a current row among multiple originals", async () => {
  const user = userEvent.setup();
  const second = { ...structuredClone(stored), id: 2, head_seq: 7 };
  vi.mocked(listSourceIntakes).mockResolvedValue([structuredClone(stored), second]);
  const first = setup(null);
  await user.selectOptions(await screen.findByLabelText("Сохранённый разбор"), "2");
  await screen.findByText(/Версия: 7/);
  first.unmount();
  vi.mocked(listSourceIntakes).mockResolvedValue([
    structuredClone(stored),
    { ...second, head_seq: 8 },
  ]);
  setup(null, undefined, first.client);
  await screen.findByText(/Версия: 8/);
  expect(screen.getByLabelText("Сохранённый разбор")).toHaveValue("2");
  expect(screen.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

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

it("explicit Month source selection retires another original and leaves the saved source selected without bytes", async () => {
  const other = { ...structuredClone(stored), id: 2, document_sha256: "d".repeat(64) };
  vi.mocked(listSourceIntakes).mockResolvedValue([structuredClone(stored), other]);
  const { client } = setup(original, { id: 2 });
  await waitFor(() => expect(screen.getByLabelText("Сохранённый разбор")).toHaveValue("2"));
  expect(brokerOriginalSession(client).snapshot().file).toBeNull();
  expect(brokerOriginalSession(client).snapshot().accountId).toBe("");
  expect(screen.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  expect(saveSourceIntake).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});
