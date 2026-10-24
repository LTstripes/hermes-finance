import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import {
  applyBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
  listBrokerMonths,
  previewBrokerMonth,
  readBrokerMonth,
} from "../api/brokerMonths";
import { ApiClientError } from "../api/client";
import { getMonth } from "../api/months";
import { previewOriginalContext } from "../api/mybrokerPreflight";
import {
  confirmIntakeReview,
  listSourceIntakes,
  previewIntakeReview,
  readSourceIntake,
  type SourceIntake,
} from "../api/sourceIntake";
import { brokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import { UiV2MonthSources } from "./UiV2MonthSources";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/months", () => ({ getMonth: vi.fn() }));
vi.mock("../api/mybrokerPreflight", () => ({ previewOriginalContext: vi.fn() }));
vi.mock("../api/brokerMonths", () => ({
  listBrokerMonths: vi.fn(),
  previewBrokerMonth: vi.fn(),
  applyBrokerMonth: vi.fn(),
  readBrokerMonth: vi.fn(),
}));
vi.mock("../api/sourceIntake", () => ({
  listSourceIntakes: vi.fn(),
  readSourceIntake: vi.fn(),
  previewIntakeReview: vi.fn(),
  confirmIntakeReview: vi.fn(),
}));
// The independent result reader is covered by MonthInstruments and desktop tests.
// This probe exposes its exact account prop alongside the real mutable reviewer.
vi.mock("./UiV2MonthInstruments", () => ({
  UiV2MonthInstruments: ({ account }: { account: string }) => (
    <output aria-label="Доходность счёта">{account}</output>
  ),
}));

const month = {
  id: 1,
  year: 2030,
  month: 1,
  status: "draft" as const,
  snapshot_date: "2030-01-31",
  source: "manual" as const,
};
function intake(id: number, account: string): SourceIntake {
  return {
    contract_version: "source_intake_v1",
    id,
    document_sha256: account.repeat(64),
    generation: 1,
    head_seq: 2,
    manifest_digest: "c".repeat(64),
    original_required: true,
    covered_from: "2030-01-01",
    covered_to: "2030-01-31",
    state: {
      account_id: id + 6,
      reporting_month_id: 1,
      default_enabled: true,
      account_currency: null,
      policy_revision: 1,
      overrides: {},
      instrument_decisions: [],
      deferred_isins: [],
    },
    document: {
      provider: "mybroker",
      parser: "mybroker-s1-v2",
      document_sha256: account.repeat(64),
      filename_account: account,
      source_accounts: [account],
      covered_from: "2030-01-01",
      covered_to: "2030-01-31",
      positions: [],
      trades: [],
      money: [],
      rub_money: [],
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
const a = intake(1, "A");
const b = intake(2, "B");
const preview: BrokerMonthPreview = {
  contract_version: "broker_month_v1",
  reporting_month_id: 1,
  account_id: 7,
  confirmation_digest: "d".repeat(64),
  document: { ...a.document, source_accounts: ["A"] },
  account_bindings: [],
  account_aliases: [],
  conflicts: [],
  exceptions: [],
  can_apply: true,
  bookkeeping_ready: false,
  cash_control_difference_kopecks: null,
  opening_date: "2029-12-31",
  ending_date: "2030-01-31",
};
function receipt(id: string): BrokerMonthReadback {
  return {
    contract_version: "broker_month_v1",
    reporting_month_id: 1,
    account_id: 7,
    request_id: id,
    confirmation_digest: preview.confirmation_digest,
    import_id: 1,
    status: "draft",
    exceptions: [],
    bookkeeping_ready: false,
    accepted: {
      document: { ...a.document, source_accounts: ["A"] },
      position_ids: [],
      cash_id: 1,
      trade_ids: [],
      source_digest: "e".repeat(64),
      projection_digest: "f".repeat(64),
    },
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listSourceIntakes).mockResolvedValue([structuredClone(a), structuredClone(b)]);
  vi.mocked(listAccounts).mockResolvedValue([
    { id: 7, name: "Broker A", status: "active", account_type: "brokerage" },
  ] as Awaited<ReturnType<typeof listAccounts>>);
  vi.mocked(getMonth).mockResolvedValue(month);
  vi.mocked(previewOriginalContext).mockResolvedValue({
    coveredFrom: "2030-01-01",
    coveredTo: "2030-01-31",
    accountId: 7,
  });
  vi.mocked(listBrokerMonths).mockResolvedValue([]);
  vi.mocked(previewBrokerMonth).mockResolvedValue(preview);
  vi.mocked(previewIntakeReview).mockResolvedValue({
    confirmation_digest: "g".repeat(64),
    financial_effects: 0,
  });
});
function Navigation() {
  const navigate = useNavigate();
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
      <button type="button" onClick={() => navigate("?source_account=INVALID")}>
        Invalid
      </button>
      <button type="button" onClick={() => navigate("?source_account=A&source_account=B")}>
        Duplicate
      </button>
    </>
  );
}
function mount(closed = false, existingClient?: QueryClient, path = "/v2/close?source_account=A") {
  const client =
    existingClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const session = brokerOriginalSession(client);
  session.context(1, false);
  const content = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Navigation />
        <UiV2MonthSources month={{ ...month, status: closed ? "closed" : "draft" }} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { ...render(content), session, client };
}
const picker = () => screen.getByLabelText("Счёт источника месяца");
const journal = () => screen.getByRole("region", { name: "Долговечный разбор источника" });
async function openA() {
  fireEvent.click(await screen.findByRole("button", { name: "Разобрать и исправить #1" }));
  await waitFor(() =>
    expect(within(journal()).getByLabelText("Сохранённый разбор")).toHaveValue("1"),
  );
}
async function originalA() {
  fireEvent.change(screen.getByLabelText("Оригинальный XML MyBroker"), {
    target: { files: [new File(["<synthetic/>"], "A.xml", { type: "application/xml" })] },
  });
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
}
it("A→B→A and Back retire original, Preview, overrides and public consent before showing B reads", async () => {
  const { session } = mount();
  await openA();
  await originalA();
  fireEvent.change(within(journal()).getByLabelText("Валюта предложения счёта"), {
    target: { value: "USD" },
  });
  act(() => session.consent(true));
  fireEvent.change(picker(), { target: { value: "B" } });
  await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
  expect(session.snapshot().file).toBeNull();
  expect(session.snapshot().lookupConsent).toBe(false);
  expect(session.snapshot().decisions).toEqual([]);
  expect(screen.queryByRole("button", { name: /Подтвердить сводку/ })).toBeNull();
  expect(within(journal()).getByLabelText("Сохранённый разбор")).toHaveValue("2");
  expect(within(journal()).queryByRole("option", { name: /#1/ })).toBeNull();
  fireEvent.click(screen.getByText("Back", { exact: true }));
  await waitFor(() => expect(picker()).toHaveValue("A"));
  expect(within(journal()).getByLabelText("Валюта предложения счёта")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Проверить изменения разбора" })).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it.each(["All", "Invalid", "Duplicate"])(
  "retires A context for %s without borrowing a result",
  async (target) => {
    const { session } = mount();
    await openA();
    await originalA();
    if (target === "All") fireEvent.change(picker(), { target: { value: "" } });
    else fireEvent.click(screen.getByText(target, { exact: true }));
    await waitFor(() => expect(session.snapshot().file).toBeNull());
    expect(screen.queryByLabelText("Доходность счёта")).toBeNull();
    expect(screen.queryByRole("button", { name: /Подтвердить сводку/ })).toBeNull();
    if (target !== "All") expect(screen.queryByLabelText("Оригинальный XML MyBroker")).toBeNull();
  },
);
it("late Preview from A cannot revive after B→A", async () => {
  const late = deferred<BrokerMonthPreview>();
  vi.mocked(previewBrokerMonth).mockReturnValue(late.promise);
  mount();
  await openA();
  fireEvent.change(screen.getByLabelText("Оригинальный XML MyBroker"), {
    target: { files: [new File(["x"], "A.xml")] },
  });
  await waitFor(() => expect(previewBrokerMonth).toHaveBeenCalledTimes(1));
  fireEvent.change(picker(), { target: { value: "B" } });
  fireEvent.change(picker(), { target: { value: "A" } });
  await act(async () => late.resolve(preview));
  expect(screen.queryByRole("button", { name: /Подтвердить сводку/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Проверить MyBroker" })).toBeDisabled();
});
it.each([false, true])(
  "pending Apply / lost ACK (%s) retains same intent and GET recovers before B is exposed",
  async (lostAck) => {
    const post = deferred<BrokerMonthReadback>();
    let id = "";
    vi.mocked(applyBrokerMonth).mockImplementation(async (_f, _i, _d, key) => {
      id = key;
      if (lostAck) throw new Error("lost ACK");
      return post.promise;
    });
    vi.mocked(readBrokerMonth)
      .mockRejectedValueOnce(new Error("lost GET"))
      .mockImplementation(async () => receipt(id));
    const { session } = mount();
    await openA();
    await originalA();
    fireEvent.click(screen.getByRole("button", { name: /Подтвердить сводку/ }));
    await waitFor(() => expect(applyBrokerMonth).toHaveBeenCalledTimes(1));
    const intent = session.snapshot().pending;
    fireEvent.change(picker(), { target: { value: "B" } });
    expect(screen.getByText(/Переключение счёта отложено/)).toHaveTextContent("A");
    expect(screen.queryByLabelText("Доходность счёта")).toBeNull();
    expect(session.snapshot().pending?.id).toBe(intent?.id);
    expect(within(journal()).getByLabelText("Валюта предложения счёта")).toBeDisabled();
    if (!lostAck) await act(async () => post.resolve(receipt(id)));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Повторить чтение" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Повторить чтение" }));
    await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
    expect(session.snapshot().pending).toBeNull();
    expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
    expect(vi.mocked(readBrokerMonth).mock.calls.every(([key]) => key === id)).toBe(true);
  },
);
it.each([false, true])(
  "journal pending/readback or unknown ACK (%s) blocks switch and uses history GET only",
  async (lostAck) => {
    const post = deferred<Awaited<ReturnType<typeof confirmIntakeReview>>>();
    let id = "";
    vi.mocked(confirmIntakeReview).mockImplementation(async (_i, _f, _intent, _digest, key) => {
      id = key;
      if (lostAck) throw new Error("lost ACK");
      return post.promise;
    });
    vi.mocked(readSourceIntake)
      .mockRejectedValueOnce(new Error("lost GET"))
      .mockImplementation(async () => ({
        ...a,
        history: [{ seq: 2, request_id: id, operation: "decisions", reviewer: "owner_local" }],
      }));
    mount();
    await openA();
    await originalA();
    fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
    fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
    await waitFor(() => expect(confirmIntakeReview).toHaveBeenCalledTimes(1));
    fireEvent.change(picker(), { target: { value: "B" } });
    expect(screen.getByText(/Переключение счёта отложено/)).toHaveTextContent("A");
    if (!lostAck)
      await act(async () =>
        post.resolve({ intake_id: 1, request_id: id, head_seq: 2, duplicate: false }),
      );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Повторить чтение журнала" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Повторить чтение журнала" }));
    // In the lost-ACK case the first GET itself is also lost; intent remains.
    if (lostAck) {
      await screen.findByText(/lost GET/);
      fireEvent.click(screen.getByRole("button", { name: "Повторить чтение журнала" }));
    }
    await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
    expect(confirmIntakeReview).toHaveBeenCalledTimes(1);
    expect(readSourceIntake).toHaveBeenCalledWith(1);
  },
);
it("CLOSED remains read-only across account switch", async () => {
  mount(true);
  await screen.findByRole("button", { name: "Просмотреть разбор #1" });
  fireEvent.change(picker(), { target: { value: "B" } });
  await waitFor(() =>
    expect(within(journal()).getByLabelText("Сохранённый разбор")).toHaveValue("2"),
  );
  expect(within(journal()).getByLabelText("Валюта предложения счёта")).toBeDisabled();
  expect(screen.queryByLabelText("Оригинальный XML MyBroker")).toBeNull();
  expect(screen.queryByRole("button", { name: "Сохранить разбор" })).toBeNull();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("an unmounted journal retains unknown ACK, exact key and source scope for SPA Back recovery", async () => {
  let id = "";
  vi.mocked(confirmIntakeReview).mockImplementation(async (_i, _f, _intent, _digest, key) => {
    id = key;
    throw new Error("lost ACK");
  });
  vi.mocked(readSourceIntake).mockImplementation(async () => ({
    ...a,
    history: [{ seq: 2, request_id: id, operation: "decisions", reviewer: "owner_local" }],
  }));
  const first = mount();
  await openA();
  await originalA();
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
  await screen.findByText(/Ответ сохранения не подтверждён.*intent сохранён/);
  first.unmount();
  mount(false, first.client, "/v2/close?source_account=B");
  expect(screen.getByText(/Переключение счёта отложено/)).toHaveTextContent("A");
  expect(screen.queryByLabelText("Доходность счёта")).toBeNull();
  expect(screen.queryByLabelText("Оригинальный XML MyBroker")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Повторить чтение журнала" }));
  await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
  expect(readSourceIntake).toHaveBeenCalledWith(1);
  expect(confirmIntakeReview).toHaveBeenCalledTimes(1);
});

it("a definite pre-ACK 409 refusal does not invent a pending commit or trap the scope", async () => {
  vi.mocked(confirmIntakeReview).mockRejectedValue(
    new ApiClientError(409, { code: "stale", message: "synthetic stale intent", details: [] }),
  );
  mount();
  await openA();
  await originalA();
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
  await screen.findByText("synthetic stale intent");
  fireEvent.change(picker(), { target: { value: "B" } });
  await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
  expect(screen.queryByRole("button", { name: "Повторить чтение журнала" })).toBeNull();
  expect(readSourceIntake).not.toHaveBeenCalled();
});

it("late non-economic Preview cannot restore A overrides or confirmation after A→B→A", async () => {
  const late = deferred<Awaited<ReturnType<typeof previewIntakeReview>>>();
  vi.mocked(previewIntakeReview).mockReturnValue(late.promise);
  mount();
  await openA();
  await originalA();
  fireEvent.change(within(journal()).getByLabelText("Валюта предложения счёта"), {
    target: { value: "USD" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  await waitFor(() => expect(previewIntakeReview).toHaveBeenCalledTimes(1));
  fireEvent.change(picker(), { target: { value: "B" } });
  fireEvent.change(picker(), { target: { value: "A" } });
  await act(async () => late.resolve({ confirmation_digest: "x", financial_effects: 0 }));
  expect(within(journal()).getByLabelText("Валюта предложения счёта")).toHaveValue("");
  expect(screen.queryByRole("button", { name: "Подтвердить сохранение разбора" })).toBeNull();
  expect(confirmIntakeReview).not.toHaveBeenCalled();
});

it("a definite journal refusal after unmount settles only its immutable key", async () => {
  const post = deferred<Awaited<ReturnType<typeof confirmIntakeReview>>>();
  vi.mocked(confirmIntakeReview).mockReturnValue(post.promise);
  const first = mount();
  await openA();
  await originalA();
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
  await waitFor(() => expect(confirmIntakeReview).toHaveBeenCalledTimes(1));
  first.unmount();
  mount(false, first.client, "/v2/close?source_account=B");
  expect(screen.getByText(/Переключение счёта отложено/)).toBeVisible();
  await act(async () =>
    post.reject(
      new ApiClientError(409, { code: "stale", message: "known refusal after leave", details: [] }),
    ),
  );
  await waitFor(() => expect(screen.getByLabelText("Доходность счёта")).toHaveTextContent("B"));
  expect(screen.queryByRole("button", { name: "Повторить чтение журнала" })).toBeNull();
  expect(readSourceIntake).not.toHaveBeenCalled();
});

it("a late old GET/refetch continuation cannot clear a newer journal command after remount", async () => {
  const refresh = deferred<void>();
  const secondPost = deferred<Awaited<ReturnType<typeof confirmIntakeReview>>>();
  let firstKey = "";
  vi.mocked(confirmIntakeReview)
    .mockImplementationOnce(async (_i, _f, _intent, _digest, key) => {
      firstKey = key;
      return { intake_id: 1, request_id: key, head_seq: 2, duplicate: false };
    })
    .mockReturnValue(secondPost.promise);
  vi.mocked(readSourceIntake).mockImplementation(async () => ({
    ...a,
    history: [{ seq: 2, request_id: firstKey, operation: "decisions", reviewer: "owner_local" }],
  }));
  const first = mount();
  await openA();
  await originalA();
  const invalidate = vi.spyOn(first.client, "invalidateQueries");
  invalidate.mockImplementationOnce(() => refresh.promise).mockResolvedValue(undefined);
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1));
  first.unmount();
  mount(false, first.client);
  fireEvent.click(screen.getByRole("button", { name: "Повторить чтение журнала" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Повторить чтение журнала" })).toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Проверить изменения разбора" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение разбора" }));
  await waitFor(() => expect(confirmIntakeReview).toHaveBeenCalledTimes(2));
  const secondKey = vi.mocked(confirmIntakeReview).mock.calls[1][4];
  expect(secondKey).not.toBe(firstKey);
  await act(async () => refresh.resolve());
  fireEvent.change(picker(), { target: { value: "B" } });
  expect(screen.getByText(/Переключение счёта отложено/)).toHaveTextContent("A");
  expect(screen.queryByLabelText("Доходность счёта")).toBeNull();
  expect(confirmIntakeReview).toHaveBeenCalledTimes(2);
});
