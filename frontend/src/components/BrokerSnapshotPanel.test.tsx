import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listBrokerIdentityMappings,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import { applyBrokerBaseline, previewBrokerSnapshot } from "../api/brokerSnapshot";
import { createInstrument } from "../api/instruments";
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

vi.mock("../api/instruments", () => ({
  createInstrument: vi.fn(),
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
  provider_quantity: "300.000000",
  hermes_quantity: "299.500000",
  quantity_difference: "-0.500000",
  quantity_equal: false,
  fingerprint: "fp-matched",
  reason: null,
  warnings: [],
  provider_broker_unit_price: "101.25000000000001",
  provider_accrued_interest_nkd: "3.50000000000001",
  provider_unrealized_result: "12.00000000000001",
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
    vi.mocked(previewBrokerSnapshot).mockReset();
    vi.mocked(applyBrokerBaseline).mockReset();
    vi.mocked(createInstrument).mockReset();
    vi.mocked(listBrokerIdentityMappings).mockReset();
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

  it("does not auto-select rows and defaults matched decisions to local values", async () => {
    const user = userEvent.setup();
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    expect(await screen.findByText(/101,25/)).toBeInTheDocument();
    expect(screen.getByText("Данные Alfa PRO", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/количество\s+300/)).toBeInTheDocument();
    expect(screen.getByText(/НКД Alfa PRO.*3,5/)).toBeInTheDocument();
    expect(screen.getByText(/P&L Alfa PRO.*12 ₽/)).toBeInTheDocument();
    expect(screen.getByText("Основной счёт")).toBeInTheDocument();
    expect(screen.getByText(/Синтетическая облигация.*RU000SYNTH01/)).toBeInTheDocument();
    expect(screen.queryByText("ID: 1:10")).toBeNull();
    const checkbox = screen.getByRole("checkbox", { name: /Выбрать позицию/ });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeDisabled();

    await user.click(checkbox);
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeEnabled();
    for (const label of ["Решение средней стоимости", "Решение рыночной цены", "Решение НКД"]) {
      expect(screen.getByLabelText(new RegExp(label))).toHaveValue("keep_existing");
    }
    expect(screen.getAllByText("Оставить текущее значение Hermes").length).toBeGreaterThan(0);
    expect(screen.queryByText("Оставить текущую")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Применить выбранный базовый срез" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить базовый срез" }));
    await waitFor(() => expect(applyBrokerBaseline).toHaveBeenCalledTimes(1));
    expect(vi.mocked(applyBrokerBaseline).mock.calls[0][1].selections[0]).toMatchObject({
      action: "update",
      average_cost: { action: "keep_existing" },
      market_price: { action: "keep_existing" },
      accrued_interest: { action: "keep_existing" },
    });
  });

  it("keeps the close month selected and shows a compact partial preview only after the explicit action", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        status: "conflicts",
        positions: [
          matched,
          {
            ...matched,
            instrument_id: 20,
            instrument_name: "Нерешённый инструмент",
            status: "conflict",
            fingerprint: null,
          },
        ],
      }),
    );

    render(
      <BrokerSnapshotPanel
        accounts={[account]}
        initialMonthId={7}
        instruments={[instrument]}
        monthlyClose
      />,
    );
    const monthSelect = await screen.findByLabelText("Отчётный месяц");
    expect(monthSelect).toHaveValue("7");
    expect(monthSelect).toBeDisabled();
    expect(previewBrokerSnapshot).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(
      await screen.findByRole("status", { name: "Результат шага Alfa PRO" }),
    ).toHaveTextContent("Частичный результат");
    expect(screen.getByRole("status", { name: "Результат шага Alfa PRO" })).toHaveTextContent(
      "Требуют внимания",
    );
    expect(screen.queryByText("ID: 1:10")).not.toBeInTheDocument();
    expect(previewBrokerSnapshot).toHaveBeenCalledWith(7, { accounts: [], instruments: [] });
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

  it("keeps safe rows selectable when another row is conflicted", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        status: "conflicts",
        eligible_for_apply: true,
        positions: [
          matched,
          {
            ...matched,
            instrument_id: 20,
            instrument_name: "Спорный инструмент",
            status: "conflict",
            fingerprint: "must-not-apply",
            reason: "duplicate provider rows map to the same canonical position",
          },
        ],
      }),
    );
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(
      await screen.findByText("Есть нерешённые строки; безопасные доступны"),
    ).toBeInTheDocument();
    expect(screen.getByText(/остальные останутся без изменений/)).toBeInTheDocument();
    const safeCheckbox = screen.getByRole("checkbox", { name: "Выбрать позицию 1:10" });
    const conflictedCheckbox = screen.getByRole("checkbox", { name: "Выбрать позицию 1:20" });
    expect(safeCheckbox).toBeEnabled();
    expect(conflictedCheckbox).toBeDisabled();

    await user.click(safeCheckbox);
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Применить выбранный базовый срез" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить базовый срез" }));
    await waitFor(() => expect(applyBrokerBaseline).toHaveBeenCalledTimes(1));
    const selections = vi.mocked(applyBrokerBaseline).mock.calls[0][1].selections;
    expect(selections).toHaveLength(1);
    expect(selections[0]).toMatchObject({ account_id: 1, instrument_id: 10 });
  });

  it("keeps baseline apply blocked for a closed month", async () => {
    const user = userEvent.setup();
    vi.mocked(listMonths).mockResolvedValueOnce([
      {
        id: 7,
        year: 2026,
        month: 8,
        status: "closed",
        snapshot_date: "2026-08-31",
        source: "manual",
      },
    ]);
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    expect(
      await screen.findByText("Утверждённый месяц нельзя менять. Сначала откройте его заново."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    const checkbox = await screen.findByRole("checkbox", { name: "Выбрать позицию 1:10" });
    await user.click(checkbox);
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeDisabled();
    expect(applyBrokerBaseline).not.toHaveBeenCalled();
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
    expect(screen.getByLabelText("Needs owner")).toBeInTheDocument();
    expect(screen.queryByLabelText(/already-resolved/)).toBeNull();
    expect(screen.queryByText("Provider evidence")).toBeNull();
    expect(screen.queryByText("matched")).toBeNull();
    expect(screen.queryByText("non_applicable")).toBeNull();
    expect(screen.queryByText(/snapshot is not an apply-candidate/)).toBeNull();

    await user.selectOptions(screen.getByLabelText("Needs owner"), "10");
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

  it("shows readable mapping identities and account instrument hints", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        accounts: [
          {
            provider_account_id: "opaque-account-1",
            hermes_account_id: null,
            status: "unmatched",
            reason: "no explicit owner mapping for provider account",
            section_codes: ["RUB"],
            observed_instruments: [
              { display_name: "ОФЗ 26240", isin: "RU000A103BR0", ticker: "SU26240RMFS8" },
            ],
          },
        ],
        instruments: [
          {
            provider_instrument_id: "opaque-instrument-1",
            isin: "RU000A0TEST01",
            ticker: "TEST",
            display_name: "Тестовая облигация",
            hermes_instrument_id: null,
            status: "unmatched",
            reason: "no Hermes instrument with this ISIN",
          },
        ],
      }),
    );
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(
      await screen.findByLabelText(
        "Раздел RUB · Инструменты: ОФЗ 26240 · RU000A103BR0 · SU26240RMFS8",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Источник: opaque-account-1")).toBeNull();
    expect(screen.getByLabelText("Тестовая облигация · RU000A0TEST01 · TEST")).toBeInTheDocument();
    expect(screen.queryByText("Источник: opaque-instrument-1")).toBeNull();
    const sourceDetails = screen.getAllByText("Подробности источника");
    expect(sourceDetails).toHaveLength(2);
    await user.click(sourceDetails[0]);
    expect(screen.getByText("Идентификатор счёта Alfa PRO: opaque-account-1")).toBeVisible();
    await user.click(sourceDetails[1]);
    expect(
      screen.getByText("Идентификатор инструмента Alfa PRO: opaque-instrument-1"),
    ).toBeVisible();
  });

  it("allows provider-only create without accrued interest and states mapping persist", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        positions: [
          {
            ...matched,
            status: "provider_only",
            hermes_quantity: null,
            fingerprint: "fp-create",
          },
        ],
      }),
    );
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    await user.click(await screen.findByRole("checkbox", { name: /Выбрать позицию/ }));
    await user.selectOptions(screen.getByLabelText(/Решение средней стоимости/), "replace");
    const averageCost = screen.getByLabelText(/Локальная средняя стоимость/);
    expect(averageCost).toHaveValue("");
    await user.type(averageCost, "100.00");
    await user.selectOptions(screen.getByLabelText(/Решение рыночной цены/), "replace");
    const marketPrice = screen.getByLabelText(/Локальная рыночная цена/);
    expect(marketPrice).toHaveValue("");
    await user.type(marketPrice, "150.00");
    await user.type(screen.getByLabelText(/Дата локальной цены/), "2026-08-31");
    await user.selectOptions(screen.getByLabelText(/Источник локальной цены/), "manual");
    const accrued = screen.getByLabelText(/Решение НКД/) as HTMLSelectElement;
    expect(Array.from(accrued.options, (option) => option.value)).toEqual(["", "replace"]);
    expect(accrued).toHaveDisplayValue("— не задавать —");
    expect(screen.getByRole("button", { name: "Применить выбранный базовый срез" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Применить выбранный базовый срез" }));
    expect(
      screen.getByText(/Новые сопоставления выбранных строк сохранятся вместе с количествами/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Подтвердить базовый срез" }));
    await waitFor(() => expect(applyBrokerBaseline).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(applyBrokerBaseline).mock.calls[0][1];
    expect(payload.selections).toHaveLength(1);
    expect(payload.selections[0]).toMatchObject({
      action: "create",
      average_cost: { action: "replace", value: "100.00" },
      market_price: {
        action: "replace",
        market_price_per_unit: "150.00",
        price_date: "2026-08-31",
        price_source: "manual",
      },
    });
    expect(payload.selections[0].accrued_interest).toBeUndefined();
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
        instruments: [
          {
            provider_instrument_id: "MONEY-1",
            isin: null,
            ticker: "RUB",
            display_name: "Денежный остаток",
            hermes_instrument_id: null,
            status: "unmatched",
            reason: null,
            is_money: true,
          },
        ],
        positions: [
          {
            ...matched,
            is_money: true,
            fingerprint: null,
            provider_instrument_id: "MONEY-1",
            provider_quantity: "1000.000000",
          },
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
    expect(screen.queryByText("Инструменты Alfa → Hermes")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/MONEY-1/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Отозвать сопоставление счёта" }),
    ).toBeInTheDocument();
  });

  it("groups positions and lets the owner select all applicable rows explicitly", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        positions: [
          matched,
          {
            ...matched,
            instrument_id: 20,
            instrument_name: "Вторая облигация",
            instrument_isin: "RU000SYNTH02",
            fingerprint: "fp-second",
          },
        ],
      }),
    );
    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));

    expect(await screen.findByText("Счёт Hermes: Основной счёт")).toBeInTheDocument();
    const checkboxes = screen.getAllByRole("checkbox", { name: /Выбрать позицию/ });
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes.every((checkbox) => !(checkbox as HTMLInputElement).checked)).toBe(true);

    await user.click(screen.getByRole("button", { name: "Выбрать все применимые" }));
    expect(
      screen
        .getAllByRole("checkbox", { name: /Выбрать позицию/ })
        .every((checkbox) => (checkbox as HTMLInputElement).checked),
    ).toBe(true);
    expect(screen.getByText("Выбрано: 2 из 2 применимых")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Снять выбор" }));
    expect(
      screen
        .getAllByRole("checkbox", { name: /Выбрать позицию/ })
        .every((checkbox) => !(checkbox as HTMLInputElement).checked),
    ).toBe(true);
  });

  it("creates a provider-only instrument only after explicit owner confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(
      preview({
        instruments: [
          {
            provider_instrument_id: "needs-owner",
            isin: "RU000A103BR0",
            ticker: "SU26240RMFS8",
            display_name: "ОФЗ 26240",
            hermes_instrument_id: null,
            status: "unmatched",
            reason: "instrument_unmatched",
          },
        ],
      }),
    );
    vi.mocked(createInstrument).mockResolvedValue({
      id: 42,
      name: "ОФЗ владельца",
      instrument_type: "bond",
      isin: "RU000A103BR0",
      ticker: "SU26240RMFS8",
      moex_secid: null,
      currency: "RUB",
      nominal_value: null,
      is_active: true,
      manual_price_allowed: true,
      notes: null,
    });

    render(<BrokerSnapshotPanel accounts={[account]} instruments={[instrument]} />);
    await user.selectOptions(await screen.findByLabelText("Отчётный месяц"), "7");
    await user.click(screen.getByRole("button", { name: "Получить данные из Альфа PRO" }));
    await user.click(await screen.findByRole("button", { name: "Создать инструмент из Alfa PRO" }));

    expect(
      await screen.findByRole("dialog", { name: "Создать инструмент из Alfa PRO" }),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("ОФЗ 26240")).toBeInTheDocument();
    expect(screen.getByDisplayValue("RU000A103BR0")).toBeInTheDocument();
    expect(screen.getByDisplayValue("SU26240RMFS8")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Название"));
    await user.type(screen.getByLabelText("Название"), "ОФЗ владельца");
    await user.click(screen.getByRole("button", { name: /^Создать$/ }));

    await waitFor(() => expect(createInstrument).toHaveBeenCalledTimes(1));
    expect(createInstrument).toHaveBeenCalledWith({
      name: "ОФЗ владельца",
      instrument_type: "bond",
      isin: "RU000A103BR0",
      ticker: "SU26240RMFS8",
      moex_secid: null,
      currency: "RUB",
      nominal_value: null,
      is_active: true,
      manual_price_allowed: true,
      notes: null,
    });
    expect(
      await screen.findByText(/Инструмент создан и выбран для будущего явного сопоставления/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Получите обновлённые данные из Альфа PRO/)).toBeInTheDocument();
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
