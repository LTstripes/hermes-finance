import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { listBrokerMonths, type BrokerMonthReadback } from "../api/brokerMonths";
import { createQueryClient } from "../queryClient";
import { makeCapitalDraft } from "../test/capitalDraftFixtures";
import { uiV2Accounts, uiV2Months } from "../test/uiV2Fixtures";
import { CapitalDraftValuation } from "./CapitalDraftValuation";
import type { ReportingMonth } from "../api/types";

vi.mock("../api/brokerMonths", () => ({ listBrokerMonths: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const heading = "Черновик / предварительная оценка, не закрытый месяц";
const accounts = [
  {
    ...uiV2Accounts[0],
    id: 3,
    name: "Synthetic A",
    account_type: "brokerage",
    include_in_capital: false,
    include_in_returns: false,
  },
  { ...uiV2Accounts[0], id: 4, name: "Synthetic B", account_type: "iis" },
  { ...uiV2Accounts[0], id: 5, name: "Synthetic empty", account_type: "brokerage" },
];
function mount(rows: BrokerMonthReadback[]) {
  vi.mocked(listBrokerMonths).mockResolvedValue(rows);
  const client = createQueryClient();
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CapitalDraftValuation months={[uiV2Months[1]]} accounts={accounts} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

it("preserves null versus zero, warnings, membership and disabled Close from source GET", async () => {
  mount([makeCapitalDraft()]);
  await screen.findByRole("heading", { name: heading });
  expect(screen.getByText("Неизвестно")).toBeVisible();
  expect(screen.getByText("0 ₽")).toBeVisible();
  expect(screen.getByText(/Счёт исключён из капитала/)).toBeVisible();
  expect(screen.getByText(/Полнота покрытия: unknown/)).toBeVisible();
  expect(screen.getByText("money_semantics_unsupported")).toBeVisible();
  expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Источник и предупреждения месяца →" })).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=final_review_close",
  );
  expect(screen.queryByText("99 999,99 ₽")).toBeNull();
});

it("switches account without stale values and never borrows from inaccessible accounts", async () => {
  const second = makeCapitalDraft(4);
  if (second.accepted.document) second.accepted.document.positions[0].ending_value = "4321.98";
  mount([makeCapitalDraft(), second, makeCapitalDraft(999)]);
  const select = await screen.findByLabelText("Брокерский счёт черновика");
  fireEvent.change(select, { target: { value: "4" } });
  expect(screen.getByText("4 321,98 ₽")).toBeVisible();
  expect(screen.queryByText("1 234,56 ₽")).toBeNull();
  fireEvent.change(select, { target: { value: "5" } });
  expect(screen.getByText("Для этого счёта нет совместимого DRAFT.")).toBeVisible();
  expect(screen.queryByRole("table")).toBeNull();
});

it.each([
  "wrong-account",
  "wrong-month",
  "closed",
  "invalid",
  "missing-document",
  "inactive",
  "wrong-provider",
])("hides incompatible %s source", async (kind) => {
  const saved = makeCapitalDraft();
  if (kind === "wrong-account") saved.account_id = 999;
  if (kind === "wrong-month") saved.reporting_month_id = 13;
  if (kind === "closed") saved.status = "closed";
  if (kind === "invalid")
    Object.assign(saved, { contract_version: undefined, accepted: undefined });
  if (kind === "missing-document") saved.accepted.document = null;
  if (kind === "inactive") saved.account_id = 9;
  if (kind === "wrong-provider" && saved.accepted.document)
    saved.accepted.document.provider = "other";
  const { client } = mount([saved]);
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(listBrokerMonths).toHaveBeenCalledWith(12, expect.any(AbortSignal));
  expect(screen.queryByRole("heading", { name: heading })).toBeNull();
});

it("never merges competing sources and lets the user select their exact receipt", async () => {
  const second = makeCapitalDraft();
  second.request_id = "synthetic-competing";
  second.exceptions = ["position_snapshot_conflict"];
  if (second.accepted.document) second.accepted.document.positions[0].ending_value = "5555.55";
  mount([makeCapitalDraft(), second]);
  fireEvent.change(await screen.findByLabelText("Исходная выписка черновика"), {
    target: { value: second.request_id },
  });
  expect(screen.getByText("5 555,55 ₽")).toBeVisible();
  expect(screen.queryByText("1 234,56 ₽")).toBeNull();
  expect(screen.getByText("position_snapshot_conflict")).toBeVisible();
});

it("hides cached facts during refresh and after failed or withdrawn source GET", async () => {
  const { client } = mount([makeCapitalDraft()]);
  await screen.findByRole("heading", { name: heading });
  let rejectRead: (error: Error) => void = () => {};
  vi.mocked(listBrokerMonths).mockImplementation(
    () =>
      new Promise((_, reject) => {
        rejectRead = reject;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Обновить DRAFT" }));
  await waitFor(() => expect(screen.queryByText("1 234,56 ₽")).toBeNull());
  rejectRead(new Error("Synthetic source unavailable"));
  await screen.findByRole("heading", { name: "Не удалось проверить DRAFT" });
  expect(screen.queryByText("789,01 ₽")).toBeNull();
  vi.mocked(listBrokerMonths).mockResolvedValue([]);
  await client.refetchQueries({ queryKey: ["broker-months", 12] });
  await waitFor(() => expect(screen.queryByRole("heading", { name: heading })).toBeNull());
});

it("allows explicit replacement when the selected receipt disappears and one compatible source remains", async () => {
  const selected = makeCapitalDraft();
  selected.request_id = "synthetic-withdrawn";
  if (selected.accepted.document) selected.accepted.document.positions[0].ending_value = "5555.55";
  mount([makeCapitalDraft(), selected]);
  fireEvent.change(await screen.findByLabelText("Исходная выписка черновика"), {
    target: { value: selected.request_id },
  });
  expect(screen.getByText("5 555,55 ₽")).toBeVisible();
  vi.mocked(listBrokerMonths).mockResolvedValue([makeCapitalDraft()]);
  fireEvent.click(screen.getByRole("button", { name: "Обновить DRAFT" }));
  await screen.findByText("Выбранная выписка DRAFT недоступна. Выбери другую исходную выписку.");
  expect(screen.queryByRole("table")).toBeNull();
  fireEvent.change(screen.getByLabelText("Исходная выписка черновика"), {
    target: { value: makeCapitalDraft().request_id },
  });
  expect(screen.getByText("1 234,56 ₽")).toBeVisible();
  expect(screen.queryByText("5 555,55 ₽")).toBeNull();
});

it("never implies zero inventory or cash from absent rows, or global Close readiness", async () => {
  const saved = makeCapitalDraft();
  saved.bookkeeping_ready = true;
  saved.exceptions = [];
  if (saved.accepted.document) {
    saved.accepted.document.positions = [];
    saved.accepted.document.rub_money = [];
  }
  mount([saved]);
  await screen.findByRole("heading", { name: heading });
  expect(screen.getByText(/не доказательство нулевой оценки/)).toBeVisible();
  expect(screen.getByText("RUB cash неизвестен.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
});

it("binds reads to the selected DRAFT month and discards it when that month becomes CLOSED", async () => {
  const client = createQueryClient();
  const newer = { ...uiV2Months[1], id: 13, month: 9, snapshot_date: "2031-09-30" };
  vi.mocked(listBrokerMonths).mockImplementation(async (monthId) => {
    const saved = makeCapitalDraft(3, monthId);
    if (monthId === 13 && saved.accepted.document)
      saved.accepted.document.positions[0].ending_value = "7777.77";
    return [saved];
  });
  const tree = (months: ReportingMonth[]) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CapitalDraftValuation months={months} accounts={accounts} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(tree([uiV2Months[1], newer]));
  await screen.findByText("1 234,56 ₽");
  fireEvent.change(screen.getByLabelText("Месяц DRAFT"), { target: { value: "13" } });
  await screen.findByText("7 777,77 ₽");
  expect(screen.queryByText("1 234,56 ₽")).toBeNull();
  expect(listBrokerMonths).toHaveBeenCalledWith(13, expect.any(AbortSignal));
  view.rerender(tree([uiV2Months[1], { ...newer, status: "closed" }]));
  await screen.findByText("1 234,56 ₽");
  expect(screen.queryByText("7 777,77 ₽")).toBeNull();
});
