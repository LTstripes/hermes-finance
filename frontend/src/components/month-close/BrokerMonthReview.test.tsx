import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { listAccounts } from "../../api/accounts";
import {
  applyBrokerMonth,
  listBrokerMonths,
  lookupPublicIdentities,
  previewBrokerMonth,
  readBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
} from "../../api/brokerMonths";
import { getMonth } from "../../api/months";
import { previewOriginalContext } from "../../api/mybrokerPreflight";
import { ApiClientError } from "../../api/client";
import { brokerOriginalSession } from "./brokerOriginalSession";
import { BrokerMonthReview } from "./BrokerMonthReview";

vi.mock("../../api/months", () => ({ getMonth: vi.fn() }));
vi.mock("../../api/mybrokerPreflight", () => ({ previewOriginalContext: vi.fn() }));
vi.mock("../../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../../api/brokerMonths", () => ({
  applyBrokerMonth: vi.fn(),
  listBrokerMonths: vi.fn(),
  lookupPublicIdentities: vi.fn(),
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
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => {
    const result = persisted(id);
    vi.mocked(listBrokerMonths).mockResolvedValue([result]);
    return result;
  });
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
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  await user.click(screen.getByText("Полный состав источника и привязки"));
}
it("one explicit summary button saves partial source-DRAFT and confirms only after GET", async () => {
  const user = show();
  await inspect(user);
  const apply = screen.getByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  expect(apply).toBeEnabled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(screen.getByRole("table", { name: "Привязки исходных счетов" })).toHaveTextContent(
    "Существующая",
  );
  expect(
    within(screen.getByRole("region", { name: "Сводка исходного DRAFT" })).getByText(
      "Общая оценка источника, включая cash",
    ).parentElement,
  ).toHaveTextContent("Неизвестно → 1");
  await user.click(screen.getByText("Все денежные строки и секции источника"));
  expect(screen.getByText("Не разобрано — требуется доказательство")).toBeVisible();

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
  const apply = screen.getByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
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
  await user.click(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  );
  await screen.findByText(/Источник или привязки изменились/);
  expect(readBrokerMonth).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
  await screen.findByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ });
  expect(
    screen.getByRole("checkbox", { name: /Я подтверждаю, что все новые aliases/ }),
  ).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeDisabled();
});
it("acknowledged Apply retries only the same GET after a read failure", async () => {
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("Synthetic read failed"));
  const user = show();
  await inspect(user);
  await user.click(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  );
  await screen.findByText("Synthetic read failed");
  expect(screen.queryByText(/Сохранённый результат подтверждён/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Повторить чтение" }));
  await screen.findByText(/Сохранённый результат подтверждён/);
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  expect(vi.mocked(readBrokerMonth).mock.calls[0]).toEqual(
    vi.mocked(readBrokerMonth).mock.calls[1],
  );
});
it("rejects independent readback from another account", async () => {
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => persisted(id, 8));
  const user = show();
  await inspect(user);

  await user.click(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  );
  await screen.findByText(/Независимое чтение не подтвердило/);
  expect(screen.queryByText(/Сохранённый результат подтверждён/)).not.toBeInTheDocument();
});
it("new original file invalidates the previous review", async () => {
  const user = show();
  await inspect(user);

  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<changed/>"], "changed.xml", { type: "application/xml" }),
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
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
  await screen.findByRole("button", { name: "Подтвердить сводку и сохранить source-DRAFT" });

  await user.click(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить source-DRAFT" }),
  );
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
    await screen.findByRole("button", { name: "Подтвердить сводку и сохранить source-DRAFT" });

    await user.click(
      screen.getByRole("button", { name: "Подтвердить сводку и сохранить source-DRAFT" }),
    );
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
  const save = await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  expect(screen.getByLabelText("Брокерский счёт")).toHaveValue("7");
  expect(previewBrokerMonth).toHaveBeenCalledWith(
    file,
    { reporting_month_id: 1, account_id: 7 },
    expect.any(AbortSignal),
  );
  expect(save).toBeEnabled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(readBrokerMonth).not.toHaveBeenCalled();

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
  expect(
    await screen.findByRole("button", {
      name: "Подтвердить сводку и сохранить неполный source-DRAFT",
    }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeDisabled();
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
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
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
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  await upload(user, a);
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });

  await act(async () => {
    if (outcome === "success")
      late.resolve({ coveredFrom: "2030-01-01", coveredTo: "2030-01-31", accountId: 8 });
    else late.reject(new Error("late-error"));
  });
  expect(screen.getByLabelText("Брокерский счёт")).toHaveValue("7");
  expect(screen.queryByText("late-error")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeEnabled();
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
      await screen.findByRole("button", {
        name: "Подтвердить сводку и сохранить неполный source-DRAFT",
      });
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
    if (kind !== "file")
      expect(
        screen.queryByRole("button", {
          name: "Подтвердить сводку и сохранить неполный source-DRAFT",
        }),
      ).not.toBeInTheDocument();
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
  await screen.findByRole("checkbox", { name: /Я подтверждаю/ });
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
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
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
  await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });

  await act(async () => {
    late.reject(new Error("old-original-error"));
  });
  expect(screen.queryByText("old-original-error")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeEnabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

it("exceptions lead a compact exact-source summary while full inventory and known codes stay expandable", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    identity: {
      evidence_gaps: [],
      instruments: [
        {
          isin: "RU000A000000",
          hermes_id: 11,
          instrument_type: "stock",
          currency: "RUB",
          action: "reuse",
          mapping_id: null,
          mapping_action: "stage_create",
          evidence_gaps: [],
        },
      ],
    },
    quantity_controls: [{ isin: "RU000A000000", difference: null }],
  });
  const { user } = mounted();
  await upload(user);
  const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  expect(within(summary).getByText("Денежные операции не разобраны")).toBeVisible();
  expect(summary).toHaveTextContent("Synthetic broker (#7)");
  expect(summary).toHaveTextContent("01.01.2030 — 31.01.2030");
  expect(summary).toHaveTextContent("Оригинал: synthetic.xml");
  expect(summary).toHaveTextContent("Инструменты каталога: переиспользуются 1; новых решений 0");
  expect(summary).toHaveTextContent(
    "Привязки инструментов: существующих 0; новых в source-DRAFT 1",
  );
  expect(screen.getByRole("table", { name: "Позиции по исходному отчёту" })).not.toBeVisible();
  expect(within(summary).getByText("money_semantics_unsupported")).not.toBeVisible();
  await user.click(within(summary).getByText("Технические причины Preview"));
  expect(within(summary).getByText("money_semantics_unsupported")).toBeVisible();
  await user.click(within(summary).getByText("Инструменты и контроль количества"));
  expect(summary).toHaveTextContent("разница количества Неизвестно");
  await user.click(screen.getByText("Полный состав источника и привязки"));
  expect(screen.getByRole("table", { name: "Позиции по исходному отчёту" })).toBeVisible();
  expect(
    summary.compareDocumentPosition(
      screen.getByRole("table", { name: "Позиции по исходному отчёту" }),
    ) & 4,
  ).toBeTruthy();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

it("unknown diagnostics stay visible and do not invent an Apply gate for a supported incomplete DRAFT", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    exceptions: ["future_unknown", "__proto__"],
  });
  const { user } = mounted();
  await upload(user);
  const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  for (const code of ["future_unknown", "__proto__"])
    expect(
      within(summary)
        .getAllByText(code)
        .some((node) => node.closest("details") === null),
    ).toBe(true);
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeEnabled();
  expect(summary).toHaveTextContent("Покрытие счёта, себестоимость, налоги и НКД не подтверждены");
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it.each([null, "0.001", ""])(
  "missing or unrepresentable source value %s remains UNKNOWN instead of a partial zero total",
  async (value) => {
    known();
    vi.mocked(previewBrokerMonth).mockResolvedValue({
      ...preview,
      document: {
        ...document,
        positions: [{ ...document.positions[0], ending_value: value }],
        rub_money: [],
      },
    });
    const { user } = mounted();
    await upload(user);
    const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
    expect(
      within(summary).getByText("Общая оценка источника, включая cash").parentElement,
    ).toHaveTextContent("Неизвестно → Неизвестно");
    expect(within(summary).getByText("Отдельный RUB cash").parentElement).toHaveTextContent(
      "Неизвестно → Неизвестно",
    );
    expect(summary).toHaveTextContent("Решения по инструментам в Preview не указаны — неизвестно");
  },
);
it("missing currency and source conflict give next actions without an enable/ignore control", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    can_apply: false,
    conflicts: ["instrument_currency_unproven", "overlapping_endpoint_conflict"],
    identity: {
      instruments: [],
      evidence_gaps: [{ isin: "RU000A000777", code: "instrument_currency_unproven" }],
    },
  });
  const { user } = mounted();
  await upload(user);
  const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  expect(summary).toHaveTextContent("Валюта инструмента не подтверждена");
  expect(summary).toHaveTextContent("RUB автоматически не назначается");
  expect(summary).toHaveTextContent("RU000A000777");
  expect(summary).toHaveTextContent("Пересекающиеся источники противоречат друг другу");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
it("acknowledged source retains the exact reviewed alias batch without asking for a second write consent", async () => {
  known();
  const bindings = [{ identity: "NEW", hermes_id: 7 }];
  vi.mocked(previewBrokerMonth).mockResolvedValue({ ...preview, account_bindings: bindings });
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("Synthetic GET failed"));
  const { user } = mounted();
  await upload(user);
  await user.click(await screen.findByRole("checkbox", { name: /Я подтверждаю/ }));
  await user.click(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  );
  await screen.findByText("Synthetic GET failed");
  expect(screen.queryByRole("checkbox", { name: /Я подтверждаю/ })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /сохранить неполный source-DRAFT/ }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Повторить чтение" }));
  await screen.findByText(/Сохранённый результат подтверждён/);
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  expect(vi.mocked(applyBrokerMonth).mock.calls[0][4]).toEqual(bindings);
});
it("a double click while saving cannot submit a second financial intent", async () => {
  known();
  const pending = deferred<BrokerMonthReadback>();
  vi.mocked(applyBrokerMonth).mockReturnValueOnce(pending.promise);
  const { user } = mounted();
  await upload(user);
  const save = await screen.findByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  await user.dblClick(save);
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Повторить чтение" })).toBeDisabled();
  const id = vi.mocked(applyBrokerMonth).mock.calls[0][3];
  await act(async () => {
    pending.resolve(persisted(id));
  });
  await screen.findByText(/Сохранённый результат подтверждён/);
});

it("absent position evidence does not turn a known cash amount into a portfolio total", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    document: { ...document, positions: [] },
  });
  const { user } = mounted();
  await upload(user);
  const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  expect(
    within(summary).getByText("Общая оценка источника, включая cash").parentElement,
  ).toHaveTextContent("Неизвестно → Неизвестно");
  expect(within(summary).getByText("Отдельный RUB cash").parentElement).toHaveTextContent(
    "400 ₽ → 400 ₽",
  );
});
it("a supported new instrument plan is disclosed without a new per-ISIN decision gate", async () => {
  known();
  vi.mocked(previewBrokerMonth).mockResolvedValue({
    ...preview,
    identity: {
      evidence_gaps: [],
      instruments: [
        {
          isin: "RU000A000777",
          hermes_id: null,
          instrument_type: "stock",
          currency: "RUB",
          action: "stage_create",
          mapping_id: null,
          mapping_action: "stage_create",
          evidence_gaps: [],
        },
      ],
    },
  });
  const { user } = mounted();
  await upload(user);
  const summary = await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  expect(summary).toHaveTextContent("Инструменты каталога: переиспользуются 0; новых решений 1");
  await user.click(within(summary).getByText("Инструменты и контроль количества"));
  expect(summary).toHaveTextContent("Планируется новый инструмент по доказательствам Preview");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeEnabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

function sessionFixture() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const session = brokerOriginalSession(client);
  const file = original();
  session.context(1, false);
  session.select(file, 1, "7");
  return { session, client, file };
}
const missing = () =>
  new ApiClientError(404, { code: "not_found", message: "not found", details: [] });
it.each(["timeout", "404", "account", "month", "request", "digest", "payload"])(
  "acknowledged %s GET failure keeps original key and only GET recovery",
  async (kind) => {
    const { session, file } = sessionFixture();
    const bad = persisted("fixed");
    if (kind === "timeout") vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("timeout"));
    else if (kind === "404") vi.mocked(readBrokerMonth).mockRejectedValueOnce(missing());
    else {
      if (kind === "account") bad.account_id++;
      if (kind === "month") bad.reporting_month_id++;
      if (kind === "request") bad.request_id = "foreign";
      if (kind === "digest") bad.confirmation_digest = "changed";
      if (kind === "payload") bad.accepted.cash_id++;
      vi.mocked(readBrokerMonth).mockResolvedValueOnce(bad);
    }
    await session.start(preview, "fixed");
    expect(session.snapshot().pending?.committed).toBeTruthy();
    expect(session.snapshot().confirmed).toBeNull();
    expect(session.candidate(persisted("fixed"))).toBeUndefined();
    await session.post();
    expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
    await session.retryRead();
    expect(session.candidate(persisted("fixed"))).toBe(file);
    expect(vi.mocked(readBrokerMonth).mock.calls).toEqual([["fixed"], ["fixed"]]);
  },
);
it("lost POST first GET recovers committed receipt without another POST", async () => {
  const { session, file } = sessionFixture();
  vi.mocked(applyBrokerMonth).mockRejectedValueOnce(new Error("lost response"));
  await session.start(preview, "lost");
  expect(session.candidate(persisted("lost"))).toBe(file);
  expect(vi.mocked(applyBrokerMonth).mock.invocationCallOrder[0]).toBeLessThan(
    vi.mocked(readBrokerMonth).mock.invocationCallOrder[0],
  );
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
});
it("lost POST + absent GET offers only exact-key replay with the original File/digest/aliases", async () => {
  const { session } = sessionFixture();
  vi.mocked(applyBrokerMonth).mockRejectedValueOnce(new Error("lost response"));
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(missing());
  const plan = { ...preview, account_bindings: [{ identity: "NEW", hermes_id: 7 }] };
  await session.start(plan, "lost");
  expect(session.snapshot().pending?.committed).toBeNull();
  expect(session.snapshot().pending?.replayAllowed).toBe(true);
  expect(session.snapshot().confirmed).toBeNull();
  await session.post();
  expect(vi.mocked(applyBrokerMonth).mock.calls[1]).toEqual(
    vi.mocked(applyBrokerMonth).mock.calls[0],
  );
});
it.each(["source_projection_changed", "accepted_mapping_changed", "account_binding_changed"])(
  "lost response cannot confirm or replay invalidated receipt %s",
  async (code) => {
    const { session } = sessionFixture();
    vi.mocked(applyBrokerMonth).mockRejectedValueOnce(new Error("lost response"));
    vi.mocked(readBrokerMonth).mockResolvedValueOnce({ ...persisted("lost"), exceptions: [code] });
    await session.start(preview, "lost");
    expect(session.snapshot().confirmed).toBeNull();
    expect(session.snapshot().pending).toBeNull();
    await session.post();
    expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  },
);
it.each(["file", "account", "month", "closed", "restore", "mapping-ABA"])(
  "late acknowledged POST cannot cross %s session boundary",
  async (kind) => {
    const { session, file, client } = sessionFixture();
    const late = deferred<BrokerMonthReadback>();
    vi.mocked(applyBrokerMonth).mockReturnValueOnce(late.promise);
    const work = session.start(preview, "late");
    if (kind === "file") {
      session.select(original("b.xml"), 1, "7");
      session.select(file, 1, "7");
    }
    if (kind === "account") {
      session.select(file, 1, "8");
      session.select(file, 1, "7");
    }
    if (kind === "month") {
      session.context(2, false);
      session.context(1, false);
    }
    if (kind === "closed") {
      session.context(1, true);
      session.context(1, false);
    }
    if (kind === "restore") session.clear();
    if (kind === "mapping-ABA") {
      client.setQueryData(["broker-identity-mappings"], ["A"]);
      client.setQueryData(["broker-identity-mappings"], ["B"]);
      client.setQueryData(["broker-identity-mappings"], ["A"]);
    }
    late.resolve(persisted("late"));
    await work;
    expect(session.snapshot().pending).toBeNull();
    expect(session.snapshot().confirmed).toBeNull();
    expect(readBrokerMonth).not.toHaveBeenCalled();
  },
);
it("unmount/remount keeps exact original and acknowledged recovery; reload uses a fresh empty session", async () => {
  known();
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("offline"));
  const { user, query, unmount } = mounted();
  const file = original();
  await upload(user, file);
  await user.click(await screen.findByRole("button", { name: /Подтвердить сводку и сохранить/ }));
  await screen.findByText("offline");
  unmount();
  render(
    <QueryClientProvider client={query}>
      <BrokerMonthReview monthId={1} closed={false} />
    </QueryClientProvider>,
  );
  expect(brokerOriginalSession(query).snapshot().file).toBe(file);
  await user.click(await screen.findByRole("button", { name: "Повторить чтение" }));
  await screen.findByText(/Сохранённый результат подтверждён/);
  expect(screen.getByRole("list", { name: "Выбранные оригиналы Money" })).toHaveTextContent(
    file.name,
  );
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
  expect(brokerOriginalSession(new QueryClient()).snapshot().file).toBeNull();
});
it("catalogue mutation while unmounted retains File but drops proof; returning requires fresh Preview", async () => {
  known();
  const { user, query, unmount } = mounted();
  const file = original();
  await upload(user, file);
  unmount();
  query.setQueryData(["broker-identity-mappings"], ["changed"]);
  render(
    <QueryClientProvider client={query}>
      <BrokerMonthReview monthId={1} closed={false} />
    </QueryClientProvider>,
  );
  expect(brokerOriginalSession(query).snapshot().file).toBe(file);
  expect(screen.queryByRole("button", { name: /Подтвердить сводку/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
  await screen.findByRole("button", { name: /Подтвердить сводку/ });
  expect(previewBrokerMonth).toHaveBeenCalledTimes(2);
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

it("late GET cannot hand original across a file ABA transition", async () => {
  const { session, file } = sessionFixture();
  const late = deferred<BrokerMonthReadback>();
  vi.mocked(readBrokerMonth).mockReturnValueOnce(late.promise);
  const work = session.start(preview, "late-get");
  await waitFor(() => expect(readBrokerMonth).toHaveBeenCalledTimes(1));
  session.select(original("b.xml"), 1, "7");
  session.select(file, 1, "7");
  late.resolve(persisted("late-get"));
  await work;
  expect(session.snapshot().confirmed).toBeNull();
  expect(session.candidate(persisted("late-get"))).toBeUndefined();
});
it("an independently refreshed mapping change evicts confirmed candidate even while panel is unmounted", async () => {
  const { session, client } = sessionFixture();
  await client.fetchQuery({ queryKey: ["broker-identity-mappings"], queryFn: async () => ["A"] });
  await session.start(preview, "mapped");
  expect(session.snapshot().confirmed).toBeTruthy();
  await client.fetchQuery({ queryKey: ["broker-identity-mappings"], queryFn: async () => ["B"] });
  expect(session.snapshot().confirmed).toBeNull();
  expect(session.snapshot().file).toBeTruthy();
});
it("CLOSED GET evicts raw original and pending state; reopen cannot revive them", async () => {
  const { session } = sessionFixture();
  vi.mocked(readBrokerMonth).mockResolvedValueOnce({ ...persisted("closed"), status: "closed" });
  await session.start(preview, "closed");
  session.context(1, false);
  expect(session.snapshot().file).toBeNull();
  expect(session.snapshot().pending).toBeNull();
  expect(session.snapshot().confirmed).toBeNull();
});

it("normalized JSON object key order does not reject the exact source; array order and values remain evidence", async () => {
  const { session, file } = sessionFixture();
  vi.mocked(readBrokerMonth).mockImplementationOnce(async (id) => ({
    ...persisted(id),
    accepted: {
      ...persisted(id).accepted,
      document: Object.fromEntries(Object.entries(document).reverse()) as typeof document,
    },
  }));
  await session.start(preview, "reordered");
  expect(session.candidate(persisted("reordered"))).toBe(file);
});

it("wrong-context 200 POST response is an unknown outcome, never a true acknowledgement", async () => {
  const { session } = sessionFixture();
  vi.mocked(applyBrokerMonth).mockResolvedValueOnce(persisted("wrong-request", 8));
  vi.mocked(readBrokerMonth).mockRejectedValueOnce(new Error("GET timeout"));
  await session.start(preview, "original-key");
  expect(session.snapshot().pending?.committed).toBeNull();
  expect(session.snapshot().confirmed).toBeNull();
  expect(readBrokerMonth).toHaveBeenCalledWith("original-key");
});
it("a newly introduced receipt exception after a lost POST requires fresh Preview rather than aggregate readiness or replay", async () => {
  const { session } = sessionFixture();
  vi.mocked(applyBrokerMonth).mockRejectedValueOnce(new Error("lost"));
  vi.mocked(readBrokerMonth).mockResolvedValueOnce({
    ...persisted("changed"),
    exceptions: [...preview.exceptions, "overlapping_endpoint_conflict"],
  });
  await session.start(preview, "changed");
  expect(session.snapshot().confirmed).toBeNull();
  expect(session.snapshot().pending).toBeNull();
  await session.post();
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
});

it("observed nonmanual mapping refetch still invalidates proof despite observer notification order", async () => {
  const { session, client } = sessionFixture();
  const key = ["broker-identity-mappings"];
  await client.fetchQuery({ queryKey: key, queryFn: async () => ["A"] });
  const observer = new QueryObserver(client, {
    queryKey: key,
    queryFn: async () => ["B"],
    enabled: false,
  });
  const stop = observer.subscribe(() => undefined);
  await session.start(preview, "observed");
  expect(session.snapshot().confirmed).toBeTruthy();
  await client.fetchQuery({ queryKey: key, queryFn: async () => ["B"] });
  expect(session.snapshot().confirmed).toBeNull();
  stop();
});

it("explicit Preview after a confirmed source Save displays the fresh summary instead of a retained receipt hiding it", async () => {
  known();
  const { user } = mounted();
  await upload(user);
  await user.click(await screen.findByRole("button", { name: /Подтвердить сводку и сохранить/ }));
  await screen.findByText(/Сохранённый результат подтверждён/);
  expect(screen.queryByRole("region", { name: "Сводка исходного DRAFT" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
  await screen.findByRole("region", { name: "Сводка исходного DRAFT" });
  expect(previewBrokerMonth).toHaveBeenCalledTimes(2);
  expect(applyBrokerMonth).toHaveBeenCalledTimes(1);
});

function inboxPreview(): BrokerMonthPreview {
  const known = Array.from({ length: 12 }, (_, i) => ({
    isin: `RU000A${String(i + 2).padStart(6, "0")}`,
    source_name: `Synthetic ready ${i + 1}`,
    intake_status: "matched" as const,
    hermes_id: i + 1,
    instrument_type: "stock",
    currency: "RUB",
    action: "reuse" as const,
    mapping_id: i + 1,
    mapping_action: "reuse" as const,
    evidence_gaps: [],
    review_reasons: [],
  }));
  return {
    ...preview,
    can_apply: false,
    conflicts: ["identity_batch_conflict"],
    identity: {
      instruments: [
        ...known,
        {
          isin: "RU000A000001",
          source_name: "Synthetic pending bond",
          intake_status: "pending_review",
          hermes_id: null,
          instrument_type: "bond",
          currency: null,
          action: "stage_create",
          mapping_id: null,
          mapping_action: "stage_create",
          evidence_gaps: ["instrument_currency_unproven"],
          review_reasons: ["instrument_currency_unproven"],
          observations: [{ section: "positions", ordinal: 12, source_account: "synthetic" }],
          candidates: [
            {
              hermes_id: 99,
              name: "Synthetic pending bond",
              isin: null,
              currency: "RUB",
              instrument_type: "bond",
              reasons: ["exact_isin_required"],
            },
          ],
        },
      ],
      evidence_gaps: [{ isin: "RU000A000001", code: "instrument_currency_unproven" }],
    },
  };
}
const publicBond = {
  isin: "RU000A000001",
  proof_id: "d".repeat(64),
  retrieved_at: "2030-01-01T00:00:00Z",
  expires_at: "2099-01-01T00:00:00Z",
  reasons: [],
  candidates: [
    {
      isin: "RU000A000001",
      secid: "SYNTHBOND",
      name: "Synthetic official bond",
      instrument_type: "bond",
      currency: "RUB",
      url: "https://iss.moex.com/iss/securities/SYNTHBOND.json",
      reasons: [],
    },
  ],
};
it("source inbox shows 12 matched and one pending; one consent, explicit decision, fresh Preview then existing DRAFT/GET", async () => {
  const pending = inboxPreview();
  vi.mocked(previewBrokerMonth).mockImplementation(async (_file, intent) =>
    intent.instrument_decisions?.length
      ? {
          ...pending,
          confirmation_digest: "e".repeat(64),
          instrument_decisions: intent.instrument_decisions,
          can_apply: true,
          conflicts: [],
          identity: {
            evidence_gaps: [],
            instruments: (pending.identity?.instruments ?? []).map((i) => ({
              ...i,
              intake_status: "matched",
              evidence_gaps: [],
              review_reasons: [],
            })),
          },
        }
      : pending,
  );
  vi.mocked(lookupPublicIdentities).mockResolvedValue([publicBond]);
  vi.mocked(applyBrokerMonth).mockImplementation(async (_file, _intent, _digest, id) => ({
    ...persisted(id),
    confirmation_digest: "e".repeat(64),
  }));
  vi.mocked(readBrokerMonth).mockImplementation(async (id) => {
    const value = { ...persisted(id), confirmation_digest: "e".repeat(64) };
    vi.mocked(listBrokerMonths).mockResolvedValue([value]);
    return value;
  });
  const user = show();
  await inspect(user);
  expect(screen.getByText(/MATCHED — 12; PENDING REVIEW — 1/)).toBeInTheDocument();
  const save = screen.getByRole("button", {
    name: "Подтвердить сводку и сохранить неполный source-DRAFT",
  });
  expect(save).toBeDisabled();
  expect(lookupPublicIdentities).not.toHaveBeenCalled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(screen.getByRole("option", { name: /NULL-ISIN/ })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /Разрешаю автоматический поиск/ }));
  await screen.findByRole("option", { name: /Создать: Synthetic official bond/ });
  expect(lookupPublicIdentities).toHaveBeenCalledExactlyOnceWith(
    ["RU000A000001"],
    expect.any(AbortSignal),
  );
  await user.selectOptions(
    screen.getByLabelText("Решение для RU000A000001"),
    `official:${publicBond.proof_id}`,
  );
  await user.click(screen.getByRole("button", { name: /Подтвердить решения и заново/ }));
  await waitFor(() =>
    expect(previewBrokerMonth).toHaveBeenLastCalledWith(
      expect.any(File),
      {
        reporting_month_id: 1,
        account_id: 7,
        instrument_decisions: [{ isin: publicBond.isin, proof_id: publicBond.proof_id }],
      },
      expect.any(AbortSignal),
    ),
  );
  expect(applyBrokerMonth).not.toHaveBeenCalled();
  expect(lookupPublicIdentities).toHaveBeenCalledTimes(1);
  await user.click(
    await screen.findByRole("button", {
      name: "Подтвердить сводку и сохранить неполный source-DRAFT",
    }),
  );
  await waitFor(() => expect(applyBrokerMonth).toHaveBeenCalled());
  expect(vi.mocked(applyBrokerMonth).mock.calls[0][1].instrument_decisions).toEqual([
    { isin: publicBond.isin, proof_id: publicBond.proof_id },
  ]);
  await screen.findByText(/Сохранённый результат подтверждён независимым чтением/);
  expect(readBrokerMonth).toHaveBeenCalledTimes(1);
});

it("source inbox refresh recovers failed public lookup and preserves original without a per-ISIN consent loop", async () => {
  vi.mocked(previewBrokerMonth).mockResolvedValue(inboxPreview());
  vi.mocked(lookupPublicIdentities)
    .mockResolvedValueOnce([
      { ...publicBond, candidates: [], reasons: ["official_lookup_unavailable"] },
    ])
    .mockResolvedValueOnce([publicBond]);
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox", { name: /Разрешаю автоматический поиск/ }));
  await screen.findByText("official_lookup_unavailable");
  await user.click(screen.getByRole("button", { name: "Обновить публичные варианты и Preview" }));
  await screen.findByRole("option", { name: /Создать: Synthetic official bond/ });
  expect(lookupPublicIdentities).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("checkbox", { name: /Разрешаю автоматический поиск/ })).toBeChecked();
  expect(
    screen.getByRole("button", { name: "Подтвердить сводку и сохранить неполный source-DRAFT" }),
  ).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});

it("official USD denomination stays in pending with a disabled creation option", async () => {
  vi.mocked(previewBrokerMonth).mockResolvedValue(inboxPreview());
  vi.mocked(lookupPublicIdentities).mockResolvedValue([
    { ...publicBond, candidates: publicBond.candidates.map((c) => ({ ...c, currency: "USD" })) },
  ]);
  const user = show();
  await inspect(user);
  await user.click(screen.getByRole("checkbox", { name: /Разрешаю автоматический поиск/ }));
  expect(
    await screen.findByRole("option", { name: /Создать:.*USD.*instrument_currency_unsupported/ }),
  ).toBeDisabled();
  expect(screen.getByText(/MATCHED — 12; PENDING REVIEW — 1/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Подтвердить решения и заново/ })).toBeDisabled();
  expect(applyBrokerMonth).not.toHaveBeenCalled();
});
