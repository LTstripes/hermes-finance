import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAccount, deleteAccount, listAccounts, updateAccount } from "../api/accounts";
import {
  deleteInstrumentMapping,
  deleteInstrumentMappingExclusion,
  discoverInstrumentMapping,
  getInstrumentMapping,
  putInstrumentMapping,
  putInstrumentMappingExclusion,
} from "../api/instrumentMappings";
import {
  createInstrument,
  deleteInstrument,
  listInstruments,
  updateInstrument,
} from "../api/instruments";
import type { InstrumentMarketMapping } from "../api/types";
import { ApiClientError } from "../api/client";
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

vi.mock("../api/instrumentMappings", () => ({
  getInstrumentMapping: vi.fn(),
  putInstrumentMapping: vi.fn(),
  deleteInstrumentMapping: vi.fn(),
  putInstrumentMappingExclusion: vi.fn(),
  deleteInstrumentMappingExclusion: vi.fn(),
  discoverInstrumentMapping: vi.fn(),
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

function mappingView(overrides: Partial<InstrumentMarketMapping> = {}): InstrumentMarketMapping {
  return {
    instrument_id: instrument.id,
    state: "unmapped",
    identity: null,
    instrument_isin: instrument.isin,
    legacy_moex_secid: instrument.moex_secid,
    ...overrides,
  };
}

const listAccountsMock = vi.mocked(listAccounts);
const createAccountMock = vi.mocked(createAccount);
const updateAccountMock = vi.mocked(updateAccount);
const deleteAccountMock = vi.mocked(deleteAccount);
const listInstrumentsMock = vi.mocked(listInstruments);
const createInstrumentMock = vi.mocked(createInstrument);
const updateInstrumentMock = vi.mocked(updateInstrument);
const deleteInstrumentMock = vi.mocked(deleteInstrument);
const getInstrumentMappingMock = vi.mocked(getInstrumentMapping);
const putInstrumentMappingMock = vi.mocked(putInstrumentMapping);
const deleteInstrumentMappingMock = vi.mocked(deleteInstrumentMapping);
const putInstrumentMappingExclusionMock = vi.mocked(putInstrumentMappingExclusion);
const deleteInstrumentMappingExclusionMock = vi.mocked(deleteInstrumentMappingExclusion);
const discoverInstrumentMappingMock = vi.mocked(discoverInstrumentMapping);

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
    getInstrumentMappingMock.mockImplementation(async (id) => mappingView({ instrument_id: id }));
    putInstrumentMappingMock.mockResolvedValue(mappingView({ state: "mapped" }));
    deleteInstrumentMappingMock.mockResolvedValue(mappingView());
    putInstrumentMappingExclusionMock.mockResolvedValue(mappingView({ state: "excluded" }));
    deleteInstrumentMappingExclusionMock.mockResolvedValue(mappingView());
    discoverInstrumentMappingMock.mockResolvedValue({
      status: "ok",
      message: null,
      candidates: [],
      rejected: [],
    });
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

  it("deactivates an instrument through the row overflow menu", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([instrument]);
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    expect(await screen.findByText("ОФЗ 26248")).toBeInTheDocument();
    expect(screen.getByText(/Номинал: 1\s*000\s*₽/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Деактивировать" })).toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Действия для инструмента «ОФЗ 26248»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Деактивировать" }));

    await waitFor(() =>
      expect(updateInstrumentMock).toHaveBeenCalledWith(instrument.id, { is_active: false }),
    );
  });

  it("keeps edit and delete actions in the instrument overflow menu", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([instrument]);
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    await screen.findByText("ОФЗ 26248");
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Удалить" })).toBeNull();

    const trigger = screen.getByRole("button", {
      name: "Действия для инструмента «ОФЗ 26248»",
    });
    await user.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    expect(screen.getByText("Удалить запись?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(deleteInstrumentMock).toHaveBeenCalledWith(instrument.id));
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

  it("shows an unmapped instrument without treating legacy moex_secid as mapping", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([{ ...instrument, moex_secid: "SBER" }]);
    getInstrumentMappingMock.mockResolvedValue(
      mappingView({ legacy_moex_secid: "SBER", instrument_isin: instrument.isin }),
    );
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    expect(await screen.findByText("Не настроен")).toBeInTheDocument();
    expect(screen.queryByTestId("mapping-identity-10")).toBeNull();
    expect(screen.queryByText("SBER")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Настроить источник" }));
    expect(screen.getByTestId("legacy-moex-hint")).toHaveTextContent("не принятый источник");
    expect(screen.getByTestId("accepted-mapping-identity")).toHaveTextContent(
      "Принятого источника нет",
    );
  });

  it("does not treat a failed mapping GET as unmapped", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([instrument]);
    getInstrumentMappingMock.mockRejectedValueOnce(
      new ApiClientError(500, {
        code: "internal_error",
        message: "mapping lookup failed",
        details: [],
      }),
    );
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (0)" }));
    expect(await screen.findByText("Не удалось загрузить инструменты")).toBeInTheDocument();
    expect(
      screen.getByText("Внутренняя ошибка приложения. Попробуй обновить данные."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Не настроен")).toBeNull();
    expect(screen.queryByText("ОФЗ 26248")).toBeNull();
    expect(screen.queryByRole("button", { name: "Настроить источник" })).toBeNull();

    getInstrumentMappingMock.mockResolvedValueOnce(
      mappingView({
        state: "mapped",
        identity: {
          provider: "moex_iss",
          provider_instrument_id: "SU26248",
          provider_venue_id: "stock/bonds/TQOB",
        },
      }),
    );
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("ОФЗ 26248")).toBeInTheDocument();
    expect(screen.getByText("Подключён")).toBeInTheDocument();
    expect(screen.getByTestId("mapping-identity-10")).toHaveTextContent("SU26248");
    expect(screen.queryByText("Не настроен")).toBeNull();
  });

  it("shows a complete mapping and saves, clears, excludes and restores it", async () => {
    const user = userEvent.setup();
    const identity = {
      provider: "moex_iss",
      provider_instrument_id: "SU26248",
      provider_venue_id: "stock/bonds/TQOB",
    };
    listInstrumentsMock.mockResolvedValue([instrument]);
    getInstrumentMappingMock.mockResolvedValue(mappingView({ state: "mapped", identity }));
    putInstrumentMappingMock.mockResolvedValue(mappingView({ state: "mapped", identity }));
    deleteInstrumentMappingMock.mockResolvedValue(mappingView());
    putInstrumentMappingExclusionMock.mockResolvedValue(
      mappingView({ state: "excluded", identity }),
    );
    deleteInstrumentMappingExclusionMock.mockResolvedValue(
      mappingView({ state: "mapped", identity }),
    );
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    expect(await screen.findByText("Подключён")).toBeInTheDocument();
    expect(screen.getByTestId("mapping-identity-10")).toHaveTextContent("TQOB");
    expect(screen.getByTestId("mapping-identity-10")).toHaveTextContent("SU26248");

    await user.click(screen.getByRole("button", { name: "Настроить источник" }));
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));
    await waitFor(() => expect(putInstrumentMappingMock).toHaveBeenCalledWith(10, identity));

    await user.click(screen.getByRole("button", { name: "Удалить источник" }));
    await waitFor(() => expect(deleteInstrumentMappingMock).toHaveBeenCalledWith(10));
    expect(await screen.findAllByText("Не настроен")).not.toHaveLength(0);
    expect(screen.queryByTestId("mapping-identity-10")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Отключить обновление" }));
    await waitFor(() => expect(putInstrumentMappingExclusionMock).toHaveBeenCalledWith(10));
    expect(await screen.findAllByText("Отключён")).not.toHaveLength(0);

    deleteInstrumentMappingExclusionMock.mockResolvedValueOnce(mappingView());
    await user.click(screen.getByRole("button", { name: "Включить обновление" }));
    await waitFor(() => expect(deleteInstrumentMappingExclusionMock).toHaveBeenCalledWith(10));
  });

  it("renders mapping mutation errors through the existing alert", async () => {
    const user = userEvent.setup();
    listInstrumentsMock.mockResolvedValue([instrument]);
    putInstrumentMappingMock.mockRejectedValue(
      new ApiClientError(422, {
        code: "unprocessable",
        message: "engine/market stock/shares is incompatible with bond",
        details: [],
      }),
    );
    render(<AccountsPage />);

    await user.click(await screen.findByRole("button", { name: "Инструменты (1)" }));
    await user.click(await screen.findByRole("button", { name: "Настроить источник" }));
    expect(discoverInstrumentMappingMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "MOEX ISS" }));
    await user.type(screen.getByLabelText("Режим торгов (boardid)"), "TQOB");
    await user.type(screen.getByLabelText("Код бумаги (secid)"), "SU26248");
    await user.click(screen.getByRole("button", { name: "Сохранить источник" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Проверь введённые данные.");
  });
});
