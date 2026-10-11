import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  applyBrokerMoney,
  previewBrokerMoney,
  readBrokerMoney,
  type MoneyPreview,
  type MoneyReadback,
} from "../../api/brokerMoney";
import { BrokerMoneyReview } from "./BrokerMoneyReview";

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
      d.role === "coupon" ? !!d.coupon_claims : !!d.owner_flow_intent,
    ),
    blockers: [],
    exceptions: ["money_semantics_unsupported"],
    sources: [],
    inventory,
    decisions: intent.money_decisions.map((d) => ({
      decision: d,
      occurrences: [d.seed],
      target_id: null,
      action: "create",
      blockers: [],
      review_context_digest: "a".repeat(64),
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
function show(closed = false) {
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
      />
    </QueryClientProvider>,
  );
}
async function prepare() {
  const user = userEvent.setup();
  await user.click(screen.getByText("Принять купоны и пополнения в этот черновик"));
  await user.upload(
    screen.getByLabelText(/Оригинальные XML для Money/),
    new File(["synthetic"], "synthetic.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить Money" }));
  const table = await screen.findByRole("table", { name: "Все наблюдения Money" });
  expect(table).toHaveTextContent("Synthetic NKD");
  for (const checkbox of within(table).getAllByRole("checkbox")) await user.click(checkbox);
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
  const stored = await screen.findByRole("table", { name: "Сохранённые купоны и пополнения" });
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
    screen.queryByRole("table", { name: "Сохранённые купоны и пополнения" }),
  ).not.toBeInTheDocument();
  await user.click(retry);
  await screen.findByRole("table", { name: "Сохранённые купоны и пополнения" });
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
    screen.queryByRole("table", { name: "Сохранённые купоны и пополнения" }),
  ).not.toBeInTheDocument();
});
it("CLOSED exposes no financial writer", async () => {
  show(true);
  expect(screen.queryByText("Принять купоны и пополнения в этот черновик")).not.toBeInTheDocument();
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
