import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { ApiClientError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import {
  applyPayouts,
  listPayoutCalendar,
  previewPayouts,
  type PayoutPreview,
} from "../api/payouts";
import { listPositions } from "../api/positions";
import { rub } from "../lib/money";
import { PayoutsPage } from "./PayoutsPage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/positions", () => ({ listPositions: vi.fn() }));
vi.mock("../api/payouts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/payouts")>();
  return {
    ...actual,
    previewPayouts: vi.fn(),
    applyPayouts: vi.fn(),
    listPayoutCalendar: vi.fn(),
  };
});

const draftMonth = {
  id: 7,
  year: 2032,
  month: 3,
  status: "draft" as const,
  snapshot_date: "2032-03-31",
  source: "manual",
};

const account = {
  id: 11,
  name: "Брокерский",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const instrument = {
  id: 21,
  name: "ОФЗ 26248",
  instrument_type: "bond",
  isin: "RU000A106A86",
  ticker: "SU26248RMFS3",
  moex_secid: null,
  currency: "RUB",
  nominal_value: rub("1000.00"),
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const position = {
  id: 44,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  quantity: "10",
  average_cost_per_unit: rub("900.00"),
  market_price_per_unit: rub("950.00"),
  market_value: rub("9500.00"),
  cost_basis: rub("9000.00"),
  unrealized_result: rub("500.00"),
  accrued_interest: rub("20.00"),
  price_source: "manual",
  price_date: "2032-03-31",
  notes: null,
  updated_at: "2032-03-31T12:00:00Z",
};

const providerUid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";

const newAndRevisedPreview: PayoutPreview = {
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  position_snapshot_id: 44,
  quantity: "10",
  provider: "t_invest",
  instrument_uid: providerUid,
  rows: [
    {
      status: "new",
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      position_snapshot_id: 44,
      quantity: "10",
      provider: "t_invest",
      instrument_uid: providerUid,
      event_kind: "coupon",
      identity_key: "n:3",
      payment_date: "2032-06-15",
      per_unit_amount: "40.125",
      currency: "RUB",
      total_amount: rub("401.25"),
      provider_status: null,
      source_method: "GetBondCoupons",
      applied_payout_id: null,
      applied_lifecycle: null,
      manual_candidate_ids: [],
      reconciliation: null,
      selectable: true,
      default_selected: true,
      fingerprint: "fp-new",
      message: null,
    },
    {
      status: "revised",
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      position_snapshot_id: 44,
      quantity: "10",
      provider: "t_invest",
      instrument_uid: providerUid,
      event_kind: "redemption",
      identity_key: "mty:1",
      payment_date: "2033-01-20",
      per_unit_amount: "1000",
      currency: "RUB",
      total_amount: rub("10000.00"),
      provider_status: null,
      source_method: "GetBondEvents",
      applied_payout_id: 90,
      applied_lifecycle: "active",
      manual_candidate_ids: [],
      reconciliation: null,
      selectable: true,
      default_selected: false,
      fingerprint: "fp-revised",
      message: null,
    },
  ],
};

const mergedCalendar = [
  {
    year: 2032,
    month: 6,
    coupon: rub("401.25"),
    dividend: rub("0"),
    interest: rub("0"),
    redemption: rub("10000.00"),
    other: rub("0"),
    passive_net: rub("401.25"),
    total_net: rub("10401.25"),
    items: [
      {
        source_kind: "manual",
        source_id: 31,
        expected_date: "2032-06-10",
        flow_type: "coupon",
        account_id: 11,
        account_name: "Брокерский",
        instrument_id: 21,
        instrument_name: "ОФЗ 26248",
        expected_net_amount: rub("100.00"),
        is_confirmed: false,
        is_approximate: false,
        manual_source: "manual",
        provider: null,
        provider_instrument_uid: null,
        provider_identity_key: null,
        provider_lifecycle: null,
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: null,
      },
      {
        source_kind: "provider",
        source_id: 90,
        expected_date: "2032-06-15",
        flow_type: "redemption",
        account_id: 11,
        account_name: "Брокерский",
        instrument_id: 21,
        instrument_name: "ОФЗ 26248",
        expected_net_amount: rub("10000.00"),
        is_confirmed: null,
        is_approximate: true,
        manual_source: null,
        provider: "t_invest",
        provider_instrument_uid: providerUid,
        provider_identity_key: "mty:1",
        provider_lifecycle: "active",
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: 90,
      },
    ],
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <PayoutsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listMonths).mockResolvedValue([draftMonth]);
  vi.mocked(listAccounts).mockResolvedValue([account]);
  vi.mocked(listInstruments).mockResolvedValue([instrument]);
  vi.mocked(listPositions).mockResolvedValue([position]);
  vi.mocked(listPayoutCalendar).mockResolvedValue(mergedCalendar);
  vi.mocked(previewPayouts).mockResolvedValue(newAndRevisedPreview);
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [],
    error_code: null,
    message: null,
  });
});

describe("PayoutsPage", () => {
  it("loads only local context/calendar on render and waits for an explicit payout preview click", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Автовыплаты" })).toBeInTheDocument();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });

    expect(previewPayouts).not.toHaveBeenCalled();
    expect(applyPayouts).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(listPayoutCalendar).toHaveBeenCalledWith(7, "v1", expect.anything()),
    );
  });

  it("previews the exact selected local position and respects backend default_selected", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });

    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    await waitFor(() =>
      expect(previewPayouts).toHaveBeenCalledWith(7, {
        account_id: 11,
        instrument_id: 21,
        position_snapshot_id: 44,
        forecast_version: "v1",
      }),
    );

    expect(screen.getByRole("checkbox", { name: "Выбрать выплату coupon" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать выплату redemption" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Применить выбранные (1)" })).toBeEnabled();
    expect(screen.queryByText(providerUid)).not.toBeInTheDocument();
  });

  it("explains a missing accepted T-Invest mapping instead of a generic validation phrase", async () => {
    const user = userEvent.setup();
    vi.mocked(previewPayouts).mockRejectedValue(
      new ApiClientError(422, {
        code: "payout_mapping_required",
        message: "instrument has no accepted payout provider mapping",
        details: [],
      }),
    );
    renderPage();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });
    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    expect(await screen.findByText(/принятого источника T-Invest/)).toBeInTheDocument();
    expect(screen.getByText(/сопоставление/)).toBeInTheDocument();
    expect(screen.queryByText("Проверь введённые данные.")).not.toBeInTheDocument();
    expect(screen.queryByText(/instrument has no accepted/)).not.toBeInTheDocument();
  });

  it("requires an explicit duplicate decision and manual target without auto-picking multiple candidates", async () => {
    const user = userEvent.setup();
    vi.mocked(previewPayouts).mockResolvedValue({
      ...newAndRevisedPreview,
      rows: [
        {
          ...newAndRevisedPreview.rows[0],
          status: "possible_manual_duplicate",
          default_selected: false,
          manual_candidate_ids: [31, 32],
          fingerprint: "fp-duplicate",
        },
      ],
    });
    renderPage();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });
    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));

    const checkbox = await screen.findByRole("checkbox", { name: "Выбрать выплату coupon" });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);

    const decision = screen.getByRole("combobox", { name: "Решение для дубля 1" });
    const target = screen.getByRole("combobox", { name: "Ручная запись для дубля 1" });
    expect(decision).toHaveValue("");
    expect(target).toHaveValue("");
    expect(screen.getByRole("button", { name: "Применить выбранные (0)" })).toBeDisabled();

    await user.selectOptions(decision, "count_provider");
    await user.selectOptions(target, "32");
    const applyButton = screen.getByRole("button", { name: "Применить выбранные (1)" });
    expect(applyButton).toBeEnabled();
    await user.click(applyButton);

    await waitFor(() =>
      expect(applyPayouts).toHaveBeenCalledWith(7, {
        account_id: 11,
        instrument_id: 21,
        position_snapshot_id: 44,
        forecast_version: "v1",
        rows: [
          expect.objectContaining({
            fingerprint: "fp-duplicate",
            manual_duplicate_decision: {
              expected_cash_flow_id: 32,
              counting_decision: "count_provider",
            },
          }),
        ],
      }),
    );
    await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledTimes(2));
    expect(previewPayouts).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
  });

  it("allows closed-month preview but exposes no apply control", async () => {
    const user = userEvent.setup();
    vi.mocked(listMonths).mockResolvedValue([{ ...draftMonth, status: "closed" }]);
    renderPage();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });

    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    expect(await screen.findByText(/Месяц закрыт/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Применить выбранные/ })).not.toBeInTheDocument();
  });

  it("drops a stale preview on preview_changed and does not claim success", async () => {
    const user = userEvent.setup();
    vi.mocked(applyPayouts).mockResolvedValue({
      success: false,
      selected_count: 1,
      items: [],
      error_code: "preview_changed",
      message: "stale",
    });
    renderPage();
    await screen.findByRole("option", { name: /ОФЗ 26248/ });
    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    await screen.findByRole("checkbox", { name: "Выбрать выплату coupon" });

    await user.click(screen.getByRole("button", { name: "Применить выбранные (1)" }));
    expect(await screen.findByText(/Предпросмотр изменился/)).toBeInTheDocument();
    expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
    expect(previewPayouts).toHaveBeenCalledTimes(1);
  });

  it("shows merged manual/provider provenance and keeps redemption visibly outside passive income", async () => {
    renderPage();

    expect(await screen.findByText("Вручную")).toBeInTheDocument();
    expect(screen.getByText("T-Invest")).toBeInTheDocument();
    expect(screen.getByText("возврат капитала, не доход")).toBeInTheDocument();
    expect(screen.getByText(/весь денежный поток/)).toBeInTheDocument();
  });
});
