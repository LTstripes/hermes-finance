import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import {
  confirmActualPayout,
  listPayoutObligations,
  previewActualPayout,
  readActualPayout,
  type PayoutObligation,
  type PayoutReceipt,
  type PayoutPlan,
} from "../../api/actualPayouts";
import { ApiClientError } from "../../api/client";
import { ActualPayoutReview } from "./ActualPayoutReview";

vi.mock("../../api/actualPayouts", () => ({
  confirmActualPayout: vi.fn(),
  listPayoutObligations: vi.fn(),
  previewActualPayout: vi.fn(),
  readActualPayout: vi.fn(),
}));
const obligation: PayoutObligation = {
  account_id: 1,
  reporting_month_id: 1,
  base_request_id: "base-A",
  investment_cash_flow_id: 7,
  actual: {
    event_date: "2030-01-31",
    net_amount_kopecks: "9007199254740993",
    tax_amount_kopecks: null,
  },
  money_proof_request_id: "money",
  terminal_relation: null,
  coverage_state: "unknown",
  legacy_relations: [],
  forecast_choices: [
    {
      kind: "ecf",
      facts: { id: "5", expected_date: "2030-02-01", forecast_version: "v1" },
      revision: null,
      provider_event_key: null,
    },
  ],
  candidates: [
    {
      kind: "ecf",
      facts: { id: "5", expected_date: "2030-02-01" },
      revision: null,
      provider_event_key: null,
      state: "unresolved",
    },
  ],
};
const accepted: PayoutReceipt = {
  contract_version: "broker_payout_reconciliation_v1",
  request_id: "",
  account_id: 1,
  reporting_month_id: 1,
  confirmation_digest: "b".repeat(64),
  accepted: { synthetic: "immutable" },
  relations: [{ id: 11, state: "paid", retired_request_id: null }],
  status: "draft",
};
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  vi.mocked(listPayoutObligations).mockImplementation(async (_month, account) =>
    account === 1 ? [obligation] : [],
  );
  vi.mocked(previewActualPayout).mockImplementation(async (intent) => ({
    contract_version: intent.contract_version,
    operation: intent.operation,
    scope: { account_id: intent.account_id, reporting_month_id: intent.reporting_month_id },
    targets: [{ investment_cash_flow_id: intent.investment_cash_flow_id }],
    review_context_digest: "a".repeat(64),
    confirmation_digest: "b".repeat(64),
    can_apply: !!intent.claims,
    blockers: intent.claims ? [] : ["payout_review_claim_binding_required"],
  }));
  vi.mocked(confirmActualPayout).mockImplementation(async (_intent, _digest, request) => ({
    ...accepted,
    request_id: request,
  }));
  vi.mocked(readActualPayout).mockImplementation(async (request) => ({
    ...accepted,
    request_id: request,
  }));
});
function show(accountId = 1, closed = false) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={cache}>
      <ActualPayoutReview
        monthId={1}
        accountId={accountId}
        baseRequestId="base-A"
        closed={closed}
      />
    </QueryClientProvider>,
  );
  return {
    ...view,
    scope: (account: number) =>
      view.rerender(
        <QueryClientProvider client={cache}>
          <ActualPayoutReview
            monthId={1}
            accountId={account}
            baseRequestId="base-A"
            closed={closed}
          />
        </QueryClientProvider>,
      ),
  };
}
async function prepare() {
  const user = userEvent.setup();
  await user.click(await screen.findByText("Выплата #7: требуется сверка"));
  await user.selectOptions(screen.getByLabelText("Ручной прогноз"), "5");
  for (const label of [
    "Ссылка на проверенный источник",
    "Основание точной связи события",
    "Основание полного исполнения или отзыва",
  ])
    await user.type(screen.getByLabelText(label), "synthetic-proof");
  await user.click(screen.getByRole("button", { name: "Проверить связь выплаты" }));
  await user.click(
    await screen.findByRole("checkbox", { name: /Подтверждаю это конкретное решение/ }),
  );
  return user;
}
it("explicit exact-event review sends no money and requires independent GET", async () => {
  show();
  const user = await prepare();
  expect(screen.getByText(/9007199254740993 коп/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Подтвердить связь выплаты" }));
  await waitFor(() => expect(readActualPayout).toHaveBeenCalledTimes(1));
  expect(confirmActualPayout).toHaveBeenCalledTimes(1);
  const intent = vi.mocked(confirmActualPayout).mock.calls[0][0];
  expect(intent.claims).toMatchObject({
    review_context_digest: "a".repeat(64),
    full_event_settled_not_partial: true,
    exact_manual_row_is_same_event: true,
  });
  expect(JSON.stringify(intent)).not.toContain("9007199254740993");
  await waitFor(() => expect(sessionStorage.length).toBe(0));
});
it("lost ACK survives Back/Reload remount and permits only GET", async () => {
  const view = show();
  const user = await prepare();
  vi.mocked(confirmActualPayout).mockRejectedValueOnce(new Error("lost ACK"));
  await user.click(screen.getByRole("button", { name: "Подтвердить связь выплаты" }));
  await screen.findByRole("button", { name: "Повторить GET связи" });
  expect(sessionStorage.length).toBe(1);
  view.unmount();
  show();
  await user.click(await screen.findByText("Выплата #7: требуется сверка"));
  expect(screen.getByRole("button", { name: "Проверить связь выплаты" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Повторить GET связи" }));
  await waitFor(() => expect(sessionStorage.length).toBe(0));
  expect(confirmActualPayout).toHaveBeenCalledTimes(1);
  expect(readActualPayout).toHaveBeenCalledTimes(1);
});
it("wrong-scope GET retains pending and never enables another Confirm", async () => {
  show();
  const user = await prepare();
  vi.mocked(readActualPayout).mockResolvedValue({ ...accepted, account_id: 2 });
  await user.click(screen.getByRole("button", { name: "Подтвердить связь выплаты" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Подтвердить связь выплаты" })).toBeDisabled();
  expect(sessionStorage.length).toBe(1);
});
it("definite 409 discards stale review, preserves no success, requires fresh Preview", async () => {
  show();
  const user = await prepare();
  vi.mocked(confirmActualPayout).mockRejectedValue(
    new ApiClientError(409, { code: "payout_preview_stale", message: "stale", details: [] }),
  );
  await user.click(screen.getByRole("button", { name: "Подтвердить связь выплаты" }));
  await screen.findByRole("alert");
  expect(readActualPayout).not.toHaveBeenCalled();
  expect(sessionStorage.length).toBe(0);
  expect(
    screen.queryByRole("button", { name: "Подтвердить связь выплаты" }),
  ).not.toBeInTheDocument();
});
it("A to B to A cannot revive a late Preview or its confirmation", async () => {
  const view = show();
  const user = await prepare();
  let finish!: (plan: PayoutPlan) => void;
  vi.mocked(previewActualPayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить связь выплаты" }));
  view.scope(2);
  await waitFor(() => expect(screen.queryByText(/Выплата #7/)).not.toBeInTheDocument());
  await act(async () =>
    finish({
      contract_version: "broker_payout_reconciliation_v1",
      operation: "link",
      scope: { account_id: 1, reporting_month_id: 1 },
      targets: [],
      review_context_digest: "a".repeat(64),
      confirmation_digest: "b".repeat(64),
      can_apply: true,
      blockers: [],
    }),
  );
  view.scope(1);
  await user.click(await screen.findByText("Выплата #7: требуется сверка"));
  expect(
    screen.queryByRole("button", { name: "Подтвердить связь выплаты" }),
  ).not.toBeInTheDocument();
  expect(confirmActualPayout).not.toHaveBeenCalled();
});
it("CLOSED keeps readable evidence and exposes no writer", async () => {
  show(1, true);
  await screen.findByText("Выплата #7: требуется сверка");
  expect(screen.queryByRole("button", { name: "Проверить связь выплаты" })).not.toBeInTheDocument();
  expect(confirmActualPayout).not.toHaveBeenCalled();
});
