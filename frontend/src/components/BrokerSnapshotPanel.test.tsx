import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyBrokerSnapshot, previewBrokerSnapshot } from "../api/brokerSnapshot";
import { listMonths } from "../api/months";
import type { Account, Instrument } from "../api/types";
import { BrokerSnapshotPanel } from "./BrokerSnapshotPanel";

vi.mock("../api/brokerSnapshot", () => ({
  applyBrokerSnapshot: vi.fn(),
  previewBrokerSnapshot: vi.fn(),
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
    error_code: null,
    message: null,
    ...overrides,
  };
}

describe("BrokerSnapshotPanel explicit owner decisions", () => {
  beforeEach(() => {
    vi.mocked(previewBrokerSnapshot).mockResolvedValue(preview());
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
    vi.mocked(applyBrokerSnapshot).mockResolvedValue({
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
    expect(screen.getByRole("button", { name: "Применить выбранное" })).toBeDisabled();

    await user.click(checkbox);
    expect(screen.getByRole("button", { name: "Применить выбранное" })).toBeDisabled();
    for (const label of ["Решение средней стоимости", "Решение рыночной цены", "Решение НКД"]) {
      await user.selectOptions(screen.getByLabelText(new RegExp(label)), "keep_existing");
    }
    expect(screen.getByRole("button", { name: "Применить выбранное" })).toBeEnabled();
  });

  it("clears review state on preview_changed and sends only confirmed selections", async () => {
    const user = userEvent.setup();
    vi.mocked(applyBrokerSnapshot).mockResolvedValueOnce({
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
    await user.click(screen.getByRole("button", { name: "Применить выбранное" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить и применить" }));
    await waitFor(() => expect(applyBrokerSnapshot).toHaveBeenCalledTimes(1));
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
    expect(screen.getByText("Инструменты, требующие сопоставления")).toBeInTheDocument();
    expect(screen.getByLabelText(/needs-owner/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/already-resolved/)).toBeNull();
    expect(screen.queryByText("Provider evidence")).toBeNull();
    expect(screen.queryByText("matched")).toBeNull();
    expect(screen.queryByText("non_applicable")).toBeNull();
    expect(screen.queryByText(/snapshot is not an apply-candidate/)).toBeNull();
  });
});
