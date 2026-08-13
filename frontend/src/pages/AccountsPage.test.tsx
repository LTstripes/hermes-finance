import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAccount, deleteAccount, listAccounts, updateAccount } from "../api/accounts";
import {
  createInstrument,
  deleteInstrument,
  listInstruments,
  updateInstrument,
} from "../api/instruments";
import { AccountsPage } from "./AccountsPage";

vi.mock("../api/accounts", () => ({
  listAccounts: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}));

vi.mock("../api/instruments", () => ({
  listInstruments: vi.fn(),
  createInstrument: vi.fn(),
  updateInstrument: vi.fn(),
  deleteInstrument: vi.fn(),
}));

const account = {
  id: 1,
  name: "Основной брокерский",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const hiddenAccount = {
  ...account,
  id: 2,
  name: "Старый счёт",
  status: "hidden",
};

const instrument = {
  id: 10,
  name: "ОФЗ 26248",
  instrument_type: "bond",
  isin: "RU000A108EH8",
  ticker: null,
  moex_secid: null,
  currency: "RUB",
  nominal_value: { amount: "1000.00", currency: "RUB" },
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const listAccountsMock = vi.mocked(listAccounts);
const createAccountMock = vi.mocked(createAccount);
const updateAccountMock = vi.mocked(updateAccount);
const deleteAccountMock = vi.mocked(deleteAccount);
const listInstrumentsMock = vi.mocked(listInstruments);
const createInstrumentMock = vi.mocked(createInstrument);
const updateInstrumentMock = vi.mocked(updateInstrument);
const deleteInstrumentMock = vi.mocked(deleteInstrument);

describe("AccountsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAccountsMock.mockResolvedValue([]);
    listInstrumentsMock.mockResolvedValue([]);
    createAccountMock.mockResolvedValue(account);
    updateAccountMock.mockResolvedValue(account);
    deleteAccountMock.mockResolvedValue(undefined);
    createInstrumentMock.mockResolvedValue(instrument);
    updateInstrumentMock.mockResolvedValue(instrument);
    deleteInstrumentMock.mockResolvedValue(undefined);
  });

  it("renders accounts and separates hidden rows", async () => {
    listAccountsMock.mockResolvedValue([account, hiddenAccount]);
    render(<AccountsPage />);

    expect(await screen.findByText("Основной брокерский")).toBeInTheDocument();
    expect(screen.getByText("Старый счёт")).toBeInTheDocument();
    expect(screen.getByText("Активные (1)")).toBeInTheDocument();
    expect(screen.getByText("Скрытые и закрытые (1)")).toBeInTheDocument();
    expect(screen.getAllByText("Брокерский")).toHaveLength(2);
  });

  it("shows a friendly label instead of a legacy account code", async () => {
    listAccountsMock.mockResolvedValue([{ ...account, external_code: "legacy:brokerage:1" }]);
    render(<AccountsPage />);

    expect(await screen.findByText("Импортирован из прежней версии")).toBeInTheDocument();
    expect(screen.queryByText("legacy:brokerage:1")).toBeNull();
  });

  it("creates an account with backend-aligned true defaults", async () => {
    const user = userEvent.setup();
    render(<AccountsPage />);

    await screen.findByText("Нет счетов");
    await user.click(screen.getAllByRole("button", { name: "Создать счёт" })[0]);
    await user.type(screen.getByLabelText("Название"), "Новый ИИС");
    await user.selectOptions(screen.getByLabelText("Тип"), "iis");
    await user.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() =>
      expect(createAccountMock).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Новый ИИС",
          account_type: "iis",
          status: "active",
          include_in_capital: true,
          include_in_returns: true,
        }),
      ),
    );
  });

  it("shows a hidden account through PATCH without inventing a new endpoint", async () => {
    const user = userEvent.setup();
    listAccountsMock.mockResolvedValue([hiddenAccount]);
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Показать" }));
    await waitFor(() =>
      expect(updateAccountMock).toHaveBeenCalledWith(hiddenAccount.id, { status: "active" }),
    );
  });

  it("deactivates an instrument through PATCH", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([instrument]);
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    expect(await screen.findByText("ОФЗ 26248")).toBeInTheDocument();
    expect(screen.getByText(/Номинал: 1\s*000\s*₽/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Деактивировать" }));

    await waitFor(() =>
      expect(updateInstrumentMock).toHaveBeenCalledWith(instrument.id, { is_active: false }),
    );
  });

  it("renders account load error and retries only that list", async () => {
    const user = userEvent.setup();
    listAccountsMock.mockRejectedValueOnce(new Error("accounts unavailable"));
    render(<AccountsPage />);

    expect(await screen.findByText("accounts unavailable")).toBeInTheDocument();
    listAccountsMock.mockResolvedValueOnce([account]);
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("Основной брокерский")).toBeInTheDocument();
    expect(listInstrumentsMock).toHaveBeenCalledTimes(1);
  });
});
