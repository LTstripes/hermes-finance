import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import {
  confirmBrokerIdentityMapping,
  type BrokerIdentityMapping,
  listEffectiveBrokerIdentityMappings,
  remapBrokerIdentityMapping,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import type { Account } from "../api/types";
import { BrokerIdentityMappingsPanel } from "./BrokerIdentityMappingsPanel";

vi.mock("../api/accounts", () => ({
  listAccounts: vi.fn(),
}));

vi.mock("../api/brokerIdentityMappings", () => ({
  confirmBrokerIdentityMapping: vi.fn(),
  listEffectiveBrokerIdentityMappings: vi.fn(),
  remapBrokerIdentityMapping: vi.fn(),
  revokeBrokerIdentityMapping: vi.fn(),
}));

const account = { id: 1, name: "Основной счёт" } as Account;
const reserveAccount = { id: 2, name: "Резервный счёт" } as Account;

function mapping(overrides: Partial<BrokerIdentityMapping> = {}): BrokerIdentityMapping {
  return {
    mapping_id: 1,
    provider: "alfa_pro",
    subject_kind: "account",
    provider_identity: "SYN-ACCOUNT-001",
    hermes_target_id: 1,
    status: "effective",
    observed_isin: null,
    confirmed_at: "2026-08-31T12:00:00Z",
    source_as_of: null,
    captured_at: null,
    predecessor_mapping_id: null,
    successor_mapping_id: null,
    revoked_at: null,
    revoke_reason: null,
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <BrokerIdentityMappingsPanel />
    </MemoryRouter>,
  );
}

const listAccountsMock = vi.mocked(listAccounts);
const listMappingsMock = vi.mocked(listEffectiveBrokerIdentityMappings);
const confirmMappingMock = vi.mocked(confirmBrokerIdentityMapping);
const remapMappingMock = vi.mocked(remapBrokerIdentityMapping);
const revokeMappingMock = vi.mocked(revokeBrokerIdentityMapping);

describe("BrokerIdentityMappingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAccountsMock.mockResolvedValue([account, reserveAccount]);
    listMappingsMock.mockResolvedValue([mapping()]);
    confirmMappingMock.mockResolvedValue(
      mapping({ mapping_id: 2, provider_identity: "SYN-ACCOUNT-NEW", hermes_target_id: 2 }),
    );
    remapMappingMock.mockResolvedValue(
      mapping({ mapping_id: 2, hermes_target_id: 2, predecessor_mapping_id: 1 }),
    );
    revokeMappingMock.mockResolvedValue(mapping({ status: "revoked", revoked_at: "2026-08-31" }));
  });

  it("lists effective account mappings with Hermes names and performs no write on load", async () => {
    renderPanel();

    expect(await screen.findByText("SYN-ACCOUNT-001")).toBeInTheDocument();
    expect(screen.getAllByText("Основной счёт").length).toBeGreaterThan(0);
    expect(screen.getByText("Действует")).toBeInTheDocument();
    expect(screen.queryByText("Счёт Hermes не найден")).toBeNull();
    expect(confirmMappingMock).not.toHaveBeenCalled();
    expect(remapMappingMock).not.toHaveBeenCalled();
    expect(revokeMappingMock).not.toHaveBeenCalled();
  });

  it("explicitly confirms a new account mapping", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(
      await screen.findByLabelText("Идентификатор счёта Alfa PRO"),
      "SYN-ACCOUNT-NEW",
    );
    await user.selectOptions(screen.getByLabelText("Счёт Hermes"), "2");
    await user.click(screen.getByRole("button", { name: "Подтвердить сопоставление" }));

    await waitFor(() =>
      expect(confirmMappingMock).toHaveBeenCalledWith({
        provider: "alfa_pro",
        subject_kind: "account",
        provider_identity: "SYN-ACCOUNT-NEW",
        hermes_target_id: 2,
      }),
    );
    expect(await screen.findByText("Сопоставление счёта подтверждено.")).toBeInTheDocument();
    expect(screen.getByText("SYN-ACCOUNT-NEW")).toBeInTheDocument();
  });

  it("confirms remap before calling the history-preserving endpoint", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.selectOptions(await screen.findByLabelText("Новый счёт Hermes"), "2");
    await user.click(screen.getByRole("button", { name: "Переназначить" }));

    expect(remapMappingMock).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Предыдущее подтверждение останется в истории");
    await user.click(within(dialog).getByRole("button", { name: "Подтвердить переназначение" }));

    await waitFor(() => expect(remapMappingMock).toHaveBeenCalledWith(1, { hermes_target_id: 2 }));
    expect(
      await screen.findByText(
        "Сопоставление переназначено. Предыдущее подтверждение сохранено в истории.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Резервный счёт").length).toBeGreaterThan(0);
  });

  it("requires explicit confirmation before revoking", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Отозвать" }));
    expect(revokeMappingMock).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Отозвать сопоставление" }));

    await waitFor(() => expect(revokeMappingMock).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/^Сопоставление отозвано\./)).toBeInTheDocument();
    expect(screen.queryByText("SYN-ACCOUNT-001")).toBeNull();
  });
});
