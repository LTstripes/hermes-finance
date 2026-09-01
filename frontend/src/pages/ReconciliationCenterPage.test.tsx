import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import {
  type BrokerReconciliationResponse,
  previewBrokerReconciliation,
  type ReconciliationRow,
} from "../api/brokerReconciliation";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import type { Account, Instrument } from "../api/types";
import { MemoryRouter } from "react-router";
import { ReconciliationCenterPage } from "./ReconciliationCenterPage";

vi.mock("../api/brokerReconciliation", () => ({
  previewBrokerReconciliation: vi.fn(),
}));

vi.mock("../api/accounts", () => ({
  listAccounts: vi.fn(),
}));

vi.mock("../api/instruments", () => ({
  listInstruments: vi.fn(),
}));

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
}));

const month = {
  id: 7,
  year: 2026,
  month: 8,
  status: "draft" as const,
  snapshot_date: "2026-08-31",
  source: "manual",
};

const account = {
  id: 1,
  name: "Синтетический счёт",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
} satisfies Account;

const instrument = {
  id: 10,
  name: "Синтетическая облигация",
  instrument_type: "bond",
  isin: "RU000SYN00001",
  ticker: "SYN",
  moex_secid: null,
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
} satisfies Instrument;

const diagnostics = {
  schema_version: "alfa-pro-diagnostics/v1",
  provider: "alfa_pro",
  snapshot_status: "complete",
  eligible_for_apply: false,
  compatibility_state: "compatible",
  compatibility_fingerprint: "a".repeat(64),
  api_doc_version: "synthetic-2.1",
  observed_alfa_pro_version: "synthetic-compat-1",
  observed_api_version: "2.1",
  observed_protocol_version: "router-v1",
  protocol_family: "router-v1",
  layout_family: "snapshot-v2.1",
  capabilities: ["position_quantity"],
  failure_class: "none",
  failure_codes: [],
  entity_status: ["positions=ok"],
  entity_counts: ["positions=1"],
  observed_fields: ["position.quantity"],
  safe_artifact: true,
  raw_payload_saved: false,
  private_values_included: false,
  credentials_included: false,
};

function row(
  state: ReconciliationRow["state"],
  overrides: Partial<ReconciliationRow> = {},
): ReconciliationRow {
  return {
    state,
    account_id: 1,
    instrument_id: 10,
    account_name: "Синтетический счёт",
    instrument_name: "Синтетическая облигация",
    instrument_isin: "RU000SYN00001",
    instrument_ticker: "SYN",
    provider_account_id: "SYN-ACCOUNT-001",
    provider_instrument_id: "SYN-INSTRUMENT-001",
    hermes_quantity: "10",
    provider_quantity: "10",
    quantity_difference: "0",
    quantity_equal: true,
    hermes_market_price_per_unit_kopecks: 10000,
    provider_broker_unit_price: "101.25",
    provider_accounting_price: "99.50",
    provider_market_value: "1012.50",
    price_comparable: "non_comparable",
    hermes_accrued_interest_kopecks: 125,
    provider_accrued_interest_nkd: "1.25",
    nkd_comparable: "non_comparable",
    hermes_unrealized_result_kopecks: 1750,
    provider_unrealized_result: "17.50",
    unrealized_comparable: "non_comparable",
    reason: null,
    warnings: [],
    comparison_only_fields: [
      "provider_broker_unit_price",
      "provider_accounting_price",
      "provider_market_value",
      "provider_accrued_interest_nkd",
      "provider_unrealized_result",
    ],
    fingerprint: "b".repeat(64),
    ...overrides,
  };
}

function result(
  overrides: Partial<BrokerReconciliationResponse> = {},
): BrokerReconciliationResponse {
  return {
    reporting_month_id: month.id,
    provider: "alfa_pro",
    status: "applicable",
    read_only: true,
    eligible_for_apply: false,
    stale: false,
    snapshot_status: "complete",
    compatibility_state: "compatible",
    compatibility_fingerprint: "a".repeat(64),
    snapshot_fingerprint: "c".repeat(64),
    source_as_of: "2026-08-28T10:00:00+00:00",
    captured_at: "2026-08-28T10:01:00+00:00",
    month_status: "draft",
    month_closed: false,
    accounts: [],
    instruments: [],
    rows: [row("matched")],
    cash: [],
    warnings: [],
    diagnostics,
    diagnostic_report: "safe synthetic diagnostics\n",
    error_code: null,
    message: null,
    ...overrides,
  };
}

function unresolvedMappingResult(
  overrides: Partial<BrokerReconciliationResponse> = {},
): BrokerReconciliationResponse {
  return result({
    status: "non_applicable",
    accounts: [
      {
        provider_account_id: "SYN-ACCOUNT-001",
        hermes_account_id: null,
        status: "unmatched",
        reason: "no explicit owner mapping for provider account",
        section_codes: ["MICEX"],
        observed_instruments: [
          {
            display_name: "Synthetic provider bond",
            isin: "RU000SYN00001",
            ticker: "SYN",
          },
        ],
      },
    ],
    instruments: [
      {
        provider_instrument_id: "SYN-INSTRUMENT-001",
        isin: "RU000SYN00001",
        ticker: "SYN",
        display_name: "Synthetic provider bond",
        hermes_instrument_id: null,
        status: "unmatched",
        reason: "no Hermes instrument with this ISIN",
      },
    ],
    rows: [row("unresolved", { reason: "account_mapping_unresolved" })],
    ...overrides,
  });
}

function manyObservedInstruments(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const n = String(index + 1).padStart(2, "0");
    return {
      display_name: `Synthetic bond ${n}`,
      isin: `RU000SYN000${n}`,
      ticker: `SYN${n}`,
    };
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReconciliationCenterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReconciliationCenterPage", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMonths).mockResolvedValue([month]);
    vi.mocked(listAccounts).mockResolvedValue([account]);
    vi.mocked(listInstruments).mockResolvedValue([instrument]);
    vi.mocked(previewBrokerReconciliation).mockResolvedValue(result());
  });

  it("does not call the provider when the page is only opened", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Сверка портфеля" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(listMonths).toHaveBeenCalledTimes(1));
    expect(previewBrokerReconciliation).not.toHaveBeenCalled();
  });

  it("keeps the close month, shows the transient compact result, and forgets it after remount", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      "",
      "/reconciliation?from=monthly-close&step=broker_reconciliation&monthId=7",
    );
    const firstRender = renderPage();

    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await waitFor(() => expect(monthSelect).toHaveValue("7"));
    expect(monthSelect).toBeDisabled();
    expect(previewBrokerReconciliation).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    expect(
      await screen.findByRole("status", { name: "Результат сверки Alfa PRO" }),
    ).toHaveTextContent("Совпадает");
    expect(previewBrokerReconciliation).toHaveBeenCalledWith(7, {
      accounts: [],
      instruments: [],
    });

    firstRender.unmount();
    renderPage();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Сверка портфеля" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: "Результат сверки Alfa PRO" }),
    ).not.toBeInTheDocument();
    expect(previewBrokerReconciliation).toHaveBeenCalledTimes(1);
  });

  it("runs the accepted read-only path explicitly and renders every normalized state", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerReconciliation).mockResolvedValue(
      result({
        rows: [
          row("matched"),
          row("differs", {
            quantity_difference: "-2",
            provider_quantity: "12",
            quantity_equal: false,
          }),
          row("missing_local", {
            account_id: null,
            instrument_id: null,
            account_name: null,
            instrument_name: null,
            hermes_quantity: null,
          }),
          row("missing_provider", {
            provider_account_id: null,
            provider_instrument_id: null,
            provider_quantity: null,
          }),
          row("unresolved", { reason: "instrument_mapping_unresolved" }),
        ],
      }),
    );

    renderPage();
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await screen.findByRole("option", { name: /Август/ });
    await user.selectOptions(monthSelect, "7");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    expect((await screen.findAllByText("Совпадает")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Отличается").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Нет локальной позиции").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Нет позиции у брокера").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Не сопоставлено").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Учётная цена брокера:").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Оценка брокера:").length).toBeGreaterThan(0);
    expect(screen.getAllByText("только сравнение").length).toBeGreaterThan(0);
    expect(screen.getByText("Нельзя считать сопоставление безопасным")).toBeInTheDocument();
    expect(screen.queryByText("matched")).toBeNull();
    expect(screen.queryByText(/Локально: счёт #1/)).toBeNull();
    expect(screen.getByText("Техническая диагностика")).toBeVisible();
    expect(screen.getByText("Версия API", { exact: true })).not.toBeVisible();
    expect(screen.queryByText(/Owner action|Read-only|comparison-only|Backend/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Применить/i })).not.toBeInTheDocument();
    expect(previewBrokerReconciliation).toHaveBeenCalledWith(7, { accounts: [], instruments: [] });
  });

  it("keeps unresolved mapping visibly unsafe and sends owner mapping only on the next explicit check", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerReconciliation)
      .mockResolvedValueOnce(unresolvedMappingResult())
      .mockResolvedValueOnce(result());

    renderPage();
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await screen.findByRole("option", { name: /Август/ });
    await user.selectOptions(monthSelect, "7");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    const accountSelect = await screen.findByLabelText("Раздел MICEX · Synthetic provider bond");
    const instrumentSelect = screen.getByLabelText("Synthetic provider bond · RU000SYN00001 · SYN");
    expect(screen.getByText("Нельзя считать сопоставление безопасным")).toBeInTheDocument();
    await user.selectOptions(accountSelect, "1");
    await user.selectOptions(instrumentSelect, "10");
    expect(screen.getByText(/Сопоставление изменилось/)).toBeInTheDocument();
    expect(previewBrokerReconciliation).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Обновить сверку" }));
    await waitFor(() => expect(previewBrokerReconciliation).toHaveBeenCalledTimes(2));
    expect(previewBrokerReconciliation).toHaveBeenLastCalledWith(7, {
      accounts: [{ hermes_account_id: 1, provider_account_id: "SYN-ACCOUNT-001" }],
      instruments: [{ hermes_instrument_id: 10, provider_instrument_id: "SYN-INSTRUMENT-001" }],
    });
  });

  it("makes unresolved mapping rows owner-identifiable without raw English reasons", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerReconciliation).mockResolvedValue(unresolvedMappingResult());

    renderPage();
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await screen.findByRole("option", { name: /Август/ });
    await user.selectOptions(monthSelect, "7");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    expect(
      await screen.findByLabelText("Раздел MICEX · Synthetic provider bond"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Synthetic provider bond · RU000SYN00001 · SYN"),
    ).toBeInTheDocument();
    expect(screen.getByText("Источник: SYN-ACCOUNT-001")).toBeInTheDocument();
    expect(screen.getByText("Источник: SYN-INSTRUMENT-001")).toBeInTheDocument();
    expect(
      screen.getByText("Причина: Нет явного сопоставления владельца для счёта брокера"),
    ).toBeInTheDocument();
    expect(screen.getByText("Причина: Нет локального инструмента с этим ISIN")).toBeInTheDocument();
    expect(
      screen.queryByText(/no explicit owner mapping for provider account/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/no Hermes instrument with this ISIN/i)).not.toBeInTheDocument();
  });

  it("bounds a long account identity and keeps the provider id on its own line", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerReconciliation).mockResolvedValue(
      unresolvedMappingResult({
        accounts: [
          {
            provider_account_id: "SYN-ACCOUNT-001",
            hermes_account_id: null,
            status: "unmatched",
            reason: "no explicit owner mapping for provider account",
            section_codes: ["MICEX"],
            observed_instruments: manyObservedInstruments(8),
          },
        ],
      }),
    );

    renderPage();
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await screen.findByRole("option", { name: /Август/ });
    await user.selectOptions(monthSelect, "7");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    expect(
      await screen.findByLabelText(
        "Раздел MICEX · Synthetic bond 01 · Synthetic bond 02 · Synthetic bond 03 · ещё 5",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Источник: SYN-ACCOUNT-001")).toBeInTheDocument();
    expect(screen.queryByText(/Synthetic bond 04/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Synthetic bond 08/)).not.toBeInTheDocument();
  });

  it.each([
    [
      "stale",
      "Снимок устарел. Сверка и любые следующие действия неприменимы до явного обновления снимка.",
    ],
    [
      "compatibility unknown",
      "Совместимость снимка не подтверждена. Результат оставлен для диагностики и неприменим.",
    ],
  ])("marks %s results as visibly non-applicable", async (_name, message) => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerReconciliation).mockResolvedValue(
      result({
        status: "non_applicable",
        stale: _name === "stale",
        snapshot_status: _name === "stale" ? "stale" : "complete",
        compatibility_state: _name === "stale" ? "compatible" : "unknown",
        rows: [],
      }),
    );

    renderPage();
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    await screen.findByRole("option", { name: /Август/ });
    await user.selectOptions(monthSelect, "7");
    await user.click(screen.getByRole("button", { name: "Проверить снимок" }));

    expect(await screen.findByText("Не применяется")).toBeInTheDocument();
    expect(screen.getByText("Сверка остановлена из соображений безопасности")).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
  });
});
