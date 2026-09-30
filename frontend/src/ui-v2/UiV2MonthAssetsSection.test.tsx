import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { createAccount, listAccounts } from "../api/accounts";
import {
  createCashBalance,
  deleteCashBalance,
  getCashTotal,
  listCashBalances,
  updateCashBalance,
} from "../api/cash";
import { getDashboard } from "../api/dashboard";
import { createDeposit, deleteDeposit, listDeposits, updateDeposit } from "../api/deposits";
import { listDebts } from "../api/debts";
import type {
  Account,
  CashBalance,
  CashTotal,
  DashboardSlice,
  DebtEntry,
  DepositCreate,
  DepositSnapshot,
  MoneyValue,
  ReportingMonth,
} from "../api/types";
import { createQueryClient } from "../queryClient";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { UiV2MonthAssetsSection } from "./UiV2MonthAssetsSection";

vi.mock("../api/accounts", () => ({
  listAccounts: vi.fn(),
  createAccount: vi.fn(),
}));
vi.mock("../api/cash", () => ({
  listCashBalances: vi.fn(),
  getCashTotal: vi.fn(),
  createCashBalance: vi.fn(),
  updateCashBalance: vi.fn(),
  deleteCashBalance: vi.fn(),
}));
vi.mock("../api/deposits", () => ({
  listDeposits: vi.fn(),
  createDeposit: vi.fn(),
  updateDeposit: vi.fn(),
  deleteDeposit: vi.fn(),
}));
vi.mock("../api/debts", () => ({ listDebts: vi.fn() }));
vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));

const monthDraft: ReportingMonth = {
  id: 7,
  year: 2031,
  month: 1,
  status: "draft",
  snapshot_date: "2031-01-31",
  source: "manual",
};

const monthNext: ReportingMonth = {
  id: 8,
  year: 2031,
  month: 2,
  status: "draft",
  snapshot_date: "2031-02-28",
  source: "alfa_pdf",
};

const monthClosed: ReportingMonth = { ...monthDraft, status: "closed", source: "excel_migration" };

const depositAccount: Account = {
  id: 11,
  name: "Депозиты",
  account_type: "deposit",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const deposit: DepositSnapshot = {
  id: 21,
  reporting_month_id: 7,
  account_id: 11,
  name: "Вклад Альфа",
  deposit_type: "deposit",
  balance: { amount: "100000.00", currency: "RUB" },
  annual_rate: "12.00",
  expected_monthly_interest: { amount: "1000.00", currency: "RUB" },
  actual_interest_received: { amount: "900.00", currency: "RUB" },
  notes: null,
  updated_at: "2031-01-31T00:00:00",
};

const cashRow: CashBalance = {
  id: 41,
  reporting_month_id: 7,
  account_id: null,
  name: "Кошелёк",
  amount: { amount: "5000.00", currency: "RUB" },
  currency: "RUB",
  include_in_capital: true,
  notes: null,
};

const linkedDebt: DebtEntry = {
  id: 31,
  reporting_month_id: 7,
  debt_type: "credit_card",
  name: "Карта для вклада",
  current_balance: { amount: "30000.00", currency: "RUB" },
  include_in_liquid_capital: true,
  linked_account_id: 11,
  annual_rate: null,
  next_due_date: null,
  contract_end_date: null,
  notes: null,
};

const dashboardFixture = {
  mortgage: null,
  summary: {
    liquid_capital: {
      linked_pairs: [
        {
          debt_id: 31,
          debt_name: "Карта для вклада",
          debt_type: "credit_card",
          debt_balance: { amount: "30000.00", currency: "RUB" },
          account_id: 11,
          account_name: "Депозиты",
          account_type: "deposit",
          account_balance: { amount: "100000.00", currency: "RUB" },
          net_contribution: { amount: "70000.00", currency: "RUB" },
        },
      ],
    },
  },
} as unknown as DashboardSlice;

let deposits: DepositSnapshot[];
let cashRows: CashBalance[];
let cashTotal: CashTotal;

function money(amount: string, currency = "RUB"): MoneyValue {
  return { amount, currency };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function makeDeposit(payload: DepositCreate, id: number): DepositSnapshot {
  return {
    id,
    reporting_month_id: payload.reporting_month_id,
    account_id: payload.account_id,
    name: payload.name,
    deposit_type: payload.deposit_type,
    balance: payload.balance,
    annual_rate: payload.annual_rate,
    expected_monthly_interest: money("0.00"),
    actual_interest_received: payload.actual_interest_received ?? money("0.00"),
    notes: null,
    updated_at: "2031-01-31T05:00:00",
  };
}

function seedDepositMutations() {
  vi.mocked(createDeposit).mockImplementation(async (payload) => {
    const created = makeDeposit(payload, 901);
    deposits = [...deposits, created];
    return created;
  });
  vi.mocked(updateDeposit).mockImplementation(async (snapshotId, payload) => {
    deposits = deposits.map((row) =>
      row.id === snapshotId
        ? {
            ...row,
            name: payload.name ?? row.name,
            deposit_type: payload.deposit_type ?? row.deposit_type,
            balance: payload.balance ?? row.balance,
            annual_rate: payload.annual_rate ?? row.annual_rate,
            actual_interest_received:
              payload.actual_interest_received ?? row.actual_interest_received,
            updated_at: "2031-01-31T06:00:00",
          }
        : row,
    );
    const updated = deposits.find((row) => row.id === snapshotId);
    if (!updated) throw new Error("deposit not found");
    return updated;
  });
  vi.mocked(deleteDeposit).mockImplementation(async (snapshotId) => {
    deposits = deposits.filter((row) => row.id !== snapshotId);
  });
}

function seedCashMutations() {
  vi.mocked(createCashBalance).mockImplementation(async (payload) => {
    const created: CashBalance = {
      id: 902,
      reporting_month_id: payload.reporting_month_id,
      account_id: null,
      name: payload.name,
      amount: payload.amount,
      currency: "RUB",
      include_in_capital: payload.include_in_capital ?? true,
      notes: null,
    };
    cashRows = [...cashRows, created];
    return created;
  });
  vi.mocked(updateCashBalance).mockImplementation(async (balanceId, payload) => {
    cashRows = cashRows.map((row) => (row.id === balanceId ? { ...row, ...payload } : row));
    const updated = cashRows.find((row) => row.id === balanceId);
    if (!updated) throw new Error("cash balance not found");
    return updated;
  });
  vi.mocked(deleteCashBalance).mockImplementation(async (balanceId) => {
    cashRows = cashRows.filter((row) => row.id !== balanceId);
  });
}

/**
 * Actual backend rounding evidence — `PercentageRate.from_api` → basis points
 * with ROUND_HALF_UP → `to_api()` with two decimals. Sources:
 * `tests/domain/test_values.py` ("13.50"→1350bp, "13.505"→1351bp,
 * "-0.005"→-1bp, rejects ""/"not-rate"/"1,25"/NaN/Infinity/floats) and
 * `tests/test_scenario_lab_deposit_rate.py` ("12"→1200bp→"12.00",
 * "12.3"→1230bp→"12.30", "12.345"→1235bp→"12.35").
 */
const BACKEND_RATE_ECHO: Record<string, string> = {
  "12": "12.00",
  "12.3": "12.30",
  "12.345": "12.35",
  "13.505": "13.51",
};

function backendRateEcho(rate: string): string {
  return BACKEND_RATE_ECHO[rate] ?? rate;
}

/** Create mock whose annual_rate comes back exactly as the backend echoes it. */
function seedBackendEchoCreates(echo: (rate: string) => string = backendRateEcho) {
  vi.mocked(createDeposit).mockImplementation(async (payload) => {
    const created: DepositSnapshot = {
      ...makeDeposit(payload, 909),
      annual_rate: echo(payload.annual_rate),
    };
    deposits = [...deposits, created];
    return created;
  });
}

/** Update mock whose annual_rate comes back exactly as the backend echoes it. */
function seedBackendEchoUpdates(echo: (rate: string) => string = backendRateEcho) {
  vi.mocked(updateDeposit).mockImplementation(async (snapshotId, payload) => {
    deposits = deposits.map((row) =>
      row.id === snapshotId
        ? {
            ...row,
            name: payload.name ?? row.name,
            deposit_type: payload.deposit_type ?? row.deposit_type,
            balance: payload.balance ?? row.balance,
            annual_rate: echo(payload.annual_rate ?? row.annual_rate),
            actual_interest_received:
              payload.actual_interest_received ?? row.actual_interest_received,
            updated_at: "2031-01-31T07:00:00",
          }
        : row,
    );
    const updated = deposits.find((row) => row.id === snapshotId);
    if (!updated) throw new Error("deposit not found");
    return updated;
  });
}

type DirtySpy = Mock<(section: string, dirty: boolean) => void>;

function contextFor(
  month: ReportingMonth,
  setDirty: DirtySpy,
  readOnly = month.status === "closed",
): MonthEditorContext {
  return {
    month,
    readOnly,
    refresh: vi.fn(async () => month),
    setDirty,
    returnToClose: null,
  };
}

function sectionElement(client: QueryClient, context: MonthEditorContext) {
  return (
    <QueryClientProvider client={client}>
      <UiV2MonthAssetsSection context={context} />
    </QueryClientProvider>
  );
}

function setup(options: { month?: ReportingMonth; readOnly?: boolean } = {}) {
  const month = options.month ?? monthDraft;
  const client = createQueryClient();
  const setDirty = vi.fn<(section: string, dirty: boolean) => void>();
  const context = contextFor(month, setDirty, options.readOnly);
  const view = render(sectionElement(client, context));
  return {
    client,
    setDirty,
    context,
    unmount: view.unmount,
    rerender(next: MonthEditorContext) {
      view.rerender(sectionElement(client, next));
    },
  };
}

async function tables() {
  return screen.findAllByRole("table");
}

describe("UiV2MonthAssetsSection", () => {
  beforeEach(() => {
    deposits = [deposit];
    cashRows = [cashRow];
    cashTotal = {
      reporting_month_id: 7,
      total: money("5000.00"),
      total_in_capital: money("5000.00"),
    };
    vi.mocked(listAccounts)
      .mockReset()
      .mockImplementation(async () => [depositAccount]);
    vi.mocked(listDeposits)
      .mockReset()
      .mockImplementation(async (monthId) =>
        deposits.filter((row) => row.reporting_month_id === monthId),
      );
    vi.mocked(listCashBalances)
      .mockReset()
      .mockImplementation(async (monthId) =>
        cashRows.filter((row) => row.reporting_month_id === monthId),
      );
    vi.mocked(getCashTotal)
      .mockReset()
      .mockImplementation(async () => ({ ...cashTotal }));
    vi.mocked(listDebts)
      .mockReset()
      .mockImplementation(async () => [linkedDebt]);
    vi.mocked(getDashboard)
      .mockReset()
      .mockImplementation(async () => dashboardFixture);
    vi.mocked(createAccount)
      .mockReset()
      .mockImplementation(async (payload) => ({
        id: 12,
        name: payload.name,
        account_type: payload.account_type,
        status: payload.status ?? "active",
        external_code: payload.external_code ?? null,
        include_in_capital: payload.include_in_capital ?? true,
        include_in_returns: payload.include_in_returns ?? true,
        notes: payload.notes ?? null,
      }));
    vi.mocked(createDeposit).mockReset();
    vi.mocked(updateDeposit).mockReset();
    vi.mocked(deleteDeposit).mockReset();
    vi.mocked(createCashBalance).mockReset();
    vi.mocked(updateCashBalance).mockReset();
    vi.mocked(deleteCashBalance).mockReset();
  });

  it("shows source/snapshot metadata, API money and the canonical linked-pair context", async () => {
    setup();

    const meta = await screen.findByTestId("month-assets-meta");
    expect(meta).toHaveTextContent("Источник: Вручную");
    expect(meta).toHaveTextContent("Снимок: 31.01.2031");
    expect(meta).toHaveTextContent("Январь 2031");
    expect(meta).toHaveTextContent("Черновик");
    expect(meta).toHaveTextContent("API выбранного месяца");

    const rendered = await tables();
    expect(rendered[0]).toHaveTextContent("Вклад Альфа");
    expect(rendered[0]).toHaveTextContent(/100\s*000\s*₽/);
    expect(rendered[1]).toHaveTextContent("Кошелёк");
    expect(screen.getAllByText("5 000 ₽").length).toBeGreaterThan(0);

    const pair = await screen.findByTestId("linked-pair-31");
    expect(pair).toHaveTextContent("Депозиты");
    expect(pair).toHaveTextContent("Карта для вклада");
    expect(pair).toHaveTextContent("Актив A · брутто");
    expect(pair).toHaveTextContent("Связанный долг D");
    expect(pair).toHaveTextContent("Чистый вклад A − D");
    expect(pair).toHaveTextContent(/70\s*000\s*₽/);
  });

  it("renders an empty snapshot date as provided instead of inventing one", async () => {
    setup({ month: { ...monthDraft, snapshot_date: "" } });
    const meta = await screen.findByTestId("month-assets-meta");
    expect(meta).toHaveTextContent("Снимок: —");
  });

  it("round-trips a deposit create with readback confirmation and dirty sync", async () => {
    deposits = [];
    seedDepositMutations();
    const { setDirty } = setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Вклад Тинькофф");
    await user.type(screen.getByLabelText("Баланс вклада"), "15000.50");
    expect(setDirty).toHaveBeenCalledWith("assets", true);

    await user.click(submit);
    await screen.findByText(/Вклад «Вклад Тинькофф» сохранён; данные перечитаны/);

    expect(createDeposit).toHaveBeenCalledTimes(1);
    expect(vi.mocked(createDeposit).mock.calls[0][0]).toEqual({
      reporting_month_id: 7,
      account_id: 11,
      name: "Вклад Тинькофф",
      deposit_type: "deposit",
      balance: { amount: "15000.50", currency: "RUB" },
      annual_rate: "12.00",
      actual_interest_received: { amount: "0.00", currency: "RUB" },
    });
    expect(screen.getByText("Вклад Тинькофф")).toBeInTheDocument();
    await waitFor(() => expect(setDirty).toHaveBeenCalledWith("assets", false));
  });

  it("round-trips a savings-type deposit", async () => {
    deposits = [];
    seedDepositMutations();
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Накопления А");
    await user.selectOptions(screen.getByLabelText("Тип"), "savings");
    await user.type(screen.getByLabelText("Баланс вклада"), "2000");
    await user.click(submit);
    await screen.findByText(/Накопления А» сохранён/);

    expect(vi.mocked(createDeposit).mock.calls[0][0]).toMatchObject({
      deposit_type: "savings",
      balance: { amount: "2000.00", currency: "RUB" },
    });
  });

  it("round-trips a cash position create and rereads API totals", async () => {
    seedCashMutations();
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить денежную позицию" });
    await user.type(screen.getByLabelText("Название денежной позиции"), "Копилка");
    await user.type(screen.getByLabelText("Сумма наличных"), "2500");
    await user.click(submit);
    await screen.findByText(/Денежная позиция «Копилка» сохранена; данные перечитаны/);

    expect(vi.mocked(createCashBalance).mock.calls[0][0]).toEqual({
      reporting_month_id: 7,
      name: "Копилка",
      amount: { amount: "2500.00", currency: "RUB" },
      include_in_capital: true,
    });
    expect(screen.getByText("Копилка")).toBeInTheDocument();
    expect(vi.mocked(getCashTotal).mock.calls.length).toBeGreaterThan(1);
  });

  it("edits a deposit with optimistic concurrency and confirms via readback", async () => {
    seedDepositMutations();
    setup();
    const user = userEvent.setup();

    await tables();
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));

    expect(screen.getByDisplayValue("Вклад Альфа")).toBeInTheDocument();
    const balance = screen.getByDisplayValue("100000.00");
    await user.clear(balance);
    await user.type(balance, "110000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await screen.findByText(/Вклад «Вклад Альфа» сохранён; данные перечитаны/);

    expect(vi.mocked(updateDeposit).mock.calls[0]).toEqual([
      21,
      {
        name: "Вклад Альфа",
        deposit_type: "deposit",
        balance: { amount: "110000.00", currency: "RUB" },
        annual_rate: "12.00",
        actual_interest_received: { amount: "900.00", currency: "RUB" },
      },
      "2031-01-31T00:00:00",
    ]);
    const rendered = await tables();
    expect(rendered[0]).toHaveTextContent(/110\s*000\s*₽/);
  });

  it("deletes a deposit only through the confirmed overflow path", async () => {
    seedDepositMutations();
    setup();
    const user = userEvent.setup();

    await tables();
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить вклад?" });
    expect(dialog).toHaveTextContent("Вклад Альфа");

    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await screen.findByText(/Вклад «Вклад Альфа» удалён; данные перечитаны/);

    expect(deleteDeposit).toHaveBeenCalledTimes(1);
    expect(deleteDeposit).toHaveBeenCalledWith(21);
    expect(screen.queryByText("Вклад Альфа")).not.toBeInTheDocument();
  });

  it("toggles capital inclusion with readback confirmation", async () => {
    seedCashMutations();
    setup();
    const user = userEvent.setup();

    await screen.findByText("Кошелёк");
    await user.click(screen.getByRole("button", { name: "да" }));
    await screen.findByText(/«Кошелёк»: исключена из ликвидного капитала/);

    expect(vi.mocked(updateCashBalance).mock.calls[0]).toEqual([41, { include_in_capital: false }]);
    expect(screen.getByRole("button", { name: "нет" })).toBeInTheDocument();
  });

  it("deletes a cash position behind confirmation", async () => {
    seedCashMutations();
    setup();
    const user = userEvent.setup();

    await screen.findByText("Кошелёк");
    await user.click(
      screen.getByRole("button", { name: "Действия для денежной позиции «Кошелёк»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить денежную позицию?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await screen.findByText(/Денежная позиция «Кошелёк» удалена/);

    expect(deleteCashBalance).toHaveBeenCalledWith(41);
    expect(screen.queryByText("Кошелёк")).not.toBeInTheDocument();
  });

  it("keeps a failed cash total unavailable instead of showing zero", async () => {
    vi.mocked(getCashTotal).mockImplementation(async () => {
      throw new Error("снимок недоступен");
    });
    setup();

    await tables();
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);
    expect(screen.getByText(/Итоги наличных за выбранный месяц недоступны/)).toBeInTheDocument();
    expect(screen.queryAllByText(/^0\s?₽$/)).toHaveLength(0);
  });

  it("rejects a cash total that belongs to another month", async () => {
    cashTotal = { ...cashTotal, reporting_month_id: 8 };
    setup();

    await tables();
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);
    expect(screen.queryAllByText(/^0\s?₽$/)).toHaveLength(0);
  });

  it("shows a genuine zero total returned by the API", async () => {
    cashRows = [];
    cashTotal = {
      reporting_month_id: 7,
      total: money("0.00"),
      total_in_capital: money("0.00"),
    };
    setup();

    await tables();
    expect(screen.getAllByText("0 ₽")).toHaveLength(2);
    expect(screen.queryByText("Недоступно")).not.toBeInTheDocument();
  });

  it("shows API currencies and never turns a malformed amount into a number", async () => {
    deposits = [
      {
        ...deposit,
        id: 31,
        name: "Вклад в долларах",
        balance: money("500.00", "USD"),
        expected_monthly_interest: money("5.00", "USD"),
        actual_interest_received: money("повреждено", "RUB"),
      },
      deposit,
    ];
    cashRows = [{ ...cashRow, currency: "USD", amount: money("75.00", "USD") }];
    setup();

    const rendered = await tables();
    expect(rendered[0]).toHaveTextContent(/500\s*USD/);
    expect(rendered[1]).toHaveTextContent(/75\s*USD/);
    expect(screen.getByText(/^Получено:/)).toHaveTextContent("—");
    expect(screen.getByText(/Строки в разных валютах/)).toBeInTheDocument();
  });

  it("reports a failed create without claiming a save and allows a retry", async () => {
    deposits = [];
    seedDepositMutations();
    vi.mocked(createDeposit).mockImplementationOnce(async () => {
      throw new Error("Сервер недоступен");
    });
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Вклад Рисковый");
    await user.type(screen.getByLabelText("Баланс вклада"), "100");

    await user.click(submit);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Сервер недоступен");
    expect(screen.queryByText(/сохранён/)).not.toBeInTheDocument();

    await user.click(submit);
    await screen.findByText(/Вклад «Вклад Рисковый» сохранён/);
    expect(createDeposit).toHaveBeenCalledTimes(2);
  });

  it("does not create a duplicate on a repeated submit", async () => {
    deposits = [];
    const gate = deferred<void>();
    seedDepositMutations();
    vi.mocked(createDeposit).mockImplementationOnce(async (payload) => {
      const created = makeDeposit(payload, 904);
      await gate.promise;
      deposits = [...deposits, created];
      return created;
    });
    setup();
    const user = userEvent.setup();

    await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Вклад Один");
    await user.type(screen.getByLabelText("Баланс вклада"), "1000");
    const form = screen
      .getByRole("button", { name: "Добавить вклад" })
      .closest("form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => expect(createDeposit).toHaveBeenCalledTimes(1));
    gate.resolve();
    await screen.findByText(/Вклад «Вклад Один» сохранён/);
    expect(createDeposit).toHaveBeenCalledTimes(1);
  });

  it("switches to the exact month and ignores a late response", async () => {
    deposits = [deposit, { ...deposit, id: 22, reporting_month_id: 8, name: "Вклад Февральский" }];
    cashRows = [
      cashRow,
      { ...cashRow, id: 42, reporting_month_id: 8, name: "Февральский кошелёк" },
    ];
    const gate = deferred<void>();
    vi.mocked(createDeposit).mockImplementationOnce(async (payload) => {
      const created = makeDeposit(payload, 905);
      await gate.promise;
      deposits = [...deposits, created];
      return created;
    });

    const { rerender, setDirty } = setup();
    const user = userEvent.setup();

    await screen.findByText("Вклад Альфа");
    expect(screen.queryByText("Вклад Февральский")).not.toBeInTheDocument();
    expect(screen.queryByText("Февральский кошелёк")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Название вклада"), "Вклад Поздний");
    await user.type(screen.getByLabelText("Баланс вклада"), "777");
    await user.click(screen.getByRole("button", { name: "Добавить вклад" }));
    await waitFor(() => expect(createDeposit).toHaveBeenCalledTimes(1));

    rerender(contextFor(monthNext, setDirty));
    await screen.findByText("Вклад Февральский");
    expect(listDeposits).toHaveBeenCalledWith(8, expect.anything());
    expect(screen.queryByText("Вклад Альфа")).not.toBeInTheDocument();
    expect(screen.queryByText("Кошелёк")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("Вклад Поздний")).not.toBeInTheDocument();
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);

    gate.resolve();
    await new Promise((done) => setTimeout(done, 20));
    expect(screen.queryByText(/Вклад «Вклад Поздний» сохранён/)).not.toBeInTheDocument();
    expect(screen.queryByText("Вклад Поздний")).not.toBeInTheDocument();
    expect(screen.getByText("Вклад Февральский")).toBeInTheDocument();
  });

  it("blocks every mutation while the month is closed and reopens in place", async () => {
    const { rerender, setDirty } = setup({ month: monthClosed });
    const user = userEvent.setup();

    await tables();
    const meta = await screen.findByTestId("month-assets-meta");
    expect(meta).toHaveTextContent("Закрыт");
    expect(meta).toHaveTextContent("Месяц закрыт");
    expect(screen.queryByRole("button", { name: "Добавить вклад" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Добавить денежную позицию" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "да" })).toBeDisabled();

    rerender(contextFor(monthDraft, setDirty, false));
    seedDepositMutations();
    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Вклад После Reopen");
    await user.type(screen.getByLabelText("Баланс вклада"), "42");
    await user.click(submit);
    await screen.findByText(/Вклад «Вклад После Reopen» сохранён/);
    expect(createDeposit).toHaveBeenCalledTimes(1);
  });

  it("shows an error block instead of zeros when assets cannot be loaded", async () => {
    vi.mocked(listDeposits).mockImplementation(async () => {
      throw new Error("Список недоступен");
    });
    setup();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить активы");
    expect(alert).toHaveTextContent("Список недоступен");
    expect(screen.queryAllByText(/^0\s?₽$/)).toHaveLength(0);
  });

  it("marks the section dirty while editing and clears it on unmount", async () => {
    const { setDirty, unmount } = setup();
    const user = userEvent.setup();

    await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Черновик");
    expect(setDirty).toHaveBeenCalledWith("assets", true);

    unmount();
    expect(setDirty).toHaveBeenLastCalledWith("assets", false);
  });

  // ——— Integrator B1: aggregate authority after a failed total readback ———

  it("never presents a pre-write cash total as current after a failed aggregate readback", async () => {
    seedCashMutations();
    cashTotal = {
      reporting_month_id: 7,
      total: money("12345.00"),
      total_in_capital: money("12345.00"),
    };
    let reads = 0;
    vi.mocked(getCashTotal).mockImplementation(async () => {
      reads += 1;
      if (reads === 1) return { ...cashTotal };
      if (reads === 2) throw new Error("агрегат недоступен");
      return {
        reporting_month_id: 7,
        total: money("14845.00"),
        total_in_capital: money("14845.00"),
      };
    });
    setup();
    const user = userEvent.setup();

    await screen.findByText("Кошелёк");
    expect(screen.getAllByText("12 345 ₽")).toHaveLength(2);

    await user.type(screen.getByLabelText("Название денежной позиции"), "Копилка");
    await user.type(screen.getByLabelText("Сумма наличных"), "2500");
    await user.click(screen.getByRole("button", { name: "Добавить денежную позицию" }));

    // Строки подтверждены перечитыванием списка…
    await screen.findByText(/Денежная позиция «Копилка» сохранена; данные перечитаны/);
    // …но итог не перечитан: старое значение не показывается как текущее.
    await screen.findByText(/Итог наличных не перечитан/);
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);
    expect(screen.queryByText("12 345 ₽")).not.toBeInTheDocument();
    expect(screen.getByText("Копилка")).toBeInTheDocument();

    // Восстановление: сервер снова отдаёт итог, повтор подтверждает его.
    await user.click(screen.getByRole("button", { name: "Повторить чтение итога" }));
    await waitFor(() => expect(screen.getAllByText("14 845 ₽")).toHaveLength(2));
    expect(screen.queryByText(/Итог наличных не перечитан/)).not.toBeInTheDocument();
    expect(screen.queryByText("Недоступно")).not.toBeInTheDocument();
    expect(reads).toBe(3);
  });

  it("keeps the aggregate unconfirmed when a capital toggle cannot refresh the total", async () => {
    seedCashMutations();
    cashTotal = {
      reporting_month_id: 7,
      total: money("9000.00"),
      total_in_capital: money("9000.00"),
    };
    let reads = 0;
    vi.mocked(getCashTotal).mockImplementation(async () => {
      reads += 1;
      if (reads === 1) return { ...cashTotal };
      throw new Error("итог не перечитан");
    });
    setup();
    const user = userEvent.setup();

    await screen.findByText("Кошелёк");
    expect(screen.getAllByText("9 000 ₽")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "да" }));
    await screen.findByText(/«Кошелёк»: исключена из ликвидного капитала/);
    await screen.findByText(/Итог наличных не перечитан/);
    expect(screen.getAllByText("Недоступно")).toHaveLength(2);
    expect(screen.queryByText("9 000 ₽")).not.toBeInTheDocument();
    expect(reads).toBe(2);
  });

  // ——— Integrator B2: foreign-month responses are rejected, not filtered ———

  it("rejects an initial deposit list that belongs to another month", async () => {
    vi.mocked(listDeposits).mockImplementation(async () => [
      { ...deposit, id: 55, reporting_month_id: 8, name: "Чужой вклад" },
    ]);
    setup();

    await screen.findByText(/Ответ API по вкладам принадлежит другому месяцу/);
    expect(screen.queryByText("Чужой вклад")).not.toBeInTheDocument();
    expect(screen.queryByText("Пусто")).not.toBeInTheDocument();
    expect(screen.queryAllByText(/^0\s?₽$/)).toHaveLength(0);
    expect(screen.getByText(/Баланс:/)).toHaveTextContent("—");
    // Отклонённый список не рендерится таблицей; таблица только у денежных средств.
    expect(await tables()).toHaveLength(1);
  });

  it("rejects an initial cash list that belongs to another month", async () => {
    vi.mocked(listCashBalances).mockImplementation(async () => [
      { ...cashRow, id: 56, reporting_month_id: 8, name: "Чужой кошелёк" },
    ]);
    setup();

    await screen.findByText(/Ответ API по денежным позициям принадлежит другому месяцу/);
    expect(screen.queryByText("Чужой кошелёк")).not.toBeInTheDocument();
    expect(screen.queryByText("Пусто")).not.toBeInTheDocument();
    expect(screen.queryAllByText(/^0\s?₽$/)).toHaveLength(0);
    // Отдельный месячный эндпоинт итога остаётся валидным для этого месяца.
    expect(screen.getAllByText("5 000 ₽").length).toBeGreaterThan(0);
    expect(await tables()).toHaveLength(1);
  });

  it("does not confirm a deposit deletion from a foreign-month readback", async () => {
    seedDepositMutations();
    vi.mocked(listDeposits).mockReset();
    vi.mocked(listDeposits).mockImplementationOnce(async (monthId) =>
      deposits.filter((row) => row.reporting_month_id === monthId),
    );
    vi.mocked(listDeposits).mockImplementation(async () => [
      { ...deposit, id: 77, reporting_month_id: 8, name: "Чужой вклад" },
    ]);
    setup();
    const user = userEvent.setup();

    await tables();
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить вклад?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await screen.findByText(/перечитывание не подтверждает выбранный снимок/);
    expect(deleteDeposit).toHaveBeenCalledWith(21);
    expect(screen.queryByText(/Вклад «Вклад Альфа» удалён/)).not.toBeInTheDocument();
    expect(screen.queryByText("Чужой вклад")).not.toBeInTheDocument();
    expect(screen.queryByText("Пусто")).not.toBeInTheDocument();
  });

  it("does not confirm a cash deletion from a foreign-month readback", async () => {
    seedCashMutations();
    vi.mocked(listCashBalances).mockReset();
    vi.mocked(listCashBalances).mockImplementationOnce(async (monthId) =>
      cashRows.filter((row) => row.reporting_month_id === monthId),
    );
    vi.mocked(listCashBalances).mockImplementation(async () => [
      { ...cashRow, id: 78, reporting_month_id: 8, name: "Чужой кошелёк" },
    ]);
    setup();
    const user = userEvent.setup();

    await screen.findByText("Кошелёк");
    await user.click(
      screen.getByRole("button", { name: "Действия для денежной позиции «Кошелёк»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Удалить денежную позицию?" });
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await screen.findByText(/перечитывание не подтверждает выбранный снимок/);
    expect(deleteCashBalance).toHaveBeenCalledWith(41);
    expect(screen.queryByText(/Денежная позиция «Кошелёк» удалена/)).not.toBeInTheDocument();
    expect(screen.queryByText("Чужой кошелёк")).not.toBeInTheDocument();
    expect(screen.queryByText("Пусто")).not.toBeInTheDocument();
  });

  // ——— Integrator B1 (5857697723): complete deposit write confirmation ———

  type UiScope = ReturnType<typeof within>;
  type User = ReturnType<typeof userEvent.setup>;

  function seedStaleUpdate(
    staleField: "annual_rate" | "deposit_type" | "actual_interest_received",
  ) {
    vi.mocked(updateDeposit).mockImplementation(async (snapshotId, payload) => {
      deposits = deposits.map((row) =>
        row.id === snapshotId
          ? {
              ...row,
              name: payload.name ?? row.name,
              deposit_type:
                staleField === "deposit_type"
                  ? row.deposit_type
                  : (payload.deposit_type ?? row.deposit_type),
              balance: payload.balance ?? row.balance,
              annual_rate:
                staleField === "annual_rate"
                  ? row.annual_rate
                  : (payload.annual_rate ?? row.annual_rate),
              actual_interest_received:
                staleField === "actual_interest_received"
                  ? row.actual_interest_received
                  : (payload.actual_interest_received ?? row.actual_interest_received),
              updated_at: "2031-01-31T06:00:00",
            }
          : row,
      );
      const updated = deposits.find((row) => row.id === snapshotId);
      if (!updated) throw new Error("deposit not found");
      return updated;
    });
  }

  const staleEditCases: Array<{
    scenario: string;
    stale: "annual_rate" | "deposit_type" | "actual_interest_received";
    mutate: (scope: UiScope, user: User) => Promise<void>;
    expectPreserved: (scope: UiScope) => void;
  }> = [
    {
      scenario: "rate-only",
      stale: "annual_rate",
      mutate: async (scope, user) => {
        const rate = scope.getByDisplayValue("12.00");
        await user.clear(rate);
        await user.type(rate, "13.50");
      },
      expectPreserved: (scope) => expect(scope.getByDisplayValue("13.50")).toBeInTheDocument(),
    },
    {
      scenario: "deposit-type-only",
      stale: "deposit_type",
      mutate: async (scope, user) => {
        await user.selectOptions(scope.getByRole("combobox"), "savings");
      },
      expectPreserved: (scope) => expect(scope.getByRole("combobox")).toHaveValue("savings"),
    },
    {
      scenario: "actual-interest-only",
      stale: "actual_interest_received",
      mutate: async (scope, user) => {
        const actual = scope.getByDisplayValue("900.00");
        await user.clear(actual);
        await user.type(actual, "1000");
      },
      expectPreserved: (scope) => expect(scope.getByDisplayValue("1000")).toBeInTheDocument(),
    },
  ];

  it.each(staleEditCases)(
    "keeps a $scenario deposit edit open when readback returns the stale row",
    async ({ stale, mutate, expectPreserved }) => {
      seedDepositMutations();
      seedStaleUpdate(stale);
      setup();
      const user = userEvent.setup();

      await tables();
      await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
      await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
      const editRow = screen.getByDisplayValue("Вклад Альфа").closest("tr") as HTMLElement;
      const scope = within(editRow);
      await mutate(scope, user);

      await user.click(scope.getByRole("button", { name: "OK" }));
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/Изменение вклада не подтверждено/);
      expect(screen.queryByText(/Вклад «Вклад Альфа» сохранён/)).not.toBeInTheDocument();

      // Новейший ввод сохранён в форме — повтор возможен после корректного readback.
      expectPreserved(scope);
      vi.mocked(updateDeposit).mockReset();
      seedDepositMutations();
      await user.click(scope.getByRole("button", { name: "OK" }));
      await screen.findByText(/Вклад «Вклад Альфа» сохранён; данные перечитаны/);
    },
  );

  // ——— Integrator B2 (5857697723): freeze controls during write + readback ———

  it("freezes the deposit create form until the deferred write is confirmed", async () => {
    deposits = [];
    seedDepositMutations();
    const gate = deferred<void>();
    vi.mocked(createDeposit).mockImplementationOnce(async (payload) => {
      await gate.promise;
      const created = makeDeposit(payload, 906);
      deposits = [...deposits, created];
      return created;
    });
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    const nameInput = screen.getByLabelText("Название вклада");
    const balanceInput = screen.getByLabelText("Баланс вклада");
    const typeSelect = screen.getByLabelText("Тип");
    await user.type(nameInput, "Вклад Отложенный");
    await user.type(balanceInput, "5000");
    await user.click(submit);

    await waitFor(() => expect(nameInput).toBeDisabled());
    expect(balanceInput).toBeDisabled();
    expect(typeSelect).toBeDisabled();
    expect(submit).toBeDisabled();
    // Черновик (в т.ч. новейший ввод) не выбрасывается во время записи.
    expect(nameInput).toHaveValue("Вклад Отложенный");
    expect(balanceInput).toHaveValue("5000");

    gate.resolve();
    await screen.findByText(/Вклад «Вклад Отложенный» сохранён; данные перечитаны/);
    expect(screen.getByText("Вклад Отложенный")).toBeInTheDocument();
    // Черновик очищается только после подтверждения, форма снова доступна.
    expect(nameInput).toHaveValue("");
    expect(nameInput).toBeEnabled();
  });

  it("freezes the cash create form until the deferred write is confirmed", async () => {
    seedCashMutations();
    const gate = deferred<void>();
    vi.mocked(createCashBalance).mockImplementationOnce(async (payload) => {
      await gate.promise;
      const created: CashBalance = {
        id: 907,
        reporting_month_id: payload.reporting_month_id,
        account_id: null,
        name: payload.name,
        amount: payload.amount,
        currency: "RUB",
        include_in_capital: payload.include_in_capital ?? true,
        notes: null,
      };
      cashRows = [...cashRows, created];
      return created;
    });
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить денежную позицию" });
    const nameInput = screen.getByLabelText("Название денежной позиции");
    const amountInput = screen.getByLabelText("Сумма наличных");
    const checkbox = screen.getByRole("checkbox", { name: "Включать в ликвидный капитал" });
    await user.type(nameInput, "Копилка");
    await user.type(amountInput, "700");
    await user.click(submit);

    await waitFor(() => expect(nameInput).toBeDisabled());
    expect(amountInput).toBeDisabled();
    expect(checkbox).toBeDisabled();
    expect(submit).toBeDisabled();
    // Черновик не выбрасывается во время записи.
    expect(nameInput).toHaveValue("Копилка");
    expect(amountInput).toHaveValue("700");

    gate.resolve();
    await screen.findByText(/Денежная позиция «Копилка» сохранена; данные перечитаны/);
    expect(screen.getByText("Копилка")).toBeInTheDocument();
    expect(nameInput).toHaveValue("");
    expect(nameInput).toBeEnabled();
  });

  it("freezes deposit edit controls until the deferred edit is confirmed", async () => {
    seedDepositMutations();
    const gate = deferred<void>();
    vi.mocked(updateDeposit).mockImplementationOnce(async (snapshotId, payload) => {
      await gate.promise;
      deposits = deposits.map((row) =>
        row.id === snapshotId ? { ...row, ...payload, updated_at: "2031-01-31T06:00:00" } : row,
      );
      const updated = deposits.find((row) => row.id === snapshotId);
      if (!updated) throw new Error("deposit not found");
      return updated;
    });
    setup();
    const user = userEvent.setup();

    await tables();
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const editRow = screen.getByDisplayValue("Вклад Альфа").closest("tr") as HTMLElement;
    const scope = within(editRow);
    const balance = scope.getByDisplayValue("100000.00");
    await user.clear(balance);
    await user.type(balance, "115000.00");
    await user.click(scope.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(scope.getByDisplayValue("Вклад Альфа")).toBeDisabled());
    expect(scope.getByDisplayValue("115000.00")).toBeDisabled();
    expect(scope.getByRole("combobox")).toBeDisabled();
    // Изменение остаётся в форме на время записи и readback.
    expect(scope.getByDisplayValue("115000.00")).toHaveValue("115000.00");

    gate.resolve();
    await screen.findByText(/Вклад «Вклад Альфа» сохранён; данные перечитаны/);
    expect(screen.queryByDisplayValue("115000.00")).not.toBeInTheDocument();
    expect(screen.queryByText(/Изменение вклада не подтверждено/)).not.toBeInTheDocument();
  });

  // ——— Integrator (5858294059): exact rate contract + create recovery ———

  it.each([
    { submitted: "12", echoed: "12.00" },
    { submitted: "12.345", echoed: "12.35" },
  ])(
    "confirms a create of rate $submitted against the backend-echoed $echoed row",
    async ({ submitted, echoed }) => {
      deposits = [];
      seedDepositMutations();
      seedBackendEchoCreates();
      setup();
      const user = userEvent.setup();

      const submit = await screen.findByRole("button", { name: "Добавить вклад" });
      await user.type(screen.getByLabelText("Название вклада"), "Вклад Ставка");
      await user.type(screen.getByLabelText("Баланс вклада"), "1000");
      const rate = screen.getByLabelText("Годовая ставка %");
      await user.clear(rate);
      await user.type(rate, submitted);
      await user.click(submit);

      await screen.findByText(/Вклад «Вклад Ставка» сохранён; данные перечитаны/);
      // Ставка уходит в API без клиентского округления (семантика не менялась).
      expect(vi.mocked(createDeposit).mock.calls[0][0].annual_rate).toBe(submitted);
      expect(screen.getByText(echoed)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it.each([
    { submitted: "12", echoed: "12.00" },
    { submitted: "12.345", echoed: "12.35" },
  ])(
    "confirms a rate-only edit $submitted against the backend-echoed $echoed row",
    async ({ submitted, echoed }) => {
      seedDepositMutations();
      seedBackendEchoUpdates();
      setup();
      const user = userEvent.setup();

      await tables();
      await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
      await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
      const editRow = screen.getByDisplayValue("Вклад Альфа").closest("tr") as HTMLElement;
      const scope = within(editRow);
      const rate = scope.getByDisplayValue("12.00");
      await user.clear(rate);
      await user.type(rate, submitted);
      await user.click(scope.getByRole("button", { name: "OK" }));

      await screen.findByText(/Вклад «Вклад Альфа» сохранён; данные перечитаны/);
      expect(vi.mocked(updateDeposit).mock.calls[0][1].annual_rate).toBe(submitted);
      expect(screen.getByText(echoed)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it.each(["12garbage", "NaN", "Infinity"])(
    "cannot confirm a create whose row echoes rate %s",
    async (rate) => {
      deposits = [];
      seedDepositMutations();
      // Изоляция контракта подтверждения: «backend» вернул строку как есть.
      seedBackendEchoCreates(() => rate);
      setup();
      const user = userEvent.setup();

      const submit = await screen.findByRole("button", { name: "Добавить вклад" });
      await user.type(screen.getByLabelText("Название вклада"), "Вклад Странная");
      await user.type(screen.getByLabelText("Баланс вклада"), "1000");
      const rateField = screen.getByLabelText("Годовая ставка %");
      await user.clear(rateField);
      await user.type(rateField, rate);
      await user.click(submit);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/Создание вклада не подтверждено/);
      expect(screen.queryByText(/сохранён; данные перечитаны/)).not.toBeInTheDocument();
      // Retained identity: кнопка переключается на read-only проверку.
      expect(createDeposit).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Проверить создание" })).toBeInTheDocument();
      // Черновик удержан.
      expect(screen.getByLabelText("Название вклада")).toHaveValue("Вклад Странная");
    },
  );

  it("recovers a successful create by retained identity without a duplicate POST", async () => {
    deposits = [];
    seedDepositMutations();
    let listCalls = 0;
    vi.mocked(listDeposits).mockImplementation(async (monthId) => {
      listCalls += 1;
      if (listCalls === 2) return []; // readback подтверждения не видит новую строку
      return deposits.filter((row) => row.reporting_month_id === monthId);
    });
    setup();
    const user = userEvent.setup();

    const submit = await screen.findByRole("button", { name: "Добавить вклад" });
    await user.type(screen.getByLabelText("Название вклада"), "Вклад Один");
    await user.type(screen.getByLabelText("Баланс вклада"), "5000");
    await user.click(submit);

    await screen.findByText(/Создание вклада не подтверждено/);
    expect(createDeposit).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Название вклада")).toHaveValue("Вклад Один");
    expect(screen.getByRole("button", { name: "Проверить создание" })).toBeInTheDocument();

    // Восстановление — только перечитывание по удержанному id, без второго POST.
    await user.click(screen.getByRole("button", { name: "Проверить создание" }));
    await screen.findByText(/Вклад «Вклад Один» сохранён; данные перечитаны/);
    expect(createDeposit).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Вклад Один")).toBeInTheDocument();
    expect(screen.getByLabelText("Название вклада")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Добавить вклад" })).toBeInTheDocument();
  });
});
