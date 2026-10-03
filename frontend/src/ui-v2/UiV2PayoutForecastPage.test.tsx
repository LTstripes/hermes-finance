import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { listExpectedFlows } from "../api/expectedFlows";
import { listInstruments } from "../api/instruments";
import { listInvestmentFlows } from "../api/investmentFlows";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import {
  applyPayouts,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  type PayoutApplyItem,
  type PayoutBatchPreview,
  type PayoutPreview,
  previewPayouts,
  previewPayoutsBatch,
} from "../api/payouts";
import { listPositions } from "../api/positions";
import { applyStatement, inspectStatement, prepareStatement } from "../api/statementImport";
import type { CloseReadiness, PositionSnapshot, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import UiV2PayoutForecastPage from "./UiV2PayoutForecastPage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
  getMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
}));
vi.mock("../api/positions", () => ({ listPositions: vi.fn() }));
vi.mock("../api/expectedFlows", () => ({ listExpectedFlows: vi.fn() }));
vi.mock("../api/investmentFlows", () => ({ listInvestmentFlows: vi.fn() }));
vi.mock("../api/statementImport", () => ({
  inspectStatement: vi.fn(),
  prepareStatement: vi.fn(),
  applyStatement: vi.fn(),
}));
vi.mock("../api/payouts", () => ({
  previewPayouts: vi.fn(),
  previewPayoutsBatch: vi.fn(),
  applyPayouts: vi.fn(),
  listPayoutCalendar: vi.fn(),
  getPayoutRefreshStatus: vi.fn(),
}));

const draftMonth = {
  id: 7,
  year: 2026,
  month: 8,
  status: "draft",
  snapshot_date: "2026-08-31",
  source: "manual",
} as ReportingMonth;

const closedMonth = {
  id: 8,
  year: 2026,
  month: 7,
  status: "closed",
  snapshot_date: "2026-07-31",
  source: "manual",
} as ReportingMonth;

const position = {
  id: 11,
  reporting_month_id: 7,
  account_id: 1,
  instrument_id: 10,
  quantity: "10",
} as PositionSnapshot;

const secondPosition = {
  id: 12,
  reporting_month_id: 7,
  account_id: 1,
  instrument_id: 10,
  quantity: "5",
} as PositionSnapshot;

function money(amount: string) {
  return { amount, currency: "RUB" };
}

const calendarFixture = [
  {
    year: 2026,
    month: 9,
    coupon: money("100.00"),
    dividend: money("200.00"),
    interest: money("0.00"),
    redemption: money("1000.00"),
    other: money("0.00"),
    passive_net: money("300.00"),
    total_net: money("1300.00"),
    items: [
      {
        source_kind: "manual",
        source_id: 1,
        expected_date: "2026-09-10",
        flow_type: "coupon",
        account_id: 1,
        account_name: "Synthetic",
        instrument_id: 10,
        instrument_name: "Bond",
        expected_net_amount: money("100.00"),
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
        source_id: 2,
        expected_date: "2026-09-10",
        flow_type: "coupon",
        account_id: 1,
        account_name: "Synthetic",
        instrument_id: 10,
        instrument_name: "Bond",
        expected_net_amount: money("100.00"),
        is_confirmed: null,
        is_approximate: false,
        manual_source: null,
        provider: "t_invest",
        provider_instrument_uid: "UID-1",
        provider_identity_key: "K-1",
        provider_lifecycle: "active",
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: null,
      },
    ],
  },
];
calendarFixture[0].items.push({
  ...calendarFixture[0].items[0],
  source_id: 3,
  flow_type: "redemption",
  expected_date: "2026-09-15",
  expected_net_amount: money("1000.00"),
});

const previewFixture: PayoutPreview = {
  reporting_month_id: 7,
  account_id: 1,
  instrument_id: 10,
  position_snapshot_id: 11,
  quantity: "10",
  provider: "t_invest",
  instrument_uid: "UID-1",
  rows: [
    {
      status: "new",
      reporting_month_id: 7,
      account_id: 1,
      instrument_id: 10,
      position_snapshot_id: 11,
      quantity: "10",
      provider: "t_invest",
      instrument_uid: "UID-1",
      event_kind: "coupon",
      identity_key: "K-1",
      payment_date: "2026-09-10",
      per_unit_amount: "10.00",
      currency: "RUB",
      total_amount: money("100.00"),
      provider_status: "ok",
      source_method: "GetBondCoupons",
      applied_payout_id: null,
      applied_lifecycle: null,
      manual_candidate_ids: [],
      reconciliation: null,
      selectable: true,
      default_selected: true,
      fingerprint: "fp-1",
      message: null,
    },
  ],
};

const statementFile = new File(["synthetic statement pdf"], "synthetic-statement.pdf", {
  type: "application/pdf",
});

const statementInspect = {
  document_sha256: "sha-1",
  status: "applicable",
  rows: [
    {
      status: "matched",
      provider_account_ref: "synthetic-broker",
      isin: "RU000SYNTH01",
      event_kind: "coupon",
      record_date: "2026-08-01",
      event_date: "2026-08-03",
      reason: null,
    },
  ],
  warnings: [],
  reason: null,
};

const statementPreparation = {
  provider: "alfa_pdf",
  document_sha256: "sha-1",
  status: "applicable",
  warnings: [],
  reason: null,
  rows: [
    {
      status: "matched",
      duplicate_class: null,
      provider_account_ref: "synthetic-broker",
      expected_hermes_account_id: 1,
      expected_hermes_instrument_id: 10,
      natural_identity: "synthetic-row-1",
      material_fingerprint: "fp-synthetic-1",
      expected_candidate_ids: [],
      candidates: [],
      isin: "RU000SYNTH01",
      event_kind: "coupon",
      record_date: "2026-08-01",
      event_date: "2026-08-03",
      quantity: "10",
      per_unit: "10.00",
      gross_amount: "12450.00",
      gross_currency: "RUB",
      tax_amount: "1618.50",
      tax_available: true,
      tax_rate: "13.00",
      net_amount: "10831.50",
      net_currency: "RUB",
      reason: null,
    },
  ],
};

const spanningStatementPreparation = {
  ...statementPreparation,
  rows: [
    statementPreparation.rows[0],
    {
      ...statementPreparation.rows[0],
      natural_identity: "synthetic-sep",
      material_fingerprint: "fp-sep",
      event_date: "2026-09-03",
      record_date: "2026-09-01",
    },
  ],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listMonths).mockResolvedValue([draftMonth, closedMonth]);
  vi.mocked(getMonth).mockImplementation(async (id: number) =>
    id === 8 ? closedMonth : draftMonth,
  );
  vi.mocked(getCloseReadiness).mockResolvedValue({
    ...draftMonth,
    can_close: false,
    items: [],
  } as CloseReadiness);
  vi.mocked(listAccounts).mockResolvedValue([
    { id: 1, name: "Synthetic", status: "active" },
  ] as never);
  vi.mocked(listInstruments).mockResolvedValue([
    { id: 10, name: "Bond", ticker: "B", instrument_type: "bond", status: "active" },
  ] as never);
  vi.mocked(listPositions).mockImplementation(async (monthId: number) =>
    monthId === 7 ? [position] : [],
  );
  vi.mocked(listPayoutCalendar).mockResolvedValue(structuredClone(calendarFixture) as never);
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 7,
    positions_changed: 0,
    items: [],
  } as never);
  vi.mocked(listExpectedFlows).mockResolvedValue([]);
  vi.mocked(listInvestmentFlows).mockResolvedValue([
    {
      id: 501,
      reporting_month_id: 7,
      account_id: 1,
      instrument_id: 10,
      flow_type: "coupon",
      event_date: "2026-08-03",
      gross_amount: money("12450.00"),
      tax_amount: money("1618.50"),
      commission_amount: money("0.00"),
      net_amount: money("10831.50"),
      currency: "RUB",
      source: "alfa_pdf",
      notes: null,
      statement_link: {
        applied_statement_event_id: 91,
        link_mode: "statement_created",
        status: "active",
      },
    } as never,
  ]);
  vi.mocked(inspectStatement).mockResolvedValue(structuredClone(statementInspect) as never);
  vi.mocked(prepareStatement).mockResolvedValue(structuredClone(statementPreparation) as never);
  vi.mocked(applyStatement).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [
      {
        action: "created",
        natural_identity: "synthetic-row-1",
        applied_statement_event_id: 91,
        investment_cash_flow_id: 501,
        material_fingerprint: "fp-synthetic-1",
        revision_id: 92,
      },
    ],
    error_code: null,
    message: null,
  } as never);
  vi.mocked(previewPayouts).mockResolvedValue(structuredClone(previewFixture) as never);
  vi.mocked(previewPayoutsBatch).mockResolvedValue({
    reporting_month_id: 7,
    forecast_version: "v1",
    summary: {
      total_positions: 1,
      eligible_positions: 1,
      with_events: 1,
      without_events: 0,
      errors: 0,
      skipped: 0,
    },
    items: [
      {
        account_id: 1,
        instrument_id: 10,
        position_snapshot_id: 11,
        provider: "t_invest",
        instrument_uid: "UID-1",
        status: "previewed",
        message: null,
        preview: structuredClone(previewFixture),
      },
    ],
  } as never);
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [
      {
        payout_id: 2,
        revision_id: 1,
        revision_kind: "APPLY",
        provider: "t_invest",
        instrument_uid: "UID-1",
        event_kind: "coupon",
        identity_key: "K-1",
        lifecycle: "active",
        total_amount: money("100.00"),
        reconciliation_id: null,
        counting_decision: null,
        expected_cash_flow_id: null,
      },
    ],
    error_code: null,
    message: null,
  } as never);
});

function show(query: string) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/v2/data/payouts${query}`]}>
        <UiV2PayoutForecastPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("uses the exact month and preserves query/hash in Data navigation", async () => {
  show("?month=7&from=monthly-close-v2&monthId=7&step=future_payouts&scope=synthetic#target");
  expect(await screen.findByText("Объединённый календарь выплат")).toBeInTheDocument();
  expect(getMonth).toHaveBeenCalledWith(7);
  expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&step=future_payouts",
  );
  expect(screen.getByRole("link", { name: /^Файлы$/ })).toHaveAttribute(
    "href",
    "/v2/data/files?month=7&from=monthly-close-v2&monthId=7&step=future_payouts&scope=synthetic#target",
  );
  // Mixed calendar: passive income and principal stay distinct.
  expect(screen.getByText("возврат капитала, не доход")).toBeInTheDocument();
});

it.each(["", "?month=", "?month=bad", "?month=999", "?month=7&month=7", "?month=07"])(
  "rejects invalid explicit scope %s",
  async (query) => {
    show(query);
    expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
    expect(getMonth).not.toHaveBeenCalled();
    expect(previewPayouts).not.toHaveBeenCalled();
    expect(previewPayoutsBatch).not.toHaveBeenCalled();
    expect(applyPayouts).not.toHaveBeenCalled();
  },
);

it("mounts the tool only after the Owner explicitly selects a month", async () => {
  const user = userEvent.setup();
  show("?from=monthly-close-v2&monthId=7&step=future_payouts#target");
  expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
  expect(getMonth).not.toHaveBeenCalled();
  await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "7");
  expect(await screen.findByText("Объединённый календарь выплат")).toBeInTheDocument();
  expect(getMonth).toHaveBeenCalledWith(7);
});

it("does not call the provider on mount; local calendar loads without preview", async () => {
  show("?month=7");
  expect(await screen.findByText("Объединённый календарь выплат")).toBeInTheDocument();
  await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledWith(7, "v1"));
  expect(getPayoutRefreshStatus).toHaveBeenCalledWith(7);
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(previewPayoutsBatch).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
  // Preview is still idle: explicit button is required.
  expect(screen.getByRole("button", { name: "Проверить выплаты T-Invest" })).toBeInTheDocument();
});

it("runs explicit preview, then cancel leaves no write, confirm applies and rereads", async () => {
  const user = userEvent.setup();
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");

  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  expect(previewPayouts).toHaveBeenCalledTimes(1);
  expect(applyPayouts).not.toHaveBeenCalled();

  // Apply is a separate explicit choice behind a confirm dialog.
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Отмена" }));
  expect(applyPayouts).not.toHaveBeenCalled();
  expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(1);
  // Authoritative readback for the same exact month/version.
  await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledTimes(3));
  expect(getPayoutRefreshStatus).toHaveBeenCalledTimes(3);
  expect(listExpectedFlows).toHaveBeenCalledWith(7, "v1");
});

it("treats version change as stale preview that cannot apply", async () => {
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();

  const versionInput = screen.getByLabelText("Версия прогноза");
  fireEvent.change(versionInput, { target: { value: "v2" } });
  await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledWith(7, "v2"));
  expect(screen.queryByText("Новая")).not.toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("keeps CLOSED fail-closed: preview stays readable, apply is blocked", async () => {
  const user = userEvent.setup();
  show("?month=8");
  expect(await screen.findByText("Объединённый календарь выплат")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  // Preview itself is allowed on CLOSED; the panel explains read-only.
  expect(await screen.findByText(/Месяц закрыт\. Предпросмотр доступен/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("does not offer a return to a different close month", async () => {
  show("?month=7&from=monthly-close-v2&monthId=8&step=future_payouts");
  await screen.findByText("Объединённый календарь выплат");
  expect(screen.queryByRole("link", { name: "Вернуться к закрытию" })).not.toBeInTheDocument();
  expect(screen.getByText(/другому месяцу/)).toBeInTheDocument();
});

it("shows provider error without claiming success", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayouts).mockRejectedValue(new Error("synthetic provider failure"));
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText(/synthetic provider failure/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
  expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
});

it("clears preview when the backend reports preview_changed", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: false,
    selected_count: 1,
    items: [],
    error_code: "preview_changed",
    message: "refresh preview before applying",
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/Предпросмотр изменился/)).toBeInTheDocument();
  expect(screen.queryByText("Новая")).not.toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
});

it("rejects a single preview for a foreign position/account/instrument", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayouts).mockResolvedValue({
    ...structuredClone(previewFixture),
    account_id: 999,
    position_snapshot_id: 999,
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText(/не соответствует запрошенному/)).toBeInTheDocument();
  expect(screen.queryByText("Новая")).not.toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("rejects a batch response with the wrong forecast version", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayoutsBatch).mockResolvedValue({
    reporting_month_id: 7,
    forecast_version: "foreign",
    summary: {
      total_positions: 1,
      eligible_positions: 1,
      with_events: 1,
      without_events: 0,
      errors: 0,
      skipped: 0,
    },
    items: [],
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  expect(await screen.findByText(/не соответствует запрошенному/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("rejects a batch response with a foreign embedded item identity", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayoutsBatch).mockResolvedValue({
    reporting_month_id: 7,
    forecast_version: "v1",
    summary: {
      total_positions: 1,
      eligible_positions: 1,
      with_events: 1,
      without_events: 0,
      errors: 0,
      skipped: 0,
    },
    items: [
      {
        account_id: 999,
        instrument_id: 999,
        position_snapshot_id: 999,
        provider: "t_invest",
        instrument_uid: "UID-1",
        status: "previewed",
        message: null,
        preview: structuredClone(previewFixture),
      },
    ],
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  expect(await screen.findByText(/не соответствует запрошенному/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("a refreshed batch item cannot replace another position", async () => {
  const user = userEvent.setup();
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  expect(await screen.findByText("Проверка завершена")).toBeInTheDocument();
  // A foreign refresh response for the same requested position is rejected
  // and the original batch item keeps its own preview.
  vi.mocked(previewPayouts).mockResolvedValue({
    ...structuredClone(previewFixture),
    position_snapshot_id: 999,
    account_id: 999,
  } as never);
  await user.click(screen.getByRole("button", { name: "Развернуть всё" }));
  const refreshButtons = screen.getAllByRole("button", { name: "Обновить preview" });
  await user.click(refreshButtons[0]);
  expect(await screen.findByText(/не соответствует запрошенному/)).toBeInTheDocument();
  expect(screen.getByText("Проверка завершена")).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("an open single confirm cannot POST after the position changes", async () => {
  const user = userEvent.setup();
  vi.mocked(listPositions).mockResolvedValue([position, secondPosition]);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
  // Changing the selected position invalidates the pending single confirm.
  await user.selectOptions(screen.getByLabelText("Позиция"), "12");
  // The dialog closes on position change; confirming the old payload is impossible.
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("does not confirm an apply whose items mismatch the selected count", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 2,
    items: [
      {
        payout_id: 2,
        revision_id: 1,
        revision_kind: "APPLY",
        provider: "t_invest",
        instrument_uid: "UID-1",
        event_kind: "coupon",
        identity_key: "K-1",
        lifecycle: "active",
        total_amount: money("100.00"),
        reconciliation_id: null,
        counting_decision: null,
        expected_cash_flow_id: null,
      },
    ],
    error_code: null,
    message: null,
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 2/)).not.toBeInTheDocument();
});

it("does not confirm when the applied payout id is absent from the reread calendar", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [
      {
        payout_id: 9999,
        revision_id: 1,
        revision_kind: "APPLY",
        provider: "t_invest",
        instrument_uid: "UID-1",
        event_kind: "coupon",
        identity_key: "K-1",
        lifecycle: "active",
        total_amount: money("100.00"),
        reconciliation_id: null,
        counting_decision: null,
        expected_cash_flow_id: null,
      },
    ],
    error_code: null,
    message: null,
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

it("does not confirm on foreign refresh status", async () => {
  const user = userEvent.setup();
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 999,
    positions_changed: 0,
    items: [],
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

it("does not confirm on wrong-version expected rows", async () => {
  const user = userEvent.setup();
  vi.mocked(listExpectedFlows).mockResolvedValue([
    { reporting_month_id: 7, forecast_version: "foreign" },
  ] as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

it("does not confirm on mismatched readiness lifecycle", async () => {
  const user = userEvent.setup();
  vi.mocked(getCloseReadiness).mockResolvedValue({
    year: 1999,
    month: 1,
    status: "draft",
    snapshot_date: "1999-01-31",
    source: "manual",
    can_close: false,
    items: [],
  } as unknown as CloseReadiness);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

it("happy path proves payout ids, exact month/version and readiness before success", async () => {
  const user = userEvent.setup();
  vi.mocked(listExpectedFlows).mockResolvedValue([
    {
      reporting_month_id: 7,
      forecast_version: "v1",
    },
  ] as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(getCloseReadiness).toHaveBeenCalledWith(7));
  expect(listExpectedFlows).toHaveBeenCalledWith(7, "v1");
  expect(getPayoutRefreshStatus).toHaveBeenCalledWith(7);
});

it("does not confirm a malformed 0/0 success for one submitted row", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 0,
    items: [],
    error_code: null,
    message: null,
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
});

it("freezes position and version controls for the whole apply/readback lifetime", async () => {
  const user = userEvent.setup();
  let resolveApply!: (value: unknown) => void;
  vi.mocked(applyPayouts).mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveApply = resolve as (value: unknown) => void;
      }) as never,
  );
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  // While the deferred POST + readback is in flight, context is frozen.
  await waitFor(() => expect(applyPayouts).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("Позиция")).toBeDisabled();
  expect(screen.getByLabelText("Версия прогноза")).toBeDisabled();
  resolveApply({
    success: true,
    selected_count: 1,
    items: [
      {
        payout_id: 2,
        revision_id: 1,
        revision_kind: "APPLY",
        provider: "t_invest",
        instrument_uid: "UID-1",
        event_kind: "coupon",
        identity_key: "K-1",
        lifecycle: "active",
        total_amount: money("100.00"),
        reconciliation_id: null,
        counting_decision: null,
        expected_cash_flow_id: null,
      },
    ],
    error_code: null,
    message: null,
  });
  // Frozen context never changed, so the completion publishes exactly once.
  expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
  expect(screen.getByLabelText("Позиция")).not.toBeDisabled();
});

it("retires an in-flight completion when the version changes before publish", async () => {
  const user = userEvent.setup();
  let resolveApply!: (value: unknown) => void;
  vi.mocked(applyPayouts).mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveApply = resolve as (value: unknown) => void;
      }) as never,
  );
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  await waitFor(() => expect(applyPayouts).toHaveBeenCalledTimes(1));
  // Programmatic context edit retires the frozen completion: no late success.
  fireEvent.change(screen.getByLabelText("Версия прогноза"), { target: { value: "v9" } });
  resolveApply({
    success: true,
    selected_count: 1,
    items: [
      {
        payout_id: 2,
        revision_id: 1,
        revision_kind: "APPLY",
        provider: "t_invest",
        instrument_uid: "UID-1",
        event_kind: "coupon",
        identity_key: "K-1",
        lifecycle: "active",
        total_amount: money("100.00"),
        reconciliation_id: null,
        counting_decision: null,
        expected_cash_flow_id: null,
      },
    ],
    error_code: null,
    message: null,
  });
  await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledWith(7, "v9"));
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
  expect(screen.queryByText("Новая")).not.toBeInTheDocument();
});

function manualCalendarRow(
  sourceId: number,
  linkedProviderPayoutId: number | null,
): Record<string, unknown> {
  return {
    source_kind: "manual",
    source_id: sourceId,
    expected_date: "2026-09-10",
    flow_type: "coupon",
    account_id: 1,
    account_name: "Synthetic",
    instrument_id: 10,
    instrument_name: "Bond",
    expected_net_amount: money("100.00"),
    is_confirmed: false,
    is_approximate: false,
    manual_source: "manual",
    provider: null,
    provider_instrument_uid: null,
    provider_identity_key: null,
    provider_lifecycle: null,
    reconciliation_id: 900,
    counting_decision: "count_manual",
    linked_manual_id: null,
    linked_provider_payout_id: linkedProviderPayoutId,
  };
}

function manualOnlyCalendar(sourceId: number, linkedProviderPayoutId: number | null) {
  return [
    {
      year: 2026,
      month: 9,
      coupon: money("100.00"),
      dividend: money("0.00"),
      interest: money("0.00"),
      redemption: money("0.00"),
      other: money("0.00"),
      passive_net: money("100.00"),
      total_net: money("100.00"),
      items: [manualCalendarRow(sourceId, linkedProviderPayoutId)],
    },
  ];
}

function applyItem(payoutId: number, expectedCashFlowId: number | null): PayoutApplyItem {
  return {
    payout_id: payoutId,
    revision_id: 1,
    revision_kind: "APPLY",
    provider: "t_invest",
    instrument_uid: "UID-1",
    event_kind: "coupon",
    identity_key: "K-1",
    lifecycle: "active",
    total_amount: money("100.00"),
    reconciliation_id: expectedCashFlowId == null ? null : 900,
    counting_decision: expectedCashFlowId == null ? null : "count_manual",
    expected_cash_flow_id: expectedCashFlowId,
  };
}

it("confirms count_manual success through the linked manual calendar row", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayouts).mockResolvedValueOnce({
    ...previewFixture,
    rows: [
      {
        ...previewFixture.rows[0],
        status: "possible_manual_duplicate",
        manual_candidate_ids: [101],
      },
    ],
  });
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [applyItem(601, 101)],
    error_code: null,
    message: null,
  } as never);
  // No provider row for the applied payout: the canonical projection keeps
  // it on the manual row via linked_provider_payout_id.
  vi.mocked(listPayoutCalendar).mockResolvedValue(manualOnlyCalendar(101, 601) as never);
  vi.mocked(listExpectedFlows).mockResolvedValue([
    {
      id: 101,
      reporting_month_id: 7,
      forecast_version: "v1",
      account_id: 1,
      instrument_id: 10,
      flow_type: "coupon",
      expected_date: "2026-09-10",
      expected_net_amount: money("100.00"),
    },
  ] as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Возможный дубль")).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Решение для дубля 1"), "count_manual");
  await user.selectOptions(screen.getByLabelText("Ручная запись для дубля 1"), "101");
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
});

it("confirms provider-visible success through the provider calendar row", async () => {
  const user = userEvent.setup();
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  // Default fixtures: payout_id 2 is a visible provider row (source_id 2).
  expect(await screen.findByText(/Применено выплат: 1/)).toBeInTheDocument();
});

it.each(["date", "reconciliation", "counting", "manual_link"])(
  "keeps a successful receipt unverified for mismatched provider calendar %s",
  async (change) => {
    const user = userEvent.setup();
    const calendar = structuredClone(calendarFixture);
    const provider = calendar[0].items[1];
    if (change === "date") provider.expected_date = "2026-09-09";
    if (change === "reconciliation") Object.assign(provider, { reconciliation_id: 999 });
    if (change === "counting") Object.assign(provider, { counting_decision: "count_provider" });
    if (change === "manual_link") Object.assign(provider, { linked_manual_id: 999 });
    vi.mocked(listPayoutCalendar).mockResolvedValue(calendar as never);
    show("?month=7");
    await screen.findByText("Объединённый календарь выплат");
    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    await screen.findByText("Новая");
    await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
    await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
    expect(await screen.findByText(/APPLIED_UNVERIFIED/)).toBeInTheDocument();
    expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
  },
);

it("does not confirm readback after the reporting-month snapshot context changes", async () => {
  const user = userEvent.setup();
  let committed = false;
  const changed = { ...draftMonth, snapshot_date: "2026-08-30" };
  vi.mocked(getMonth).mockImplementation(async () => (committed ? changed : draftMonth));
  vi.mocked(getCloseReadiness).mockImplementation(
    async () =>
      ({
        ...(committed ? changed : draftMonth),
        can_close: false,
        items: [],
      }) as CloseReadiness,
  );
  vi.mocked(applyPayouts).mockImplementation(async () => {
    committed = true;
    return {
      success: true,
      selected_count: 1,
      items: [applyItem(2, null)],
      error_code: null,
      message: null,
    };
  });
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  await screen.findByText("Новая");
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/APPLIED_UNVERIFIED/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат/)).not.toBeInTheDocument();
});

it("does not confirm an unrelated manual link for the applied payout", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [applyItem(601, null)],
    error_code: null,
    message: null,
  } as never);
  vi.mocked(listPayoutCalendar).mockResolvedValue(manualOnlyCalendar(101, 602) as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

async function prepareStatementRow(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByLabelText("PDF отчёта Alfa"), statementFile);
  await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));
  await screen.findByText("synthetic-broker");
  await user.selectOptions(screen.getByLabelText("Alfa-счёт synthetic-broker"), "1");
  await user.click(screen.getByRole("button", { name: "Подготовить к импорту" }));
  await screen.findByText("Новая строка");
  await user.click(screen.getByRole("checkbox", { name: "Выбрать строку 1" }));
}

it("mounts the statement import section only for a valid explicit month with no action on mount", async () => {
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  expect(document.getElementById("statement-import")).not.toBeNull();
  expect(screen.getByLabelText("PDF отчёта Alfa")).toBeInTheDocument();
  expect(inspectStatement).not.toHaveBeenCalled();
  expect(prepareStatement).not.toHaveBeenCalled();
  expect(applyStatement).not.toHaveBeenCalled();
  expect(listInvestmentFlows).not.toHaveBeenCalled();
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("keeps the write/import tool unmounted without a valid explicit month", async () => {
  show("?month=bad#statement-import");
  await screen.findByText("Месяц не выбран");
  expect(document.getElementById("statement-import")).toBeNull();
  expect(screen.queryByLabelText("PDF отчёта Alfa")).toBeNull();
  expect(inspectStatement).not.toHaveBeenCalled();
});

it("retires the statement document when the explicit month changes", async () => {
  const user = userEvent.setup();
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await user.upload(screen.getByLabelText("PDF отчёта Alfa"), statementFile);
  await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));
  await screen.findByText("synthetic-broker");

  await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "8");
  await screen.findByLabelText("PDF отчёта Alfa");
  expect(screen.queryByText("synthetic-broker")).not.toBeInTheDocument();
  const input = screen.getByLabelText("PDF отчёта Alfa") as HTMLInputElement;
  expect(input.files?.length ?? 0).toBe(0);
  expect(screen.queryByRole("button", { name: "Применить выбранные строки" })).toBeNull();
});

it("constrains the native statement workspace to rows of the explicit month", async () => {
  const user = userEvent.setup();
  // One synthetic two-month preparation: the selected month is August 2026.
  vi.mocked(prepareStatement).mockResolvedValueOnce(spanningStatementPreparation as never);
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await user.upload(screen.getByLabelText("PDF отчёта Alfa"), statementFile);
  await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));
  await screen.findByText("synthetic-broker");
  await user.selectOptions(screen.getByLabelText("Alfa-счёт synthetic-broker"), "1");
  await user.click(screen.getByRole("button", { name: "Подготовить к импорту" }));
  await screen.findAllByText("Новая строка");

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes).toHaveLength(2);
  expect(checkboxes[0]).toBeEnabled();
  expect(checkboxes[1]).toBeDisabled();
  expect(screen.getByText(/строка относится к другому отчётному месяцу/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Выбрать все готовые" }));
  expect(checkboxes[0]).toBeChecked();
  expect(checkboxes[1]).not.toBeChecked();
  expect(applyStatement).not.toHaveBeenCalled();
});

it("keeps upload, inspect and prepare free of any write until the owner confirms", async () => {
  const user = userEvent.setup();
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await prepareStatementRow(user);
  expect(prepareStatement).toHaveBeenCalledTimes(1);
  expect(applyStatement).not.toHaveBeenCalled();
  expect(listInvestmentFlows).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Применить выбранные строки" }));
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Отмена" }));
  expect(applyStatement).not.toHaveBeenCalled();
  expect(screen.queryByText(/Импортировано строк/)).not.toBeInTheDocument();
  expect(screen.getByText("Новая строка")).toBeInTheDocument();
});

it("applies a synthetic statement only after the exact-month authoritative reread", async () => {
  const user = userEvent.setup();
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await prepareStatementRow(user);
  await user.click(screen.getByRole("button", { name: "Применить выбранные строки" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить и применить" }));

  expect(await screen.findByText(/Импортировано строк: 1/)).toBeInTheDocument();
  expect(applyStatement).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(listInvestmentFlows).toHaveBeenCalledWith(7));
  expect(getCloseReadiness).toHaveBeenCalledWith(7);
  expect(getMonth).toHaveBeenCalledWith(7);
  expect(screen.queryByText(/не подтверждён повторной загрузкой/)).not.toBeInTheDocument();
});

it("does not claim success when the applied flow id is missing from the reread", async () => {
  const user = userEvent.setup();
  vi.mocked(listInvestmentFlows).mockResolvedValue([]);
  show("?month=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await prepareStatementRow(user);
  await user.click(screen.getByRole("button", { name: "Применить выбранные строки" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить и применить" }));

  expect(await screen.findByText(/не подтверждён повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Импортировано строк/)).not.toBeInTheDocument();
  // The prepared document is retired: no blind replay of the same selection.
  expect(screen.queryByRole("button", { name: "Применить выбранные строки" })).toBeNull();
});

it("keeps the statement import fail-closed on a CLOSED month", async () => {
  show("?month=8#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  expect(
    screen.getByText(/Проверка PDF доступна, но применение выплат заблокировано/),
  ).toBeInTheDocument();
  expect(applyStatement).not.toHaveBeenCalled();
});

it("routes the actual_payouts close step to the native statement-import anchor and back", async () => {
  show("?month=7&from=monthly-close-v2&step=actual_payouts&monthId=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  expect(document.getElementById("statement-import")).not.toBeNull();
  expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&step=actual_payouts",
  );
  expect(screen.queryByRole("link", { name: "Продолжить к закрытию" })).toBeNull();
});

it("hands a zero-row statement outcome back to the same-month close step", async () => {
  const user = userEvent.setup();
  vi.mocked(inspectStatement).mockResolvedValueOnce({
    ...statementInspect,
    rows: [],
  } as never);
  show("?month=7&from=monthly-close-v2&step=actual_payouts&monthId=7#statement-import");
  await screen.findByLabelText("PDF отчёта Alfa");
  await user.upload(screen.getByLabelText("PDF отчёта Alfa"), statementFile);
  await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));

  expect(await screen.findByText("Результат проверки PDF Alfa")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Продолжить к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&step=actual_payouts",
  );
});

it("does not confirm a mismatched manual reconciliation identity", async () => {
  const user = userEvent.setup();
  vi.mocked(applyPayouts).mockResolvedValue({
    success: true,
    selected_count: 1,
    items: [applyItem(601, 101)],
    error_code: null,
    message: null,
  } as never);
  // Same manual source_id, but the link points at another payout.
  vi.mocked(listPayoutCalendar).mockResolvedValue(manualOnlyCalendar(101, 999) as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
});

function mockBulk(count = 3) {
  const items = Array.from({ length: count }, (_, index) => {
    const value = structuredClone(previewFixture);
    value.position_snapshot_id = 11 + index;
    value.instrument_id = 10 + index;
    value.instrument_uid = `UID-${index + 1}`;
    value.rows = value.rows.map((row) => ({
      ...row,
      position_snapshot_id: value.position_snapshot_id,
      instrument_id: value.instrument_id,
      instrument_uid: value.instrument_uid,
      identity_key: `K-${index + 1}`,
    }));
    return {
      account_id: 1,
      instrument_id: value.instrument_id,
      position_snapshot_id: value.position_snapshot_id,
      provider: "t_invest",
      instrument_uid: value.instrument_uid,
      status: "previewed",
      message: null,
      preview: value,
    };
  });
  vi.mocked(listPositions).mockResolvedValue(
    items.map((item) => ({
      ...position,
      id: item.position_snapshot_id,
      instrument_id: item.instrument_id,
    })) as never,
  );
  vi.mocked(previewPayoutsBatch).mockResolvedValue({
    reporting_month_id: 7,
    forecast_version: "v1",
    summary: {
      total_positions: count,
      eligible_positions: count,
      with_events: count,
      without_events: 0,
      errors: 0,
      skipped: 0,
    },
    items,
  } as never);
  vi.mocked(applyPayouts).mockImplementation(async (_monthId, payload) => ({
    success: true,
    selected_count: payload.rows.length,
    error_code: null,
    message: null,
    items: payload.rows.map((row) => ({
      ...applyItem(payload.position_snapshot_id, null),
      provider: row.provider,
      instrument_uid: row.instrument_uid,
      event_kind: row.event_kind,
      identity_key: row.identity_key,
    })),
  }));
  vi.mocked(listPayoutCalendar).mockResolvedValue([
    {
      ...calendarFixture[0],
      items: items.map((item) => ({
        ...calendarFixture[0].items[1],
        source_id: item.position_snapshot_id,
        instrument_id: item.instrument_id,
        provider_instrument_uid: item.instrument_uid,
        provider_identity_key: item.preview.rows[0].identity_key,
      })),
    },
  ] as never);
  return items;
}

it("bulk starts collapsed, disclosure preserves selection and top confirmation freezes the reviewed groups", async () => {
  const user = userEvent.setup();
  mockBulk(2);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  expect(screen.queryByLabelText("PDF отчёта Alfa")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 2");
  expect(document.getElementById("payout-group-11")).toHaveAttribute("hidden");
  expect(document.getElementById("payout-group-12")).toHaveAttribute("hidden");
  await user.click(screen.getByRole("button", { name: "Развернуть всё" }));
  expect(document.getElementById("payout-group-11")).not.toHaveAttribute("hidden");
  await user.click(screen.getByRole("button", { name: "Свернуть всё" }));
  expect(screen.getByText("Выбрано событий: 2")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Очистить выбор" }));
  await screen.findByText("Выбрано событий: 0");
  await user.click(screen.getByRole("button", { name: "Выбрать доступные" }));
  await screen.findByText("Выбрано событий: 2");
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("Подтвердить выбор (2 групп)");
  await user.click(screen.getByRole("button", { name: "Отмена" }));
  expect(applyPayouts).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (2 групп)" }));
  await screen.findByText(/Подтверждено: 2 из 2/);
  expect(vi.mocked(applyPayouts).mock.calls.map((call) => call[1].position_snapshot_id)).toEqual([
    11, 12,
  ]);
});

it("bulk mixed success and ambiguous failure retains CONFIRMED, UNKNOWN and NOT_SENT without replay", async () => {
  const user = userEvent.setup();
  mockBulk();
  const view = show("?month=7");
  vi.mocked(applyPayouts)
    .mockImplementationOnce(async (_id, payload) => ({
      success: true,
      selected_count: 1,
      items: [{ ...applyItem(11, null), ...payload.rows[0] }],
      error_code: null,
      message: null,
    }))
    .mockRejectedValueOnce(new Error("lost response"));
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 3");
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (3 групп)" }));
  await screen.findByText(/UNKNOWN/);
  expect(screen.getByText(/CONFIRMED/)).toBeInTheDocument();
  expect(screen.getByText(/NOT_SENT/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(2);
  view.unmount();
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  expect(applyPayouts).toHaveBeenCalledTimes(2);
  expect(previewPayoutsBatch).toHaveBeenCalledTimes(1);
  // Reload performs only local reads. A later write needs fresh explicit preview + confirmation.
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 3");
  expect(applyPayouts).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (3 групп)" }));
  await screen.findByText(/Подтверждено: 3 из 3/);
});

it("a preview queued before Apply cannot rearm selection after UNKNOWN", async () => {
  const user = userEvent.setup();
  let reply!: (value: PayoutPreview) => void;
  const oldPreview = new Promise<PayoutPreview>((resolve) => {
    reply = resolve;
  });
  vi.mocked(previewPayouts)
    .mockResolvedValueOnce(previewFixture)
    .mockReturnValueOnce(oldPreview)
    .mockResolvedValue(previewFixture);
  vi.mocked(applyPayouts).mockRejectedValueOnce(new Error("synthetic lost response"));
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  const refresh = screen.getByRole("button", { name: "Проверить выплаты T-Invest" });
  await user.click(refresh);
  await screen.findByText("Новая");
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  const confirm = screen.getByRole("button", { name: /Применить \(1\)/ });
  // Two already queued activations before React commits the busy state:
  // a pre-attempt preview must be fenced even if UI disabling is not yet painted.
  act(() => {
    refresh.click();
    confirm.click();
  });
  await screen.findByText(/UNKNOWN/);
  expect(applyPayouts).toHaveBeenCalledTimes(1);
  await act(async () => {
    reply(previewFixture);
    await oldPreview;
  });
  expect(screen.queryByText("Новая")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Применить выбранные \(1\)/ }),
  ).not.toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(1);
  await user.click(refresh);
  await screen.findByText("Новая");
  expect(previewPayouts).toHaveBeenCalledTimes(3);
  expect(applyPayouts).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  await screen.findByText(/Применено выплат: 1/);
  expect(applyPayouts).toHaveBeenCalledTimes(2);
});

it("blocks bulk Apply while an explicit batch preview remains pending", async () => {
  const user = userEvent.setup();
  mockBulk();
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  const refresh = screen.getByRole("button", { name: "Проверить все позиции T-Invest" });
  await user.click(refresh);
  await screen.findByText("Выбрано событий: 3");
  let reply!: (value: PayoutBatchPreview) => void;
  vi.mocked(previewPayoutsBatch).mockReturnValueOnce(
    new Promise((resolve) => {
      reply = resolve;
    }),
  );
  await user.click(refresh);
  expect(screen.getByRole("button", { name: /^Применить выбранные$/ })).toBeDisabled();
  expect(applyPayouts).not.toHaveBeenCalled();
  const original = await vi.mocked(previewPayoutsBatch).mock.results[0].value;
  await act(async () => {
    reply(original);
  });
});

it("bulk blocks duplicate clicks and individual Apply until authoritative readback completes", async () => {
  const user = userEvent.setup();
  mockBulk(2);
  show("?month=7");
  let resolve!: (value: Awaited<ReturnType<typeof applyPayouts>>) => void;
  vi.mocked(applyPayouts).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 2");
  await user.click(screen.getByRole("button", { name: "Развернуть всё" }));
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  const confirm = screen.getByRole("button", { name: "Подтвердить выбор (2 групп)" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(applyPayouts).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("combobox", { name: "Отчётный месяц" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Применить выбранные" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Остановить после текущей группы" }));
  resolve({
    success: true,
    selected_count: 1,
    items: [applyItem(11, null)],
    error_code: null,
    message: null,
  });
  await screen.findByText(/CONFIRMED/);
  expect(screen.getByText(/NOT_SENT/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(1);
});

it("bulk rejects changed local quantity before POST and leaves later groups NOT_SENT", async () => {
  const user = userEvent.setup();
  const items = mockBulk(2);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 2");
  vi.mocked(listPositions).mockResolvedValue(
    items.map((item) => ({
      ...position,
      id: item.position_snapshot_id,
      instrument_id: item.instrument_id,
      quantity: "999",
    })) as never,
  );
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (2 групп)" }));
  await screen.findByText(/STALE_NO_WRITE/);
  expect(screen.getByText(/NOT_SENT/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("collapsed warnings remain visible and manual duplicates require explicit row reconciliation", async () => {
  const user = userEvent.setup();
  const items = mockBulk(2);
  items[0].preview.rows[0] = {
    ...items[0].preview.rows[0],
    status: "possible_manual_duplicate",
    default_selected: false,
    manual_candidate_ids: [101],
  };
  items[1].preview.rows[0] = {
    ...items[1].preview.rows[0],
    status: "unchanged",
    selectable: false,
    default_selected: false,
  };
  vi.mocked(previewPayoutsBatch).mockResolvedValue({
    reporting_month_id: 7,
    forecast_version: "v1",
    summary: {
      total_positions: 2,
      eligible_positions: 2,
      with_events: 2,
      without_events: 0,
      errors: 0,
      skipped: 0,
    },
    items,
  } as never);
  show("?month=7");
  await screen.findByText("Объединённый календарь выплат");
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText(/Возможный ручной дубль/);
  expect(screen.getByText(/ALREADY_PRESENT/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Выбрать доступные" }));
  expect(screen.getByText("Выбрано событий: 0")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Развернуть всё" }));
  await user.selectOptions(screen.getByLabelText("Решение для дубля 1"), "count_manual");
  await user.selectOptions(screen.getByLabelText("Ручная запись для дубля 1"), "101");
  await user.click(screen.getByRole("button", { name: "Выбрать доступные" }));
  await screen.findByText("Выбрано событий: 1");
  await user.click(screen.getByRole("button", { name: "Свернуть всё" }));
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (1 групп)" }));
  await waitFor(() => expect(applyPayouts).toHaveBeenCalledTimes(1));
  expect(vi.mocked(applyPayouts).mock.calls[0][1].rows[0].manual_duplicate_decision).toEqual({
    expected_cash_flow_id: 101,
    counting_decision: "count_manual",
  });
  // A receipt lacking that explicit link remains unverified, never a false success.
  await screen.findByText(/APPLIED_UNVERIFIED/);
});
