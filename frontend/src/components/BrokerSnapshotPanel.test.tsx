import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listBrokerIdentityMappings,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import { applyBrokerBaseline, previewBrokerSnapshot } from "../api/brokerSnapshot";
import { listMonths } from "../api/months";
import type { Account, Instrument } from "../api/types";
import { BrokerSnapshotPanel } from "./BrokerSnapshotPanel";

vi.mock("../api/brokerSnapshot", () => ({
  applyBrokerBaseline: vi.fn(),
  previewBrokerSnapshot: vi.fn(),
}));

vi.mock("../api/brokerIdentityMappings", () => ({
  listBrokerIdentityMappings: vi.fn(),
  revokeBrokerIdentityMapping: vi.fn(),
}));

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
}));

const account = { id: 1, name: "Основной счёт" } as Account;
const instrument = { id: 10, name: "Синтетическая облигация", isin: "RU000SYNTH01" } as Instrument;

const matched = {
  account_id: 1,
  instrument_id: 10,
  account_name: "Основной счёт",
  instrument_name: "Синтетическая облигация",
  instrument_isin: "RU000SYNTH01",
  status: "matched",
  provider_quantity: "2",
  hermes_quantity: "2",
  quantity_difference: "0",
  quantity_equal: true,
  fingerprint: "fp-matched",
  reason: null,
  warnings: [],
  provider_broker_unit_price: "101.25",
  provider_accrued_interest_nkd: "3.50",
  provider_unrealized_result: "12.00",
};

function preview(overrides: Record<string, unknown> = {}) {
  return {
    reporting_month_id: 7,
    provider: "alfa_pro",
    status: "applicable",
    eligible_for_apply: true,
    snapshot_status: "complete",
    positions: [matched],
    accounts: [],
    instruments: [],
    cash: [],
    warnings: [],
    diagnostics: {
      schema_version: "alfa-pro-diagnostics/v1",
      provider: "alfa_pro",
      snapshot_status: "complete",
      eligible_for_apply: true,
      compatibility_state: "compatible",
      compatibility_fingerprint: "a".repeat(64),
      api_doc_version: "2.1",
      observed_alfa_pro_version: "synthetic-compat-1",
      observed_api_version: "2.1",
      observed_protocol_version: "2.1",
      protocol_family: "router-v1",
      layout_family: "snapshot-v2.1",
      capabilities: ["position_quantity"],
      failure_class: "none",
      failure_codes: [],
      entity_status: ["synthetic=ok"],
      entity_counts: ["synthetic=1"],
      observed_fields: ["synthetic={Field}"],
      safe_artifact: true,
      raw_payload_saved: false,
      private_values_included: false,
      credentials_included: false,
    },
    diagnostic_report: "safe synthetic diagnostics\n",
    error_code: null,
    message: null,
    ...overrides,
  };
}

describe("BrokerSnapshotPanel explicit owner decisions", () => {
  beforeEach(() => {
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(preview());
    vi.mocked(listBrokerIdentityMappings).mockResolvedValue([]);
    vi.mocked(revokeBrokerIdentityMapping).mockResolvedValue({
      mapping_id: 1,
      provider: "alfa_pro",
      subject_kind: "instrument",
      provider_identity: "needs-owner",
      hermes_target_id: 10,
      status: "revoked",
      observed_isin: null,
      confirmed_at: "2026-08-31T12:00:00Z",
      source_as_of: null,
      captured_at: null,
      predecessor_mapping_id: null,
      successor_mapping_id: null,
      revoked_at: "2026-08-31T12:00:00Z",
      revoke_reason: null,
    });
    vi.mocked(listMonths).mockResolvedValue([
      {
        id: 7,
        year: 2026,
        month: 8,
        status: "draft",
        snapshot_date: "2026-08-31",
        source: "manual",
      },
    ]);
    vi.mocked(applyBrokerBaseline).mockResolvedValue({
      success: true,
      selected_count: 1,
      items: [],
      error_code: null,
      message: null,
    });
  });

  it("does not auto-select and requires every local decision before apply", async () => {
    const user = userEvent.setup();
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    expect(await screen.findByText(/101\.25/)).toBeInTheDocument();
    expect(screen.getByText("Основной счёт")).toBeInTheDocument();
    expect(screen.getByText(/Синтетическая облигация.*RU000SYNTH01/)).toBeInTheDocument();
    expect(screen.getByText("ID: 1:10")).toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox", { name: /Выбрать позицию/ });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeDisabled();

    await user.click(checkbox);
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeDisabled();
    for (const label of ["Решение средней стоимости", "Решение рыночной цены", "Решение НКД"]) {
      await user.selectOptions(screen.getByLabelText(new RegExp(label)), "keep_existing");
    }
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeEnabled();
  });

  it("clears review state on preview_changed and sends only confirmed selections", async () => {
    const user = userEvent.setup();
    vi.mocked(applyBrokerBaseline).mockResolvedValueOnce({
      success: false,
      selected_count: 0,
      items: [],
      error_code: "preview_changed",
      message: "preview changed",
    });
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    await user.click(await screen.findByRole("checkbox", { name: /Выбрать позицию/ }));
    for (const label of ["Решение средней стоимости", "Решение рыночной цены", "Решение НКД"]) {
      await user.selectOptions(screen.getByLabelText(new RegExp(label)), "keep_existing");
    }
    await user.click(screen.getByRole("button", { name: "Применить выбранный базовый срез" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить базовый срез" }));
    await waitFor(() => expect(applyBrokerBaseline).toHaveBeenCalledTimes(1));
    expect(applyBrokerBaseline).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ baseline_date: "2026-08-31" }),
    );
    expect(screen.queryByRole("checkbox", { name: /Выбрать позицию/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("preview changed");
  });

  it("uses owner-facing availability and mapping labels", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue({
      ...preview(),
      status: "non_applicable",
      eligible_for_apply: false,
      snapshot_status: "provider_unavailable",
      warnings: ["snapshot is not an apply-candidate: status=provider_unavailable"],
      instruments: [
        {
          provider_instrument_id: "already-resolved",
          isin: "RU000SYNTH01",
          ticker: null,
          display_name: "Already resolved",
          hermes_instrument_id: 10,
          status: "matched",
          reason: null,
        },
        {
          provider_instrument_id: "needs-owner",
          isin: null,
          ticker: null,
          display_name: "Needs owner",
          hermes_instrument_id: null,
          status: "unmatched",
          reason: "instrument_unmatched",
        },
      ],
    });
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    const month = await screen.findByLabelText("Отчётный месяц");
    expect(screen.getByRole("option", { name: /Август.*2026.*Черновик/ })).toBeInTheDocument();
    await user.selectOptions(month, "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(
      await screen.findByText(
        "Не удалось подключиться к Альфа PRO. Убедитесь, что терминал запущен и выполнен вход.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Инструменты Alfa → Hermes")).toBeInTheDocument();
    expect(screen.getByLabelText(/needs-owner/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/already-resolved/)).toBeNull();
    expect(screen.queryByText("Provider evidence")).toBeNull();
    expect(screen.queryByText("matched")).toBeNull();
    expect(screen.queryByText("non_applicable")).toBeNull();
    expect(screen.queryByText(/snapshot is not an apply-candidate/)).toBeNull();

    await user.selectOptions(screen.getByLabelText(/needs-owner/), "10");
    expect(
      screen.getByText(
        "Сопоставление изменилось. Получите обновлённые данные из Альфа PRO перед выбором и применением.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Обнови preview/)).toBeNull();
  });

  it("explains unknown provider layout and keeps apply unavailable", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue({
      ...preview(),
      status: "non_applicable",
      eligible_for_apply: false,
      snapshot_status: "compatibility_error",
      diagnostics: {
        ...preview().diagnostics,
        snapshot_status: "compatibility_error",
        eligible_for_apply: false,
        compatibility_state: "unknown",
        failure_class: "layout",
        failure_codes: ["missing_required_entity_field"],
      },
      diagnostic_report: "compatibility_state: unknown\nfailure_class: layout\n",
    });
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(
      await screen.findByText(
        "Не удалось однозначно распознать формат данных Альфа PRO. Применение отключено; передайте безопасную диагностику разработчику.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeDisabled();
  });

  it("shows reused mappings and disables IsMoney rows", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        accounts: [
          {
            provider_account_id: "SYN-ACCOUNT-001",
            hermes_account_id: 1,
            status: "matched",
            reason: null,
            classification: "reused",
          },
        ],
        positions: [
          { ...matched, is_money: true, fingerprint: "fp-money", provider_quantity: "1000" },
        ],
      }),
    );
    vi.mocked(listBrokerIdentityMappings).mockResolvedValue([
      {
        mapping_id: 9,
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
      },
    ]);
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    expect(await screen.findByText("Уже подтверждено")).toBeInTheDocument();
    expect(screen.getByText("Дата базового среза")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2026-08-31")).toBeInTheDocument();
    expect(screen.getByText(/Денежная строка Alfa/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Выбрать позицию/ })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Отозвать сопоставление счёта" }),
    ).toBeInTheDocument();
  });

  it("shows and copies the safe diagnostic artifact", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(await screen.findByText("safe synthetic diagnostics")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Скопировать диагностику" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("safe synthetic diagnostics\n"));
    expect(screen.getByRole("button", { name: "Скопировано" })).toBeInTheDocument();
  });
});
