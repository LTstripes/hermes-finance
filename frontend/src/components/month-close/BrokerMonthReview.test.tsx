import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
import { BrokerMonthReview } from "./BrokerMonthReview";

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
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
  await screen.findByRole("button", { name: "Сформировать неполный черновик" });
}
it("requires explicit whole-account review and confirms partial DRAFT only after GET", async () => {
  const user = show();
  await inspect(user);
  const apply = screen.getByRole("button", { name: "Сформировать неполный черновик" });
  expect(apply).toBeDisabled();
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
  await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
  await user.upload(
    screen.getByLabelText("Оригинальный XML MyBroker"),
    new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
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
    await user.selectOptions(screen.getByLabelText("Брокерский счёт"), "7");
    await user.upload(
      screen.getByLabelText("Оригинальный XML MyBroker"),
      new File(["<synthetic/>"], "synthetic.xml", { type: "application/xml" }),
    );
    await user.click(screen.getByRole("button", { name: "Проверить MyBroker" }));
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
