import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../../api/accounts";
import {
  applyBrokerMonth,
  listBrokerMonths,
  previewBrokerMonth,
  readBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
} from "../../api/brokerMonths";
import { getMonth } from "../../api/months";
import { previewOriginalContext } from "../../api/mybrokerPreflight";
import { BrokerMonthReview } from "./BrokerMonthReview";

vi.mock("../../api/months", () => ({ getMonth: vi.fn() }));
vi.mock("../../api/mybrokerPreflight", () => ({ previewOriginalContext: vi.fn() }));
vi.mock("../../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../../api/brokerMonths", () => ({
  applyBrokerMonth: vi.fn(),
  listBrokerMonths: vi.fn(),
  previewBrokerMonth: vi.fn(),
  readBrokerMonth: vi.fn(),
}));

const document: BrokerMonthPreview["document"] = {
  provider: "mybroker",
  parser: "mybroker-s1-v2",
  document_sha256: "a".repeat(64),
  filename_account: "synthetic",
  covered_from: "2030-01-01",
  covered_to: "2030-01-31",
  source_accounts: ["synthetic"],
  section_inventory: { money: 1 },
  trades: [],
  positions: [
    {
      ordinal: 1,
      source_account: "synthetic",
      isin: "RU000A000000",
      actual_quantity: "10",
      forward_quantity: "10",
      beginning_actual_quantity: "10",
      beginning_value: null,
      ending_value: "1000.01",
    },
  ],
  rub_money: [
    {
      ordinal: 1,
      source_account: "synthetic",
      currency: "RUB",
      beginning_amount: "400",
      ending_amount: "400",
    },
  ],
  money: [
    {
      ordinal: 1,
      source_account: "synthetic",
      date: "2030-01-15",
      kind: "unsupported",
      amount: "123.45",
      currency: "RUB",
    },
  ],
};
const preview: BrokerMonthPreview = {
  contract_version: "broker_month_v1",
  reporting_month_id: 1,
  account_id: 7,
  confirmation_digest: "b".repeat(64),
  account_bindings: [],
  account_aliases: [
    {
      identity: "synthetic",
      hermes_id: 7,
      mapping_id: 1,
      action: "reuse",
      origins: ["filename_account", "acc_code"],
      target_name: "Synthetic broker",
    },
  ],
  document,
  conflicts: [],
  exceptions: ["money_semantics_unsupported"],
  can_apply: true,
  bookkeeping_ready: false,
  cash_control_difference_kopecks: null,
  opening_date: "2029-12-31",
  ending_date: "2030-01-31",
};
function persisted(requestId: string, accountId = 7): BrokerMonthReadback {
  return {
    contract_version: "broker_month_v1",
    reporting_month_id: 1,
    account_id: accountId,
    request_id: requestId,
    confirmation_digest: preview.confirmation_digest,
    import_id: 10,
    status: "draft",
    exceptions: preview.exceptions,
    bookkeeping_ready: false,
    accepted: {
      document,
      position_ids: [12],
      cash_id: 13,
      trade_ids: [],
      source_digest: "c".repeat(64),
      projection_digest: "d".repeat(64),
    },
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getMonth).mockResolvedValue({
    id: 1,
    year: 2030,
    month: 1,
    snapshot_date: "2030-01-31",
    status: "draft",
    source: "manual",
  });
  vi.mocked(previewOriginalContext).mockResolvedValue({
    coveredFrom: "2030-01-01",
    coveredTo: "2030-01-31",
    accountId: null,
  });
  vi.mocked(listAccounts).mockResolvedValue([
    { id: 7, name: "Synthetic broker", status: "active", account_type: "brokerage" },
  ] as Awaited<ReturnType<typeof listAccounts>>);
  vi.mocked(listBrokerMonths).mockResolvedValue([]);
  vi.mocked(previewBrokerMonth).mockResolvedValue(preview);
  vi.mocked(applyBrokerMonth).mockImplementation(async (_file, _intent, _digest, requestId) =>
    persisted(requestId),
  );
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => persisted(id));
});
function show(closed = false) {
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={query}>
      <BrokerMonthReview monthId={1} closed={closed} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}
async function inspect(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("option", { name: "Synthetic broker" });
  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
  await screen.findByRole("button", { name: "Сформировать неполный черновик" });
}
it("requires explicit whole-account review and confirms partial DRAFT only after GET", async () => {
  const user = show();
  await inspect(user);
  const apply = screen.getByRole("button", { name: "Сформировать неполный черновик" });
  expect(apply).toBeDisabled();
  expect(screen.getByRole("table", { name: "Привязки исходных счетов" })).toHaveTextContent(
    "Существующая",
  );
  expect(screen.getByText(/Общая оценка источника/)).toHaveTextContent("— → 1");
  await user.click(screen.getByText("Все денежные строки и секции источника"));
  expect(screen.getByText("Не разобрано — требуется доказательство")).toBeVisible();
  await user.click(screen.getByRole("checkbox"));
  await user.click(apply);
  await screen.findByText(/Сохранённый результат подтверждён независимым чтением/);
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  expect(readBrokerMonth).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Черновик неполный; Close заблокирован/)).toBeVisible();
});

it("discloses every new alias and sends the exact batch decision only after explicit confirmation", async () => {
  const decisions = ["FILE-ALIAS", "ROW-A", "ROW-B"].map((identity) => ({
    identity,
    hermes_id: 7,
  }));
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    account_bindings: decisions,
    account_aliases: decisions.map((d, i) => ({
      ...d,
      mapping_id: null,
      action: "stage_create",
      origins: [i === 0 ? "filename_account" : "acc_code"],
      target_name: "Synthetic broker",
    })),
  });
  const user = show();
  await inspect(user);
  const table = screen.getByRole("table", { name: "Привязки исходных счетов" });
  for (const alias of [
    "FILE-ALIAS",
    "ROW-A",
    "ROW-B",
    "filename_account",
    "acc_code",
    "Synthetic broker (#7)",
  ])
    expect(table).toHaveTextContent(alias);
  await user.click(
    screen.getByRole("checkbox", { name: "Я проверил весь счёт и видимую неполноту черновика." }),
  );
  const apply = screen.getByRole("button", { name: "Сформировать неполный черновик" });
  expect(apply).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  await user.click(screen.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }));
  await user.click(apply);
  await screen.findByText(/Сохранённый результат подтверждён независимым чтением/);
  expect(vi.mocked(applyBrokerMonth).mock.calls[0][4]).toEqual(decisions);
});

it("reinspection invalidates alias confirmation and stale Apply cannot claim success", async () => {
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    account_bindings: [{ identity: "synthetic", hermes_id: 7 }],
    account_aliases: [{ ...preview.account_aliases[0], action: "stage_create", mapping_id: null }],
  });
  vi.mocked(applyBrokerMonth).mockRejectedValue(new Error("broker_month_preview_stale"));
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }));
  await user.click(screen.getByRole("checkbox", { name: /Я проверил весь счёт/ }));
  await user.click(screen.getByRole("button", { name: "Сформировать неполный черновик" }));
  await screen.findByText("broker_month_preview_stale");
  expect(readBrokerMonth).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
  await screen.findByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ });
  expect(
    screen.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }),
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Сформировать неполный черновик" })).toBeDisabled();
});
it("does not claim success after failed GET and reuses request identity on retry", async () => {
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("Synthetic read failed"));
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Сформировать неполный черновик" }));
  await screen.findByText("Synthetic read failed");
  expect(screen.queryByText(/Сохранённый результат подтверждён/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Сформировать неполный черновик" }));
  await screen.findByText(/Сохранённый результат подтверждён/);
  const calls = vi.mocked(applyBrokerMonth).mock.calls;
  expect(calls[0][3]).toBe(calls[1][3]);
});
it("rejects independent readback from another account", async () => {
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => persisted(id, 8));
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Сформировать неполный черновик" }));
  await screen.findByText(/Независимое чтение не подтвердило/);
  expect(screen.queryByText(/Сохранённый результат подтверждён/)).not.toBeInTheDocument();
});
it("new original file invalidates the previous review", async () => {
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox"));
  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<changed/>"], "changed.xml", { type: "application/xml" }),
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Сформировать неполный черновик" }),
  ).not.toBeInTheDocument();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it("CLOSED renders every persisted covered account and offers no writer", async () => {
  vi.mocked(listBrokerMonths).mockResolvedValue([persisted("a"), persisted("b", 8)]);
  show(true);
  await screen.findByText(/Счёт #7/);
  expect(screen.getByText(/Счёт #8/)).toBeVisible();
  expect(screen.queryByLabelText("Оригинальный XML MyBroker")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Проверить MyBroker" })).not.toBeInTheDocument();
});

it("a refreshed source GET overrides earlier ready Apply readback", async () => {
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    bookkeeping_ready: true,
    exceptions: [],
  });
  vi.mocked(applyBrokerMonth).mockImplementation(async (_file, _intent, _digest, requestId) => ({
    ...persisted(requestId),
    bookkeeping_ready: true,
    exceptions: [],
  }));
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => ({
    ...persisted(id),
    bookkeeping_ready: true,
    exceptions: [],
  }));
  vi.mocked(listBrokerMonths).mockImplementation(async () => {
    const id = vi.mocked(applyBrokerMonth).mock.calls.at(-1)?.[3];
    return id
      ? [{ ...persisted(id), bookkeeping_ready: false, exceptions: ["source_projection_changed"] }]
      : [];
  });
  const user = show();
  await screen.findByRole("option", { name: "Synthetic broker" });
  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
  await screen.findByRole("button", { name: "Сформировать черновик" });
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Сформировать черновик" }));
  await screen.findByText(/Черновик неполный; Close заблокирован/);
  expect(screen.queryByText(/Брокерский компонент готов к общей проверке/)).not.toBeInTheDocument();
});

it.each([true, false])(
  "account readiness retains every receipt blocker when newer receipt blocked=%s",
  async (newerBlocked) => {
    const first = (id: string) => ({
      ...persisted(id),
      bookkeeping_ready: newerBlocked,
      exceptions: newerBlocked ? [] : ["source_projection_changed"],
    });
    vi.mocked(previewBrokerMonth).mockResolvedValue({
      ...preview,
      bookkeeping_ready: true,
      exceptions: [],
    });
    vi.mocked(applyBrokerMonth).mockImplementation(async (_file, _intent, _digest, id) =>
      first(id),
    );
    vi.mocked(readBrokerMonth).mockImplementation(async (id) => first(id));
    vi.mocked(listBrokerMonths).mockImplementation(async () => {
      const id = vi.mocked(applyBrokerMonth).mock.calls.at(-1)?.[3];
      return id
        ? [
            first(id),
            {
              ...persisted("newer-request"),
              bookkeeping_ready: !newerBlocked,
              exceptions: newerBlocked ? ["source_projection_changed"] : [],
            },
          ]
        : [];
    });
    const user = show();
    await screen.findByRole("option", { name: "Synthetic broker" });
    await user.upload(
      screen.getByLabelText("Оригинальный XML MyBroker"),
      new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
    );
    await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
    await screen.findByRole("button", { name: "Сформировать черновик" });
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Сформировать черновик" }));
    await screen.findByText(/Сохранённый источник месяца/);
    expect(screen.getByText(/Черновик неполный; Close заблокирован/)).toBeVisible();
    expect(
      screen.queryByText(/Брокерский компонент готов к общей проверке/),
    ).not.toBeInTheDocument();
  },
);

function mounted() {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const node = (id: number, closed = false) => (
    <QueryClientProvider client={query}>
      <BrokerMonthReview monthId={id} closed={closed} />
    </QueryClientProvider>
  );
  const view = render(node(1));
  return {
    ...view,
    query,
    user: userEvent.setup(),
    change: (id: number, closed = false) => view.rerender(node(id, closed)),
  };
}
const original = (name = "synthetic.xml") =>
  new File([`<${name}/>`], name, { type: "application/xml" });
function known() {
  vi.mocked(previewOriginalContext).mockResolvedValue({
    coveredFrom: "2030-01-01",
    coveredTo: "2030-01-31",
    accountId: 7,
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function upload(user: ReturnType<typeof userEvent.setup>, file = original()) {
  await screen.findByRole("option", { name: "Synthetic broker" });
  await user.upload(screen.getByLabelText("Оригинальный XML MyBroker"), file);
}
it("known original automatically uses ordinary Preview; can_apply is authoritative and Save remains explicit", async () => {
  known();
  const { user } = mounted();
  const file = original();
  await upload(user, file);
  const save = await screen.findByRole("button", { name: "Сформировать неполный черновик" });
  expect(screen.getByLabelText("Брокерский счёт")).toHaveValue("7");
  expect(previewBrokerMonth).toHaveBeenCalledWith(
    file,
    { reporting_month_id: 1, account_id: 7 },
    expect.any(AbortSignal),
  );
  expect(save).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(readBrokerMonth).not.toHaveBeenCalled();
  await user.click(screen.getByRole("checkbox"));
  expect(save).toBeEnabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it("ordinary can_apply=false cannot be bypassed by known account or review", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    can_apply: false,
    conflicts: ["instrument_currency_unproven"],
  });
  const { user } = mounted();
  await upload(user);
  expect(await screen.findByRole("checkbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Сформировать неполный черновик" })).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it.each(["wrong", "partial", "wide", "snapshot", "closed", "inactive", "empty"])(
  "does not auto-select for %s context",
  async (kind) => {
    known();
    if (["wrong", "partial", "wide"].includes(kind))
      vi.mocked(previewOriginalContext).mockResolvedValue({
        coveredFrom:
          kind === "wide" ? "2029-01-01" : kind === "partial" ? "2030-01-02" : "2030-02-01",
        coveredTo: "2030-01-31",
        accountId: 7,
      });
    if (kind === "snapshot" || kind === "closed")
      vi.mocked(getMonth).mockResolvedValue({
        id: 1,
        year: 2030,
        month: 1,
        snapshot_date: kind === "snapshot" ? "2030-01-30" : "2030-01-31",
        status: kind === "closed" ? "closed" : "draft",
        source: "manual",
      });
    const { user } = mounted();
    await screen.findByRole("option", { name: "Synthetic broker" });
    if (kind === "empty") vi.mocked(listAccounts).mockResolvedValue([]);
    if (kind === "inactive")
      vi.mocked(listAccounts).mockResolvedValue([
        { id: 7, name: "Synthetic broker", status: "closed", account_type: "brokerage" },
      ] as Awaited<ReturnType<typeof listAccounts>>);
    await upload(user);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Проверить MyBroker" })).toBeEnabled(),
    );
    expect(previewBrokerMonth).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Брокерский счёт")).toHaveValue("");
    expect(applyBrokerMonth).not.toHaveBeenCalled();
  },
);
it("discovery error leaves manual selection and retry available", async () => {
  vi.mocked(previewOriginalContext).mockRejectedValue(new Error("Malformed discovery"));
  const { user } = mounted();
  await upload(user);
  await screen.findByText("Malformed discovery");
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
  await screen.findByRole("checkbox");
  expect(previewBrokerMonth).toHaveBeenCalledTimes(1);
});
it.each(["success", "error"])("file A→B→A rejects late discovery %s", async (outcome) => {
  known();
  const late = deferred<Awaited<ReturnType<typeof previewOriginalContext>>>();
  vi.mocked(previewOriginalContext).mockReturnValueOnce(late.promise);
  const { user } = mounted();
  const a = original();
  await upload(user, a);
  await upload(user, original("b.xml"));
  await screen.findByRole("checkbox");
  await upload(user, a);
  await screen.findByRole("checkbox");
  await user.click(screen.getByRole("checkbox"));
  await act(async () => {
    if (outcome === "success")
      late.resolve({ coveredFrom: "2030-01-01", coveredTo: "2030-01-31", accountId: 8 });
    else late.reject(new Error("late-error"));
  });
  expect(screen.getByLabelText("Брокерский счёт")).toHaveValue("7");
  expect(screen.queryByText("late-error")).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(previewBrokerMonth).toHaveBeenCalledTimes(2);
});
it.each(["file", "account", "month", "closed", "unmount", "mappings"])(
  "late ordinary Preview cannot revive review after %s change",
  async (kind) => {
    known();
    const late = deferred<BrokerMonthPreview>();
    vi.mocked(previewBrokerMonth).mockReturnValueOnce(late.promise);
    const { user, change, unmount, query } = mounted();
    await upload(user);
    await waitFor(() => expect(previewBrokerMonth).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(previewBrokerMonth).mock.calls[0][2];
    if (kind === "file") {
      await upload(user, original("b.xml"));
      await screen.findByRole("checkbox");
    }
    if (kind === "account") await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "");
    if (kind === "month") {
      change(2);
      change(1);
    }
    if (kind === "closed") change(1, true);
    if (kind === "unmount") unmount();
    if (kind === "mappings")
      await act(async () => {
        query.setQueryData(["broker-identity-mappings"], ["changed"]);
      });
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      late.resolve({ ...preview, confirmation_digest: "late" });
    });
    if (kind !== "file") expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(applyBrokerMonth).not.toHaveBeenCalled();
  },
);
it("mapping invalidation immediately drops both whole-account and alias consent", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    account_bindings: [{ identity: "NEW", hermes_id: 7 }],
  });
  const { user, query } = mounted();
  await upload(user);
  await screen.findByRole("checkbox", { name: /Я проверил/ });
  for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
  await act(async () => {
    query.setQueryData(["broker-identity-mappings"], ["A"]);
    query.setQueryData(["broker-identity-mappings"], ["B"]);
    query.setQueryData(["broker-identity-mappings"], ["A"]);
  });
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

it("upload before initial account list completes still reaches automatic ordinary Preview", async () => {
  known();
  const initial = deferred<Awaited<ReturnType<typeof listAccounts>>>();
  const available = [
    { id: 7, name: "Synthetic broker", status: "active", account_type: "brokerage" },
  ] as Awaited<ReturnType<typeof listAccounts>>;
  vi.mocked(listAccounts).mockReturnValueOnce(initial.promise).mockResolvedValue(available);
  const plan = deferred<Awaited<ReturnType<typeof previewOriginalContext>>>();
  vi.mocked(previewOriginalContext).mockReturnValueOnce(plan.promise);
  const { user } = mounted();
  await user.upload(screen.getByLabelText("Оригинальный XML MyBroker"), original());
  await act(async () => {
    initial.resolve(available);
  });
  await act(async () => {
    plan.resolve({ coveredFrom: "2030-01-01", coveredTo: "2030-01-31", accountId: 7 });
  });
  await screen.findByRole("checkbox");
  expect(previewBrokerMonth).toHaveBeenCalledTimes(1);
});

it("late ordinary Preview error after selecting another original cannot replace current ready state", async () => {
  known();
  const late = deferred<BrokerMonthPreview>();
  vi.mocked(previewBrokerMonth).mockReturnValueOnce(late.promise);
  const { user } = mounted();
  await upload(user);
  await waitFor(() => expect(previewBrokerMonth).toHaveBeenCalledTimes(1));
  await upload(user, original("b.xml"));
  await screen.findByRole("checkbox");
  await user.click(screen.getByRole("checkbox"));
  await act(async () => {
    late.reject(new Error("old-original-error"));
  });
  expect(screen.queryByText("old-original-error")).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
