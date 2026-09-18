import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAccount, deleteAccount, listAccounts, updateAccount } from "../api/accounts";
import {
  confirmBrokerIdentityMapping,
  listEffectiveBrokerIdentityMappings,
  remapBrokerIdentityMapping,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import { discoverInstrumentMapping, getInstrumentMapping } from "../api/instrumentMappings";
import { listMonths } from "../api/months";
import { deleteInstrument, getInstrumentCleanup, listInstruments } from "../api/instruments";
import type { BrokerIdentityMapping } from "../api/brokerIdentityMappings";
import type { InstrumentCleanup, InstrumentMarketMapping } from "../api/types";
import UiV2DataCatalogsPage from "../ui-v2/UiV2DataCatalogsPage";

vi.mock("../api/accounts", () => ({
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  listAccounts: vi.fn(),
  updateAccount: vi.fn(),
}));

vi.mock("../api/brokerIdentityMappings", () => ({
  confirmBrokerIdentityMapping: vi.fn(),
  listEffectiveBrokerIdentityMappings: vi.fn(),
  remapBrokerIdentityMapping: vi.fn(),
  revokeBrokerIdentityMapping: vi.fn(),
}));

vi.mock("../api/instrumentMappings", () => ({
  deleteInstrumentMapping: vi.fn(),
  deleteInstrumentMappingExclusion: vi.fn(),
  discoverInstrumentMapping: vi.fn(),
  getInstrumentMapping: vi.fn(),
  putInstrumentMapping: vi.fn(),
  putInstrumentMappingExclusion: vi.fn(),
}));

vi.mock("../api/months", () => ({ listMonths: vi.fn() }));

vi.mock("../api/instruments", () => ({
  createInstrument: vi.fn(),
  deleteInstrument: vi.fn(),
  getInstrumentCleanup: vi.fn(),
  listInstruments: vi.fn(),
  updateInstrument: vi.fn(),
}));

const account = {
  id: 1,
  name: "Синтетический брокерский счёт",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: false,
  notes: null,
};

const hiddenAccount = {
  ...account,
  id: 2,
  name: "Синтетический закрытый счёт",
  status: "hidden",
};

const instrument = {
  id: 10,
  name: "Синтетическая облигация",
  instrument_type: "bond",
  isin: "RU000A000001",
  ticker: "SYNB",
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

function cleanupView(overrides: Partial<InstrumentCleanup> = {}): InstrumentCleanup {
  return {
    instrument_id: instrument.id,
    can_delete: true,
    status: "deletable",
    reason_code: "unused",
    message: "Инструмент не используется. Его можно удалить после явного подтверждения.",
    references: [],
    active_duplicates: [],
    ...overrides,
  };
}

function brokerMapping(): BrokerIdentityMapping {
  return {
    mapping_id: 20,
    provider: "alfa_pro",
    subject_kind: "account",
    provider_identity: "SYN-CATALOG-ACCOUNT-001",
    hermes_target_id: account.id,
    status: "effective",
    observed_isin: null,
    confirmed_at: "2031-08-31T12:00:00Z",
    source_as_of: null,
    captured_at: null,
    predecessor_mapping_id: null,
    successor_mapping_id: null,
    revoked_at: null,
    revoke_reason: null,
  };
}

const listAccountsMock = vi.mocked(listAccounts);
const createAccountMock = vi.mocked(createAccount);
const updateAccountMock = vi.mocked(updateAccount);
const deleteAccountMock = vi.mocked(deleteAccount);
const listInstrumentsMock = vi.mocked(listInstruments);
const deleteInstrumentMock = vi.mocked(deleteInstrument);
const getInstrumentCleanupMock = vi.mocked(getInstrumentCleanup);
const getInstrumentMappingMock = vi.mocked(getInstrumentMapping);
const discoverInstrumentMappingMock = vi.mocked(discoverInstrumentMapping);
const listMonthsMock = vi.mocked(listMonths);
const listBrokerMappingsMock = vi.mocked(listEffectiveBrokerIdentityMappings);
const confirmBrokerMappingMock = vi.mocked(confirmBrokerIdentityMapping);
const remapBrokerMappingMock = vi.mocked(remapBrokerIdentityMapping);
const revokeBrokerMappingMock = vi.mocked(revokeBrokerIdentityMapping);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/v2/data/catalogs"]}>
        <UiV2DataCatalogsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("UiV2DataCatalogsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMonthsMock.mockResolvedValue([
      {
        id: 12,
        year: 2031,
        month: 8,
        status: "draft",
        snapshot_date: "2031-08-30",
        source: "manual",
      },
    ]);
    listAccountsMock.mockResolvedValue([account, hiddenAccount]);
    createAccountMock.mockResolvedValue(account);
    updateAccountMock.mockResolvedValue(account);
    deleteAccountMock.mockResolvedValue(undefined);
    listInstrumentsMock.mockResolvedValue([instrument]);
    getInstrumentMappingMock.mockImplementation(async (id) => mappingView({ instrument_id: id }));
    getInstrumentCleanupMock.mockResolvedValue(cleanupView());
    deleteInstrumentMock.mockResolvedValue(undefined);
    discoverInstrumentMappingMock.mockResolvedValue({
      status: "ok",
      message: null,
      candidates: [],
      rejected: [],
    });
    listBrokerMappingsMock.mockResolvedValue([]);
    confirmBrokerMappingMock.mockResolvedValue(brokerMapping());
    remapBrokerMappingMock.mockResolvedValue(brokerMapping());
    revokeBrokerMappingMock.mockResolvedValue(brokerMapping());
  });

  it("renders native catalog semantics without probing a provider", async () => {
    renderPage();

    expect(await screen.findByTestId("catalog-accounts")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Справочники и сопоставления" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: "В капитале" })).toHaveLength(2);
    expect(screen.getAllByRole("columnheader", { name: "В доходности" })).toHaveLength(2);
    const activeRow = screen.getByRole("row", { name: /Синтетический брокерский счёт/ });
    expect(within(activeRow).getByText("Да")).toBeInTheDocument();
    expect(within(activeRow).getByText("Нет")).toBeInTheDocument();
    expect(discoverInstrumentMappingMock).not.toHaveBeenCalled();
  });

  it("requires explicit account mutations and confirmation for deletion", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Создать счёт" }));
    await user.type(screen.getByLabelText("Название"), "Новый синтетический счёт");
    await user.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(createAccountMock).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Новый синтетический счёт",
          include_in_capital: true,
          include_in_returns: true,
        }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "Скрыть" }));
    await waitFor(() =>
      expect(updateAccountMock).toHaveBeenCalledWith(account.id, { status: "hidden" }),
    );

    const accountRow = screen.getByRole("row", { name: /Синтетический брокерский счёт/ });
    await user.click(within(accountRow).getByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("явное удаление записи справочника");
    expect(deleteAccountMock).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(deleteAccountMock).toHaveBeenCalledWith(account.id));
  });

  it("keeps instrument cleanup fail-closed and discovery explicit", async () => {
    const user = userEvent.setup();
    getInstrumentCleanupMock.mockResolvedValue(
      cleanupView({
        can_delete: false,
        status: "protected",
        reason_code: "historical_referenced",
        message: "Нельзя удалить: инструмент используется в закрытой истории.",
      }),
    );
    discoverInstrumentMappingMock.mockResolvedValue({
      status: "ok",
      message: "Синтетических кандидатов не найдено.",
      candidates: [],
      rejected: [],
    });
    renderPage();

    await user.click(await screen.findByRole("tab", { name: /Инструменты/ }));
    expect(await screen.findByText("Синтетическая облигация")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Настроить источник" }));
    expect(discoverInstrumentMappingMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Найти в T-Invest" }));
    await waitFor(() =>
      expect(discoverInstrumentMappingMock).toHaveBeenCalledWith(10, { provider: "t_invest" }),
    );

    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    const instrumentRow = screen.getByRole("row", { name: /Синтетическая облигация/ });
    await user.click(within(instrumentRow).getByRole("button", { name: "Удалить" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Нельзя удалить");
    await user.click(within(dialog).getByRole("button", { name: "Понятно" }));
    expect(deleteInstrumentMock).not.toHaveBeenCalled();
  });

  it("keeps broker identity mappings read-only until an explicit action", async () => {
    listBrokerMappingsMock.mockResolvedValue([brokerMapping()]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: /Постоянные сопоставления/ }));
    expect(await screen.findByText("SYN-CATALOG-ACCOUNT-001")).toBeInTheDocument();
    expect(confirmBrokerMappingMock).not.toHaveBeenCalled();
    expect(remapBrokerMappingMock).not.toHaveBeenCalled();
    expect(revokeBrokerMappingMock).not.toHaveBeenCalled();
  });
});
