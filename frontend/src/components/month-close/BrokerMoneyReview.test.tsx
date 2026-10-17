import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  applyBrokerMoney,
  previewBrokerMoney,
  readBrokerMoney,
  type MoneyPreview,
  type MoneyReadback,
} from "../../api/brokerMoney";
import { BrokerMoneyReview, MoneyStored } from "./BrokerMoneyReview";

vi.mock("../../api/instruments", () => ({
  listInstruments: async () => [
    { id: 2, name: "Synthetic bond", isin: "RU000A000001", currency: "RUB" },
  ],
}));
vi.mock("../../api/brokerMoney", () => ({
  previewBrokerMoney: vi.fn(),
  applyBrokerMoney: vi.fn(),
  readBrokerMoney: vi.fn(),
}));
const inventory: MoneyPreview["inventory"] = [
  {
    occurrence: { import_id: 10, section: "money", ordinal: 1 },
    candidate_kind: "coupon_paid_candidate",
    description: "Synthetic coupon",
    date: "2030-01-17",
    signed_amount: "1000.00",
    currency: "RUB",
    reasons: [],
  },
  {
    occurrence: { import_id: 10, section: "money", ordinal: 2 },
    candidate_kind: "account_cash_in_candidate",
    description: "Synthetic account funding",
    date: "2030-01-17",
    signed_amount: "50000.00",
    currency: "RUB",
    reasons: [],
  },
  {
    occurrence: { import_id: 10, section: "money", ordinal: 3 },
    candidate_kind: "trade_paid_nkd_candidate",
    description: "Synthetic NKD",
    date: "2030-01-17",
    signed_amount: "-125.50",
    currency: "RUB",
    reasons: [],
  },
];
const readback = (id: string): MoneyReadback => ({
  contract_version: "broker_money_v1",
  request_id: id,
  confirmation_digest: "b".repeat(64),
  base_request_id: "base",
  account_id: 1,
  reporting_month_id: 1,
  accepted: { synthetic: true },
  targets: [
    {
      role: "coupon",
      target_id: 7,
      facts: { net_amount_kopecks: "100000", tax_amount_kopecks: null },
      effective: true,
      exceptions: [],
    },
    {
      role: "account_funding",
      target_id: "h2",
      facts: { boundary_amount_kopecks: "5000000" },
      effective: true,
      exceptions: [],
      h2: { account_scope: { status: "authoritative" }, portfolio_scope: { status: "unknown" } },
    },
  ],
  exceptions: ["money_semantics_unsupported"],
  bookkeeping_ready: false,
});
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(previewBrokerMoney).mockImplementation(async (_files, intent) => ({
    ...intent,
    confirmation_digest: "b".repeat(64),
    can_apply: intent.money_decisions.every((d) =>
      d.role === "coupon"
        ? !!d.coupon_claims
        : d.role === "trade"
          ? !!d.trade_claims
          : !!d.owner_flow_intent,
    ),
    blockers: [],
    exceptions: ["money_semantics_unsupported"],
    sources: [],
    inventory,
    trade_choices: [
      {
        trade_id: 7,
        ids: ["native-A", "native-B"],
        source_identity: "e".repeat(64),
        instrument_id: 2,
        core: {
          isin: "RU000A000001",
          trade_time: "2030-01-15T09:00:00",
          trade_amount: "10125.50",
          quantity: "1",
        },
        revision: { revision: "1" },
      },
    ],
    decisions: intent.money_decisions.map((d) => ({
      decision: d,
      occurrences: [d.seed],
      target_id: null,
      action: "create",
      blockers: [],
      review_context_digest: "a".repeat(64),
      ...(d.role === "trade"
        ? {
            native_ids: ["native-A", "native-B"],
            cash_review: {
              settlement: "-10000.00",
              paid_nkd: "-125.50",
              commission: "-10.00",
              native_total: "10125.50",
              native_nkd: "125.50",
              native_fee: "10.00",
              settlement_date: "2030-01-17",
              depo_settlement_date: "2030-01-17",
            },
          }
        : {}),
      ...(d.role === "account_funding"
        ? {
            owner_flow_intent: {
              evidence_version: "h2-a1-owner-rub-v2",
              account_id: 1,
              seed: d.seed,
            },
            h2_plan: {
              source_set_fingerprint: "c".repeat(64),
              review_context_digest: "d".repeat(64),
            },
          }
        : {}),
    })),
  }));
  vi.mocked(applyBrokerMoney).mockImplementation(async (_files, _intent, _digest, id) =>
    readback(id),
  );
  vi.mocked(readBrokerMoney).mockImplementation(async (id) => readback(id));
});
it("persistent panel shows earlier coupon and funding after a later batch and reload", () => {
  const saved = readback("later-batch");
  const earlier = saved.targets;
  saved.targets = [{ ...earlier[0], target_id: 8, facts: { net_amount_kopecks: "200000" } }];
  saved.current_targets = [...earlier, ...saved.targets];
  render(<MoneyStored saved={saved} />);
  const stored = screen.getByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  expect(within(stored).getAllByRole("row")).toHaveLength(4);
  expect(stored).toHaveTextContent("1 000");
  expect(stored).toHaveTextContent("2 000");
  expect(stored).toHaveTextContent("50 000");
});
it("legacy PDF technical tax zero remains unknown when provenance says unavailable", () => {
  const saved = readback("synthetic");
  saved.targets[0].facts = { net_amount_kopecks: "100000", tax_amount_kopecks: "0" };
  saved.targets[0].components = { tax_amount_kopecks: null };
  render(<MoneyStored saved={saved} />);
  expect(screen.getByRole("table")).toHaveTextContent("Неизвестно");
});
function show(closed = false, originalFile?: File) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <BrokerMoneyReview
        baseRequestId="base"
        monthId={1}
        accountId={1}
        importId={10}
        closed={closed}
        originalFile={originalFile}
      />
    </QueryClientProvider>,
  );
}
async function prepare() {
  const user = userEvent.setup();
  await user.click(screen.getByText("Принять Money в этот черновик"));
  await user.upload(
    screen.getByLabelText(/Оригинальные XML для Money/),
    new File(["synthetic"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  const table = await screen.findByRole("table", { name: "Все наблюдения Money" });
  expect(table).toHaveTextContent("Synthetic NKD");
  for (const checkbox of within(table).getAllByRole("checkbox").slice(0, 2))
    await user.click(checkbox);
  await user.selectOptions(screen.getByLabelText("Подтверждённая облигация для строки 2"), "2");
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  await user.click(
    await screen.findByRole("checkbox", { name: /Я подтверждаю перечисленные конкретные/ }),
  );
  return user;
}
it("one specific batch review, one Apply and independent GET; net/NULL/portfolio UNKNOWN stay visible", async () => {
  show();
  const user = await prepare();
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  const stored = await screen.findByRole("table", {
    name: "Сохранённые Money и доказательства покупки",
  });
  expect(stored).toHaveTextContent("Неизвестно");
  expect(stored).toHaveTextContent("50 000");
  expect(applyBrokerMoney).toHaveBeenCalledTimes(1);
  expect(readBrokerMoney).toHaveBeenCalledTimes(1);
  const selected = vi.mocked(applyBrokerMoney).mock.calls[0][1].money_decisions;
  expect(selected[0].coupon_claims?.exact_row_instrument_link).toBe(true);
  expect(selected[1].owner_flow_intent?.claims).toMatchObject({
    not_tracked_account_transfer: true,
    owner_capital_crossing: true,
  });
  expect(screen.getByText(/Внешний взнос портфеля не подтверждён/)).toBeInTheDocument();
});
it("failed GET retries only reading and cannot claim success from POST", async () => {
  show();
  const user = await prepare();
  vi.mocked(readBrokerMoney).mockRejectedValueOnce(new Error("Synthetic GET unavailable"));
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  const retry = await screen.findByRole("button", { name: "Повторить GET Money" });
  expect(
    screen.queryByRole("table", { name: "Сохранённые Money и доказательства покупки" }),
  ).not.toBeInTheDocument();
  await user.click(retry);
  await screen.findByRole("table", { name: "Сохранённые Money и доказательства покупки" });
  expect(applyBrokerMoney).toHaveBeenCalledTimes(1);
  expect(readBrokerMoney).toHaveBeenCalledTimes(2);
});
it("mismatched GET keeps the financial batch unconfirmed", async () => {
  show();
  const user = await prepare();
  vi.mocked(readBrokerMoney).mockImplementation(async (id) => ({
    ...readback(id),
    account_id: 99,
  }));
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/другого счёта/));
  expect(
    screen.queryByRole("table", { name: "Сохранённые Money и доказательства покупки" }),
  ).not.toBeInTheDocument();
});
it("CLOSED exposes no financial writer", async () => {
  show(true);
  expect(screen.queryByText("Принять Money в этот черновик")).not.toBeInTheDocument();
});
it("late confirmed Preview after navigation cannot dispatch Apply", async () => {
  const view = show();
  const user = await prepare();
  let finish!: (value: MoneyPreview) => void;
  vi.mocked(previewBrokerMoney).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  view.unmount();
  finish({
    contract_version: "broker_money_v1",
    confirmation_digest: "b".repeat(64),
    base_request_id: "base",
    account_id: 1,
    reporting_month_id: 1,
    can_apply: true,
    blockers: [],
    exceptions: [],
    sources: [],
    inventory: [],
    decisions: [],
  });
  await Promise.resolve();
  expect(applyBrokerMoney).not.toHaveBeenCalled();
});

it("requires explicit native execution and independent NKD basis before Apply and verifies GET", async () => {
  show();
  const user = userEvent.setup();
  await user.click(screen.getByText("Принять Money в этот черновик"));
  await user.upload(
    screen.getByLabelText(/Оригинальные XML для Money/),
    new File(["synthetic"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  const table = await screen.findByRole("table", { name: "Все наблюдения Money" });
  await user.click(within(table).getAllByRole("checkbox")[2]);
  const exact = screen.getByLabelText("Точное исполнение покупки для НКД строки 4");
  expect(exact).toHaveTextContent("native-A / native-B");
  await user.selectOptions(exact, "7");
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  expect(
    screen.getByRole("checkbox", { name: /Я подтверждаю перечисленные конкретные/ }),
  ).toBeDisabled();
  expect(applyBrokerMoney).not.toHaveBeenCalled();
  await user.selectOptions(
    screen.getByLabelText("Независимо доказанное включение НКД в native сумму сделки"),
    "includes_paid_nkd",
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  await user.click(
    screen.getByRole("checkbox", { name: /Я подтверждаю перечисленные конкретные/ }),
  );
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  await waitFor(() => expect(readBrokerMoney).toHaveBeenCalledTimes(1));
  const accepted = vi.mocked(applyBrokerMoney).mock.calls[0][1].money_decisions[0];
  expect(accepted.trade_id).toBe(7);
  expect(accepted.expected_trade_revision).toBe(1);
  expect(accepted.trade_claims).toMatchObject({
    native_total_basis: "includes_paid_nkd",
    native_total_basis_independently_proved: true,
    fee_separately_charged: true,
  });
});

it("offers native stock commission and requires independent basis evidence before typed two-leg Apply/GET/reload", async () => {
  const oldPreview = vi.mocked(previewBrokerMoney).getMockImplementation();
  if (!oldPreview) throw new Error("missing synthetic preview");
  vi.mocked(previewBrokerMoney).mockImplementation(async (files, intent) => {
    const result = await oldPreview(files, intent);
    result.inventory = [
      {
        occurrence: { import_id: 10, section: "money", ordinal: 1 },
        candidate_kind: "unsupported",
        s1_kind: "commission",
        trade_identity: "e".repeat(64),
        description: "Комиссия по сделке native-A",
        date: "2030-01-17",
        signed_amount: "-1.25",
        currency: "RUB",
        reasons: [],
      },
    ];
    const trade = result.trade_choices?.[0];
    if (!trade) throw new Error("missing synthetic trade");
    trade.instrument_type = "stock";
    result.decisions.forEach((proposed) => {
      proposed.cash_review = {
        settlement: "-100.00",
        commission: "-1.25",
        native_total: "100.00",
        native_fee: "1.25",
        settlement_date: "2030-01-17",
        depo_settlement_date: "2030-01-17",
      };
    });
    return result;
  });
  const stockRead = (id: string): MoneyReadback => ({
    ...readback(id),
    exceptions: [],
    bookkeeping_ready: true,
    targets: [
      {
        role: "trade",
        target_id: 7,
        facts: null,
        effective: true,
        exceptions: [],
        trade_revision: { revision: "2" },
        cash_proof: {
          proof_variant: "stock_buy_separate_fee_v1",
          signed_minor: {
            settlement: "-10000",
            commission: "-125",
            native_total: "10000",
            native_fee: "125",
          },
          claims: {
            native_total_basis: "excludes_separate_fee",
            basis_reference: "independent-source-v1",
          },
        },
      },
    ],
  });
  vi.mocked(applyBrokerMoney).mockImplementation(async (_files, _intent, _digest, id) =>
    stockRead(id),
  );
  vi.mocked(readBrokerMoney).mockImplementation(async (id) => stockRead(id));
  const view = show();
  const user = userEvent.setup();
  await user.click(screen.getByText("Принять Money в этот черновик"));
  await user.upload(
    screen.getByLabelText(/Оригинальные XML для Money/),
    new File(["synthetic"], "synthetic.xml"),
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  await user.click(screen.getByRole("checkbox", { name: "Комиссия покупки акции" }));
  await user.selectOptions(
    screen.getByLabelText("Точное исполнение покупки акции для строки 2"),
    "7",
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  const confirmation = screen.getByRole("checkbox", {
    name: /Я подтверждаю перечисленные конкретные/,
  });
  expect(confirmation).toBeDisabled();
  expect(confirmation).not.toBeChecked();
  expect(screen.queryByLabelText(/Независимо доказанное включение НКД/)).not.toBeInTheDocument();
  expect(screen.getByText(/Расчёт S/)).toHaveTextContent("−100");
  await user.type(
    screen.getByLabelText("Независимое основание суммы без комиссии"),
    "independent-source-v1",
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  expect(confirmation).not.toBeChecked();
  await user.click(confirmation);
  await user.click(screen.getByRole("button", { name: "Принять один Money batch" }));
  await waitFor(() => expect(readBrokerMoney).toHaveBeenCalledTimes(1));
  const accepted = vi.mocked(applyBrokerMoney).mock.calls[0][1].money_decisions[0];
  expect(accepted.trade_claims).toMatchObject({
    proof_variant: "stock_buy_separate_fee_v1",
    basis_reference: "independent-source-v1",
    native_total_basis: "excludes_separate_fee",
  });
  expect(accepted.trade_claims).not.toHaveProperty("nkd_separately_posted");
  view.unmount();
  render(<MoneyStored saved={stockRead("saved")} />);
  expect(screen.getByRole("table")).toHaveTextContent("Комиссия покупки акции");
  expect(screen.getByRole("table")).toHaveTextContent("independent-source-v1");
  expect(screen.getByRole("table")).not.toHaveTextContent("НКД");
});

it.each([false, true])(
  "retained primary plus supplemental keep exact bytes/name and union order (reverse=%s)",
  async (reverse) => {
    const primary = new File(["primary exact bytes"], "primary.xml", { type: "application/xml" });
    const supplemental = new File(["supplemental exact bytes"], "overlap.xml", {
      type: "application/xml",
    });
    show(false, reverse ? supplemental : primary);
    const user = userEvent.setup();
    await user.click(screen.getByText("Принять Money в этот черновик"));
    expect(previewBrokerMoney).not.toHaveBeenCalled();
    expect(applyBrokerMoney).not.toHaveBeenCalled();
    await user.upload(
      screen.getByLabelText(/Оригинальные XML для Money/),
      reverse ? primary : supplemental,
    );
    await user.click(screen.getByRole("button", { name: "Проверить Money" }));
    expect(vi.mocked(previewBrokerMoney).mock.calls[0][0]).toEqual(
      reverse ? [supplemental, primary] : [primary, supplemental],
    );
    expect(applyBrokerMoney).not.toHaveBeenCalled();
  },
);
it("bad supplemental remains selected after rejection and can be removed without losing the primary", async () => {
  const primary = new File(["primary"], "primary.xml", { type: "application/xml" });
  const bad = new File(["bad"], "bad.xml", { type: "application/xml" });
  show(false, primary);
  const user = userEvent.setup();
  await user.click(screen.getByText("Принять Money в этот черновик"));
  await user.upload(screen.getByLabelText(/Оригинальные XML для Money/), bad);
  vi.mocked(previewBrokerMoney).mockRejectedValueOnce(new Error("invalid supplemental"));
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  await screen.findByText("invalid supplemental");
  const selected = screen.getByRole("list", { name: "Выбранные оригиналы Money" });
  expect(selected).toHaveTextContent(primary.name);
  expect(selected).toHaveTextContent(bad.name);
  expect(applyBrokerMoney).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Убрать bad.xml" }));
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  expect(vi.mocked(previewBrokerMoney).mock.calls[1][0]).toEqual([primary]);
});

it.each(["account", "month", "base", "file", "closed", "epoch"])(
  "late Money Preview cannot revive decisions after %s ABA",
  async (kind) => {
    const primary = new File(["primary"], "primary.xml", { type: "application/xml" });
    const initial = {
      baseRequestId: "base",
      monthId: 1,
      accountId: 1,
      importId: 10,
      closed: false,
      sessionEpoch: 1,
      originalFile: primary,
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = (props: typeof initial) => (
      <QueryClientProvider client={client}>
        <BrokerMoneyReview {...props} />
      </QueryClientProvider>
    );
    const result = await vi.mocked(previewBrokerMoney).getMockImplementation()?.([primary], {
      contract_version: "broker_money_v1",
      base_request_id: "base",
      reporting_month_id: 1,
      account_id: 1,
      money_decisions: [],
    });
    let resolve!: (value: MoneyPreview) => void;
    vi.mocked(previewBrokerMoney).mockReturnValueOnce(
      new Promise<MoneyPreview>((done) => {
        resolve = done;
      }),
    );
    const view = render(tree(initial));
    const user = userEvent.setup();
    await user.click(screen.getByText("Принять Money в этот черновик"));
    await user.click(screen.getByRole("button", { name: "Проверить Money" }));
    const changed = { ...initial };
    if (kind === "account") changed.accountId++;
    if (kind === "month") changed.monthId++;
    if (kind === "base") changed.baseRequestId = "other";
    if (kind === "file") changed.originalFile = new File(["other"], "other.xml");
    if (kind === "closed") changed.closed = true;
    if (kind === "epoch") changed.sessionEpoch++;
    view.rerender(tree(changed));
    view.rerender(tree(initial));
    await act(async () => {
      resolve(result as MoneyPreview);
    });
    expect(screen.queryByRole("table", { name: "Все наблюдения Money" })).not.toBeInTheDocument();
    expect(applyBrokerMoney).not.toHaveBeenCalled();
  },
);
