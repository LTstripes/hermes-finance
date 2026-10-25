import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  listAllSourceIntakes,
  readSourceIntake,
  saveSourceIntake,
  type SourceIntake,
} from "../../api/sourceIntake";
import { SourceIntakeUpload } from "./SourceIntakeUpload";

vi.mock("../../api/sourceIntake", () => ({
  listAllSourceIntakes: vi.fn(),
  readSourceIntake: vi.fn(),
  saveSourceIntake: vi.fn(),
}));

beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.unstubAllGlobals());
function sourceFixture(): SourceIntake {
  return {
    contract_version: "source_intake_v1",
    id: 4,
    document_sha256: "a".repeat(64),
    generation: 1,
    head_seq: 3,
    manifest_digest: "b".repeat(64),
    original_required: true,
    covered_from: "2040-10-01",
    covered_to: "2040-10-31",
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
      covered_from: "2040-10-01",
      covered_to: "2040-10-31",
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
}

it("holds uncertain upload and navigation until exact request-key GET proves source-only Save; never replays POST", async () => {
  const user = userEvent.setup();
  let key = "";
  const file = new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" });
  const pending = vi.fn();
  const saved = vi.fn();
  const source = sourceFixture();
  vi.mocked(saveSourceIntake).mockImplementation(async (_file, id) => {
    key = id;
    source.history = [{ seq: 3, operation: "manifest", request_id: id, reviewer: "owner_local" }];
    throw new TypeError("synthetic lost ACK");
  });
  vi.mocked(listAllSourceIntakes)
    .mockResolvedValueOnce([])
    .mockImplementation(async () => [source]);
  vi.mocked(readSourceIntake).mockImplementation(async () => source);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SourceIntakeUpload compact onPendingChange={pending} onSaved={saved} />
    </QueryClientProvider>,
  );
  const input = screen.getByLabelText("XML-файлы");
  await user.upload(input, file);
  const recover = await screen.findByRole("button", { name: "Проверить сохранение" });
  await waitFor(() => expect(pending).toHaveBeenLastCalledWith(true));
  expect(input).toBeEnabled();
  await user.upload(input, file);
  expect(await screen.findByRole("alert")).toHaveTextContent("Сначала перечитай результат");
  expect(saveSourceIntake).toHaveBeenCalledTimes(1);
  await user.click(recover);
  expect(await screen.findByText(/Результат запроса пока не найден/)).toBeVisible();
  expect(input).toBeEnabled();
  expect(saveSourceIntake).toHaveBeenCalledTimes(1);
  expect(saved).not.toHaveBeenCalled();
  await user.click(recover);
  await waitFor(() => expect(pending).toHaveBeenLastCalledWith(false));
  expect(input).toBeEnabled();
  expect(listAllSourceIntakes).toHaveBeenCalledTimes(2);
  expect(readSourceIntake).toHaveBeenCalledWith(4);
  expect(saveSourceIntake).toHaveBeenCalledTimes(1);
  expect(saved).toHaveBeenCalledWith(
    file,
    expect.objectContaining({
      financial_authority: "none",
      history: [expect.objectContaining({ request_id: key })],
    }),
  );
});

it("uses the same XML input after Reload and preserves exact-original binding rather than rebinding or applying", async () => {
  vi.stubGlobal("crypto", {
    randomUUID: () => "synthetic-upload-key",
    subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xaa).buffer) },
  });
  const user = userEvent.setup();
  const source = sourceFixture();
  source.document_sha256 = "aa".repeat(32);
  source.state.account_id = 7;
  source.state.reporting_month_id = 1;
  const other = {
    ...structuredClone(source),
    id: 8,
    document_sha256: "f".repeat(64),
    state: { ...source.state, account_id: 99, reporting_month_id: 2 },
  };
  vi.mocked(saveSourceIntake).mockImplementation(async (_file, key) => {
    source.history = [{ seq: 3, operation: "decision", request_id: key, reviewer: "owner_local" }];
    return { intake_id: source.id, request_id: key, head_seq: 3, duplicate: true };
  });
  vi.mocked(readSourceIntake).mockResolvedValue(source);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const saved = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SourceIntakeUpload compact knownSources={[other, source]} onSaved={saved} />
    </QueryClientProvider>,
  );
  const file = new File(["<synthetic/>"], "same-original.xml", { type: "application/xml" });
  await user.upload(screen.getByLabelText("XML-файлы"), file);
  await screen.findByText("same-original.xml: Сохранен", { exact: true });
  expect(saveSourceIntake).toHaveBeenCalledTimes(1);
  expect(vi.mocked(saveSourceIntake).mock.calls[0].slice(2)).toEqual([1, 7]);
  expect(readSourceIntake).toHaveBeenCalledWith(source.id);
  expect(saved).toHaveBeenCalledWith(
    file,
    expect.objectContaining({ financial_authority: "none" }),
  );
  expect(listAllSourceIntakes).not.toHaveBeenCalled();
});
