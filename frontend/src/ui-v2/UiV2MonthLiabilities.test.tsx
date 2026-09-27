import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { ApiClientError } from "../api/client";
import { getDashboard } from "../api/dashboard";
import {
  createDebt,
  deleteDebt,
  linkDebtToAccount,
  listDebts,
  unlinkDebtFromAccount,
  updateDebt,
} from "../api/debts";
import { createProperty, deleteProperty, listProperties, updateProperty } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import type { Account, DebtEntry, PropertySnapshot, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { MONTH_LIABILITIES_SECTION_ID, UiV2MonthLiabilities } from "./UiV2MonthLiabilities";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/debts", () => ({
  createDebt: vi.fn(),
  deleteDebt: vi.fn(),
  linkDebtToAccount: vi.fn(),
  listDebts: vi.fn(),
  unlinkDebtFromAccount: vi.fn(),
  updateDebt: vi.fn(),
}));
vi.mock("../api/properties", () => ({
  createProperty: vi.fn(),
  deleteProperty: vi.fn(),
  listProperties: vi.fn(),
  updateProperty: vi.fn(),
}));
vi.mock("../api/summary", () => ({ getMonthSummary: vi.fn() }));

const debt: DebtEntry = {
  id: 1,
  reporting_month_id: 7,
  debt_type: "credit_card",
  name: "Основная карта",
  current_balance: { amount: "123456.00", currency: "RUB" },
  include_in_liquid_capital: true,
  linked_account_id: null,
  annual_rate: "19.90",
  next_due_date: "2030-06-20",
  contract_end_date: null,
  notes: null,
};

const property: PropertySnapshot = {
  id: 2,
  reporting_month_id: 7,
  name: "Синтетическая квартира",
  estimated_value: { amount: "7000000.00", currency: "RUB" },
  mortgage_balance: { amount: "3000000.00", currency: "RUB" },
  monthly_payment: { amount: "50000.00", currency: "RUB" },
  mortgage_annual_rate: null,
  notes: null,
};

const account: Account = {
  id: 11,
  name: "Синтетический депозит",
  account_type: "deposit",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const alternateAccount: Account = { ...account, id: 12, name: "Синтетические наличные" };
const savingsAccount: Account = {
  ...account,
  id: 13,
  name: "Синтетический накопительный счёт",
  account_type: "savings",
};
const brokerageAccount: Account = {
  ...account,
  id: 14,
  name: "Синтетический брокерский счёт",
  account_type: "brokerage",
};
const iisAccount: Account = { ...account, id: 15, name: "Синтетический ИИС", account_type: "iis" };
const excludedSavingsAccount: Account = {
  ...savingsAccount,
  id: 16,
  name: "Синтетический исключённый счёт",
  include_in_capital: false,
};

let debtsByMonth = new Map<number, DebtEntry[]>();
let propertiesByMonth = new Map<number, PropertySnapshot[]>();
let nextDebtId = 100;
let nextPropertyId = 200;
let client: QueryClient;
let setDirty: Mock<(section: string, dirty: boolean) => void>;

function findDebt(id: number): DebtEntry {
  for (const rows of debtsByMonth.values()) {
    const row = rows.find((candidate) => candidate.id === id);
    if (row !== undefined) return row;
  }
  throw new Error(`debt ${id} is not in the store`);
}

function findProperty(id: number): PropertySnapshot {
  for (const rows of propertiesByMonth.values()) {
    const row = rows.find((candidate) => candidate.id === id);
    if (row !== undefined) return row;
  }
  throw new Error(`property ${id} is not in the store`);
}

function leaf(monthId: number, readOnly: boolean) {
  const month: ReportingMonth = {
    id: monthId,
    year: 2030,
    month: 4,
    status: readOnly ? "closed" : "draft",
    snapshot_date: "2030-04-30",
    source: "manual",
  };
  const context: MonthEditorContext = {
    month,
    readOnly,
    refresh: async () => month,
    setDirty,
    returnToClose: null,
  };
  return (
    <QueryClientProvider client={client}>
      <UiV2MonthLiabilities context={context} />
    </QueryClientProvider>
  );
}

function renderLeaf(monthId = 7, readOnly = false) {
  client = createQueryClient();
  return render(leaf(monthId, readOnly));
}

async function debtSection(): Promise<HTMLElement> {
  return await screen.findByRole("region", { name: "Долги месяца" });
}

async function propertySection(): Promise<HTMLElement> {
  return await screen.findByRole("region", { name: "Недвижимость месяца" });
}

async function tables(): Promise<HTMLElement[]> {
  return await screen.findAllByRole("table");
}

/** Value of a `label: <strong>…</strong>` totals line inside the given section. */
function labelledValue(container: HTMLElement, label: string): HTMLElement | null {
  const line = Array.from(container.querySelectorAll("span")).find((element) =>
    element.textContent?.trimStart().startsWith(label),
  );
  return line?.querySelector("strong") ?? null;
}

describe("UiV2MonthLiabilities leaf (#564)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    debtsByMonth = new Map([
      [7, [{ ...debt }]],
      [8, []],
    ]);
    propertiesByMonth = new Map([
      [7, [{ ...property }]],
      [8, []],
    ]);
    nextDebtId = 100;
    nextPropertyId = 200;
    setDirty = vi.fn();

    vi.mocked(listAccounts).mockResolvedValue([
      account,
      alternateAccount,
      savingsAccount,
      brokerageAccount,
      iisAccount,
      excludedSavingsAccount,
    ]);
    vi.mocked(listDebts).mockImplementation(async (monthId) =>
      (debtsByMonth.get(monthId) ?? []).map((row) => ({ ...row })),
    );
    vi.mocked(listProperties).mockImplementation(async (monthId) =>
      (propertiesByMonth.get(monthId) ?? []).map((row) => ({ ...row })),
    );
    vi.mocked(getDashboard).mockResolvedValue({ mortgage: null } as never);
    vi.mocked(getMonthSummary).mockResolvedValue({ coverage: { coverage_pct: null } } as never);

    vi.mocked(createDebt).mockImplementation(async (payload) => {
      const monthId = payload.reporting_month_id;
      const row: DebtEntry = {
        id: nextDebtId++,
        reporting_month_id: monthId,
        debt_type: payload.debt_type,
        name: payload.name,
        current_balance: payload.current_balance,
        include_in_liquid_capital: payload.include_in_liquid_capital ?? true,
        linked_account_id: null,
        annual_rate: payload.annual_rate ?? null,
        next_due_date: payload.next_due_date ?? null,
        contract_end_date: payload.contract_end_date ?? null,
        notes: null,
      };
      debtsByMonth.set(monthId, [...(debtsByMonth.get(monthId) ?? []), row]);
      return row;
    });
    vi.mocked(updateDebt).mockImplementation(async (id, payload) => {
      const row = findDebt(id);
      Object.assign(row, payload);
      return { ...row };
    });
    vi.mocked(deleteDebt).mockImplementation(async (id) => {
      for (const [monthId, rows] of debtsByMonth) {
        debtsByMonth.set(
          monthId,
          rows.filter((row) => row.id !== id),
        );
      }
    });
    vi.mocked(linkDebtToAccount).mockImplementation(async (id, accountId) => {
      const row = findDebt(id);
      row.linked_account_id = accountId;
      return { ...row };
    });
    vi.mocked(unlinkDebtFromAccount).mockImplementation(async (id) => {
      findDebt(id).linked_account_id = null;
    });

    vi.mocked(createProperty).mockImplementation(async (payload) => {
      const monthId = payload.reporting_month_id;
      const row: PropertySnapshot = {
        id: nextPropertyId++,
        reporting_month_id: monthId,
        name: payload.name,
        estimated_value: payload.estimated_value,
        mortgage_balance: payload.mortgage_balance,
        monthly_payment: payload.monthly_payment,
        mortgage_annual_rate: payload.mortgage_annual_rate ?? null,
        notes: null,
      };
      propertiesByMonth.set(monthId, [...(propertiesByMonth.get(monthId) ?? []), row]);
      return row;
    });
    vi.mocked(updateProperty).mockImplementation(async (id, payload) => {
      const row = findProperty(id);
      Object.assign(row, payload);
      return { ...row };
    });
    vi.mocked(deleteProperty).mockImplementation(async (id) => {
      for (const [monthId, rows] of propertiesByMonth) {
        propertiesByMonth.set(
          monthId,
          rows.filter((row) => row.id !== id),
        );
      }
    });
  });

  it("renders exact money, provenance labels, and month totals", async () => {
    renderLeaf();
    const [debtTable, propertyTable] = await tables();
    const month = await debtSection();

    expect(listDebts).toHaveBeenCalledWith(7, expect.anything());
    expect(listProperties).toHaveBeenCalledWith(7, expect.anything());

    expect(debtTable).toHaveTextContent(/123\s*456\s*₽/);
    expect(debtTable).toHaveTextContent("В капитале");
    expect(debtTable).toHaveTextContent(/19,90%/);
    expect(debtTable).toHaveTextContent(/20\.06\.2030/);
    expect(debtTable).toHaveTextContent("Не связано");
    expect(month).toHaveTextContent(/CC\s*123\s*456\s*₽/);
    expect(month).toHaveTextContent("Долг по кредитным картам:");
    expect(month).not.toHaveTextContent("Долгов нет.");

    expect(propertyTable).toHaveTextContent(/7\s*000\s*000\s*₽/);
    expect(propertyTable).toHaveTextContent("не указано");
    expect(propertyTable).not.toHaveTextContent(/0,00%/);
    const propertyBlock = await propertySection();
    expect(propertyBlock).toHaveTextContent(/RE\s*7\s*000\s*000\s*₽/);
    expect(propertyBlock).not.toHaveTextContent("Объектов нет.");
  });

  it("keeps a missing dashboard and summary as dashes instead of zeros", async () => {
    vi.mocked(getDashboard).mockRejectedValue(
      new ApiClientError(422, {
        code: "unprocessable",
        message: "linked account has no included cash or deposit fact for reporting month",
        details: [],
      }),
    );
    vi.mocked(getMonthSummary).mockRejectedValue(new Error("summary unavailable"));
    renderLeaf();

    const propertyBlock = await propertySection();
    expect(labelledValue(propertyBlock, "Покрытие ипотеки (ориентир):")).toHaveTextContent("—");
    expect(labelledValue(propertyBlock, "Недостаток покрытия:")).toHaveTextContent("—");
    expect(labelledValue(propertyBlock, "Покрытие обязательных расходов:")).toHaveTextContent("—");
    expect(await screen.findByText("Контекст пары недоступен")).toBeInTheDocument();
    expect(await tables()).toHaveLength(2);
  });

  it("creates a debt with an exact payload and confirms it through a canonical readback", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const month = await debtSection();

    await user.type(within(month).getByLabelText("Текущий баланс долга"), "100000.50");
    await user.click(within(month).getByRole("button", { name: "Добавить долг" }));

    await waitFor(() =>
      expect(createDebt).toHaveBeenCalledWith({
        reporting_month_id: 7,
        debt_type: "credit_card",
        name: "Кредитка",
        current_balance: { amount: "100000.50", currency: "RUB" },
        include_in_liquid_capital: true,
        annual_rate: null,
        next_due_date: null,
        contract_end_date: null,
      }),
    );
    expect(listDebts).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Кредитка")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("100000.50")).toBeNull();
  });

  it("rejects an invalid debt rate before any write", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const month = await debtSection();

    await user.type(within(month).getByLabelText("Текущий баланс долга"), "1000");
    await user.type(within(month).getByLabelText("Годовая ставка, % (пусто — неизвестно)"), "-1");
    await user.click(within(month).getByRole("button", { name: "Добавить долг" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ставка — неотрицательное число, пусто — неизвестно",
    );
    expect(createDebt).not.toHaveBeenCalled();
    expect(listDebts).toHaveBeenCalledTimes(1);
  });

  it("edits a debt through an exact payload and the confirmed readback", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    );
    const balance = screen.getByDisplayValue("123456.00");
    await user.clear(balance);
    await user.type(balance, "100000.00");
    await user.click(within(debtTable).getByRole("button", { name: "OK" }));

    await waitFor(() =>
      expect(updateDebt).toHaveBeenCalledWith(1, {
        debt_type: "credit_card",
        name: "Основная карта",
        current_balance: { amount: "100000.00", currency: "RUB" },
        include_in_liquid_capital: true,
        annual_rate: "19.90",
        next_due_date: "2030-06-20",
        contract_end_date: null,
      }),
    );
    expect(listDebts).toHaveBeenCalledTimes(2);
    const [debtTableAfter] = await tables();
    expect(debtTableAfter).toHaveTextContent(/100\s*000\s*₽/);
    expect(debtTableAfter).not.toHaveTextContent(/123\s*456\s*₽/);
    expect(within(debtTableAfter).queryByRole("button", { name: "OK" })).toBeNull();
  });

  it("keeps a cleared name visible as a validation error without a write", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    );
    await user.clear(screen.getByDisplayValue("Основная карта"));
    await user.click(within(debtTable).getByRole("button", { name: "OK" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Имя и баланс долга обязательны");
    expect(updateDebt).not.toHaveBeenCalled();
    expect(within(debtTable).getByRole("button", { name: "OK" })).toBeInTheDocument();
  });

  it("shows a rejected save and allows the same edit to be submitted again", async () => {
    const user = userEvent.setup();
    vi.mocked(updateDebt).mockRejectedValueOnce(new Error("save failed"));
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    );
    const balance = screen.getByDisplayValue("123456.00");
    await user.clear(balance);
    await user.type(balance, "100000.00");
    await user.click(within(debtTable).getByRole("button", { name: "OK" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("save failed");
    expect(within(debtTable).getByRole("button", { name: "OK" })).toBeInTheDocument();

    await user.click(within(debtTable).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(updateDebt).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).toBeNull();
    const [debtTableAfter] = await tables();
    expect(debtTableAfter).toHaveTextContent(/100\s*000\s*₽/);
  });

  it("sends a cleared debt rate as an explicit null", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    );
    await user.clear(screen.getByDisplayValue("19.90"));
    await user.click(within(debtTable).getByRole("button", { name: "OK" }));

    await waitFor(() =>
      expect(updateDebt).toHaveBeenCalledWith(1, expect.objectContaining({ annual_rate: null })),
    );
    const [debtTableAfter] = await tables();
    expect(debtTableAfter).toHaveTextContent("не указано");
    expect(debtTableAfter).not.toHaveTextContent(/19,90%/);
  });

  it("links a debt through the dedicated endpoint and confirms the readback", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(within(debtTable).getByRole("button", { name: "Связать счёт" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Счёт для связи с долгом «Основная карта»" }),
      "11",
    );
    await user.click(screen.getByRole("button", { name: "Сохранить связь" }));

    await waitFor(() => expect(linkDebtToAccount).toHaveBeenCalledWith(1, 11));
    expect(listDebts).toHaveBeenCalledTimes(2);
    const [debtTableAfter] = await tables();
    expect(within(debtTableAfter).getByText("Синтетический депозит")).toBeInTheDocument();
    expect(
      within(debtTableAfter).getByRole("button", { name: "Изменить связь" }),
    ).toBeInTheDocument();
    expect(within(debtTableAfter).getByRole("button", { name: "Отвязать" })).toBeInTheDocument();
  });

  it("offers only cash, deposit, and savings accounts that are included in capital", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(within(debtTable).getByRole("button", { name: "Связать счёт" }));
    const picker = screen.getByRole("combobox", {
      name: "Счёт для связи с долгом «Основная карта»",
    });

    expect(within(picker).getByRole("option", { name: /Синтетический депозит/ })).toBeEnabled();
    expect(within(picker).getByRole("option", { name: /Синтетические наличные/ })).toBeEnabled();
    expect(
      within(picker).getByRole("option", { name: /Синтетический накопительный счёт/ }),
    ).toBeEnabled();
    expect(within(picker).queryByRole("option", { name: /брокерский/i })).toBeNull();
    expect(within(picker).queryByRole("option", { name: /ИИС/i })).toBeNull();
    expect(within(picker).queryByRole("option", { name: /исключённый/i })).toBeNull();
  });

  it("disables linking and explains it when no eligible account exists", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      brokerageAccount,
      iisAccount,
      excludedSavingsAccount,
    ]);
    renderLeaf();
    const [debtTable] = await tables();

    expect(within(debtTable).getByRole("button", { name: "Связать счёт" })).toBeDisabled();
    expect(
      within(debtTable).getByText("Нет доступных счетов для связи", { exact: false }),
    ).toBeInTheDocument();
    expect(
      within(debtTable).queryByText("Связь доступна для кредитки", { exact: false }),
    ).toBeNull();
  });

  it("keeps an ineligible current relation visible but unavailable as a new choice", async () => {
    debtsByMonth.set(7, [{ ...debt, linked_account_id: brokerageAccount.id }]);
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    expect(within(debtTable).getByText("Синтетический брокерский счёт")).toBeInTheDocument();
    await user.click(within(debtTable).getByRole("button", { name: "Изменить связь" }));

    const picker = screen.getByRole("combobox", {
      name: "Счёт для связи с долгом «Основная карта»",
    });
    expect(within(picker).getByRole("option", { name: /брокерский/i })).toBeDisabled();
    expect(within(picker).getByRole("option", { name: /Синтетический депозит/ })).toBeEnabled();
    expect(
      within(debtTable).getByText("Текущая связь сохранена", { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить связь" })).toBeDisabled();
  });

  it("confirms unlink and updates the row only after the readback", async () => {
    debtsByMonth.set(7, [{ ...debt, linked_account_id: 11 }]);
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(within(debtTable).getByRole("button", { name: "Отвязать" }));
    const dialog = screen.getByRole("alertdialog", { name: "Отвязать счёт?" });
    expect(dialog).toHaveTextContent("Синтетический депозит");
    await user.click(within(dialog).getByRole("button", { name: "Отвязать" }));

    await waitFor(() => expect(unlinkDebtFromAccount).toHaveBeenCalledWith(1));
    expect(listDebts).toHaveBeenCalledTimes(2);
    const [debtTableAfter] = await tables();
    expect(within(debtTableAfter).getByText("Не связано")).toBeInTheDocument();
    expect(
      within(debtTableAfter).getByRole("button", { name: "Связать счёт" }),
    ).toBeInTheDocument();
  });

  it("confirms debt deletion and clears the row after the readback", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [debtTable] = await tables();

    await user.click(
      within(debtTable).getByRole("button", { name: "Удалить долг «Основная карта»" }),
    );
    const dialog = screen.getByRole("alertdialog", { name: "Удалить долг?" });
    expect(dialog).toHaveTextContent("Удалить долг «Основная карта»?");
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(deleteDebt).toHaveBeenCalledWith(1));
    const month = await debtSection();
    expect(month).toHaveTextContent("Долгов нет.");
    expect(screen.queryByText("Основная карта")).toBeNull();
  });

  it("validates a property edit before any write", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [, propertyTable] = await tables();

    await user.click(
      within(propertyTable).getByRole("button", {
        name: "Изменить объект «Синтетическая квартира»",
      }),
    );
    await user.clear(within(propertyTable).getByLabelText("Название объекта"));
    await user.click(within(propertyTable).getByRole("button", { name: "OK" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Заполни название, стоимость, остаток ипотеки и платёж",
    );
    expect(updateProperty).not.toHaveBeenCalled();

    await user.type(
      within(propertyTable).getByLabelText("Название объекта"),
      "Синтетическая квартира",
    );
    await user.type(within(propertyTable).getByLabelText("Годовая ставка ипотеки"), "-2");
    await user.click(within(propertyTable).getByRole("button", { name: "OK" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ставка ипотеки — неотрицательное число, пусто — неизвестно",
    );
    expect(updateProperty).not.toHaveBeenCalled();
  });

  it("edits a property through an exact payload and the confirmed readback", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const [, propertyTable] = await tables();

    await user.click(
      within(propertyTable).getByRole("button", {
        name: "Изменить объект «Синтетическая квартира»",
      }),
    );
    const mortgage = screen.getByDisplayValue("3000000.00");
    await user.clear(mortgage);
    await user.type(mortgage, "2900000.00");
    await user.click(within(propertyTable).getByRole("button", { name: "OK" }));

    await waitFor(() =>
      expect(updateProperty).toHaveBeenCalledWith(2, {
        name: "Синтетическая квартира",
        estimated_value: { amount: "7000000.00", currency: "RUB" },
        mortgage_balance: { amount: "2900000.00", currency: "RUB" },
        monthly_payment: { amount: "50000.00", currency: "RUB" },
        mortgage_annual_rate: null,
      }),
    );
    expect(listProperties).toHaveBeenCalledTimes(2);
    const [, propertyTableAfter] = await tables();
    expect(propertyTableAfter).toHaveTextContent(/2\s*900\s*000\s*₽/);
    expect(within(propertyTableAfter).queryByRole("button", { name: "OK" })).toBeNull();
  });

  it("stays read-only for a closed month", async () => {
    debtsByMonth.set(7, [{ ...debt, linked_account_id: 11 }]);
    renderLeaf(7, true);
    const [debtTable, propertyTable] = await tables();

    expect(screen.queryByRole("button", { name: "Добавить долг" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить объект" })).toBeNull();
    expect(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    ).toBeDisabled();
    expect(
      within(debtTable).getByRole("button", { name: "Удалить долг «Основная карта»" }),
    ).toBeDisabled();
    expect(within(debtTable).getByRole("button", { name: "Изменить связь" })).toBeDisabled();
    expect(within(debtTable).getByRole("button", { name: "Отвязать" })).toBeDisabled();
    expect(
      within(propertyTable).getByRole("button", {
        name: "Изменить объект «Синтетическая квартира»",
      }),
    ).toBeDisabled();
    expect(
      within(propertyTable).getByRole("button", {
        name: "Удалить объект «Синтетическая квартира»",
      }),
    ).toBeDisabled();
  });

  it("drops a response that lands only after another month was selected", async () => {
    let release: (() => void) | null = null;
    vi.mocked(createDebt).mockImplementation(
      (payload) =>
        new Promise<DebtEntry>((resolve) => {
          release = () => {
            const monthId = payload.reporting_month_id;
            const row: DebtEntry = {
              id: nextDebtId++,
              reporting_month_id: monthId,
              debt_type: payload.debt_type,
              name: payload.name,
              current_balance: payload.current_balance,
              include_in_liquid_capital: payload.include_in_liquid_capital ?? true,
              linked_account_id: null,
              annual_rate: payload.annual_rate ?? null,
              next_due_date: payload.next_due_date ?? null,
              contract_end_date: payload.contract_end_date ?? null,
              notes: null,
            };
            debtsByMonth.set(monthId, [...(debtsByMonth.get(monthId) ?? []), row]);
            resolve(row);
          };
        }),
    );

    const user = userEvent.setup();
    const view = renderLeaf(7);
    const month = await debtSection();
    await user.type(within(month).getByLabelText("Текущий баланс долга"), "100000.50");
    await user.click(within(month).getByRole("button", { name: "Добавить долг" }));
    await waitFor(() => expect(release).not.toBeNull());

    view.rerender(leaf(8, false));
    expect(await debtSection()).toHaveTextContent("Долгов нет.");
    expect(listDebts).toHaveBeenCalledWith(8, expect.anything());

    await act(async () => {
      release?.();
    });

    expect(screen.queryByRole("alert")).toBeNull();
    expect(await debtSection()).toHaveTextContent("Долгов нет.");
    expect(screen.queryByText("Кредитка")).toBeNull();
    expect(listDebts).toHaveBeenCalledTimes(3);
  });

  it("refuses a readback that belongs to another month", async () => {
    const user = userEvent.setup();
    renderLeaf();
    const month = await debtSection();

    vi.mocked(listDebts).mockResolvedValueOnce([
      { ...debt, id: 99, name: "Чужой месяц", reporting_month_id: 99 },
    ]);
    await user.type(within(month).getByLabelText("Текущий баланс долга"), "100000.50");
    await user.click(within(month).getByRole("button", { name: "Добавить долг" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Долг не подтверждён повторной загрузкой.",
    );
    expect(screen.queryByText("Кредитка")).toBeNull();
    expect(screen.getByText("Основная карта")).toBeInTheDocument();
  });

  it("shows a load failure notice and retries on demand", async () => {
    const user = userEvent.setup();
    vi.mocked(listDebts).mockRejectedValueOnce(new Error("network down"));
    renderLeaf();

    expect(await screen.findByText("Не удалось загрузить обязательства")).toBeInTheDocument();
    expect(screen.getByText("network down")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await debtSection()).toHaveTextContent("Основная карта");
    expect(screen.queryByText("Не удалось загрузить обязательства")).toBeNull();
  });

  it("reports section dirtiness while editing and clears it on unmount", async () => {
    expect(MONTH_LIABILITIES_SECTION_ID).toBe("liabilities");
    const user = userEvent.setup();
    const view = renderLeaf();
    const [debtTable] = await tables();

    await waitFor(() => expect(setDirty).toHaveBeenCalledWith("liabilities", false));
    await user.click(
      within(debtTable).getByRole("button", { name: "Изменить долг «Основная карта»" }),
    );
    await waitFor(() => expect(setDirty).toHaveBeenLastCalledWith("liabilities", true));

    await user.click(within(debtTable).getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(setDirty).toHaveBeenLastCalledWith("liabilities", false));

    view.unmount();
    expect(setDirty).toHaveBeenLastCalledWith("liabilities", false);
  });
});
