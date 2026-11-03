import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { listExpectedFlows } from "../api/expectedFlows";
import { getInstrumentMapping } from "../api/instrumentMappings";
import { listInstruments } from "../api/instruments";
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
import type { CloseReadiness, PositionSnapshot, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import UiV2PayoutForecastPage from "./UiV2PayoutForecastPage";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instrumentMappings", () => ({ getInstrumentMapping: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
  getMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
}));
vi.mock("../api/positions", () => ({ listPositions: vi.fn() }));
vi.mock("../api/expectedFlows", () => ({ listExpectedFlows: vi.fn() }));
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
  vi.mocked(getInstrumentMapping).mockResolvedValue({
    instrument_id: 10,
    state: "mapped",
    identity: { provider: "t_invest", provider_instrument_id: "UID-1", provider_venue_id: null },
    instrument_isin: "RU000SYNTH01",
    legacy_moex_secid: null,
  });
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
    forecast_as_of: "2026-08-31T12:00:00Z",
    automatic_refresh: { status: "completed", message: "", reason_codes: [] },
    items: [],
  } as never);
  vi.mocked(listExpectedFlows).mockResolvedValue([]);
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

async function openDetails() {
  const button = await screen.findByRole("button", { name: "Подробности" });
  if (button.getAttribute("aria-expanded") === "false") fireEvent.click(button);
}

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
  await openDetails();
  expect(getMonth).toHaveBeenCalledWith(7);
  expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&step=future_payouts",
  );
  expect(screen.getByRole("link", { name: /^Экспорт и копии$/ })).toHaveAttribute(
    "href",
    "/v2/data/files?month=7&from=monthly-close-v2&monthId=7&step=future_payouts&scope=synthetic#target",
  );
  // Mixed calendar: passive income and principal stay distinct.
  expect(
    within(screen.getByRole("region", { name: "Основной прогноз" })).getByText(
      "возврат капитала, не доход",
    ),
  ).toBeInTheDocument();
});

it.each([
  "",
  "?month=",
  "?month=bad",
  "?month=999",
  "?month=7&month=7",
  "?month=07",
  "#statement-import",
  "?month=999#statement-import",
])("rejects invalid explicit scope %s", async (query) => {
  show(query);
  expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
  expect(getMonth).not.toHaveBeenCalled();
  expect(document.getElementById("statement-import")).toBeNull();
  expect(screen.queryByLabelText("PDF отчёта Alfa")).toBeNull();
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(previewPayoutsBatch).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("mounts the tool only after the Owner explicitly selects a month", async () => {
  const user = userEvent.setup();
  show("?from=monthly-close-v2&monthId=7&step=future_payouts#target");
  expect(await screen.findByText("Месяц не выбран")).toBeInTheDocument();
  expect(getMonth).not.toHaveBeenCalled();
  await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "7");
  await openDetails();
  expect(getMonth).toHaveBeenCalledWith(7);
});

it("does not call the provider on mount; local calendar loads without preview", async () => {
  show("?month=7");
  await openDetails();
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
  await openDetails();

  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  expect(previewPayouts).toHaveBeenCalledTimes(1);
  expect(applyPayouts).not.toHaveBeenCalled();

  // Apply is a separate explicit choice behind a confirm dialog.
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  const confirmation = await screen.findByRole("alertdialog");
  expect(confirmation).toHaveTextContent("Август 2026");
  expect(confirmation).not.toHaveTextContent(/месяц #/i);
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
  await openDetails();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  // Preview itself is allowed on CLOSED; the panel explains read-only.
  expect(await screen.findByText(/Месяц закрыт\. Предпросмотр доступен/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("does not offer a return to a different close month", async () => {
  show("?month=7&from=monthly-close-v2&monthId=8&step=future_payouts");
  await openDetails();
  expect(screen.queryByRole("link", { name: "Вернуться к закрытию" })).not.toBeInTheDocument();
  expect(screen.getByText(/другому месяцу/)).toBeInTheDocument();
});

it("shows provider error without claiming success", async () => {
  const user = userEvent.setup();
  vi.mocked(previewPayouts).mockRejectedValue(new Error("synthetic provider failure"));
  show("?month=7");
  await openDetails();
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
  await openDetails();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText(/не соответствует выбранной позиции/)).toBeInTheDocument();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  expect(await screen.findByText(/не соответствует выбранной позиции/)).toBeInTheDocument();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  expect(await screen.findByText(/не соответствует выбранной позиции/)).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("a refreshed batch item cannot replace another position", async () => {
  const user = userEvent.setup();
  show("?month=7");
  await openDetails();
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
  expect(await screen.findByText(/не соответствует выбранной позиции/)).toBeInTheDocument();
  expect(screen.getByText("Проверка завершена")).toBeInTheDocument();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("an open single confirm cannot POST after the position changes", async () => {
  const user = userEvent.setup();
  vi.mocked(listPositions).mockResolvedValue([position, secondPosition]);
  show("?month=7");
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
  await openDetails();
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
    await openDetails();
    await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
    await screen.findByText("Новая");
    await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
    await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
    expect(await screen.findByText(/Сохранение не подтверждено/)).toBeInTheDocument();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  await screen.findByText("Новая");
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/Сохранение не подтверждено/)).toBeInTheDocument();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить выплаты T-Invest" }));
  expect(await screen.findByText("Новая")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Применить выбранные \(1\)/ }));
  await user.click(screen.getByRole("button", { name: /Применить \(1\)/ }));
  expect(await screen.findByText(/не подтверждены повторной загрузкой/)).toBeInTheDocument();
  expect(screen.queryByText(/Применено выплат: 1/)).not.toBeInTheDocument();
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
  await openDetails();
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
  await openDetails();
  expect(screen.getByLabelText("PDF отчёта Alfa")).not.toBeVisible();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText("Выбрано событий: 3");
  await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
  await user.click(screen.getByRole("button", { name: "Подтвердить выбор (3 групп)" }));
  await screen.findByText(/Результат неизвестен/);
  expect(screen.getByText(/Сохранение подтверждено/)).toBeInTheDocument();
  expect(screen.getByText(/Запрос не отправлен · версия/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(2);
  view.unmount();
  show("?month=7");
  await openDetails();
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
  await openDetails();
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
  await screen.findByText(/Результат неизвестен/);
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
  await openDetails();
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
  await openDetails();
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
  await screen.findByText(/Сохранение подтверждено/);
  expect(screen.getByText(/Запрос не отправлен · версия/)).toBeInTheDocument();
  expect(applyPayouts).toHaveBeenCalledTimes(1);
});

it("bulk rejects changed local quantity before POST and leaves later groups NOT_SENT", async () => {
  const user = userEvent.setup();
  const items = mockBulk(2);
  show("?month=7");
  await openDetails();
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
  await screen.findByText(/Данные устарели, запрос не отправлен/);
  expect(screen.getByText(/Запрос не отправлен · версия/)).toBeInTheDocument();
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
  await openDetails();
  await user.click(screen.getByRole("button", { name: "Проверить все позиции T-Invest" }));
  await screen.findByText(/Возможный ручной дубль/);
  expect(screen.getByText(/Уже сохранено; повторно не отправляется/)).toBeInTheDocument();
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
  await screen.findByText(/Сохранение не подтверждено/);
});

it("keeps the ordinary desktop view to two actions and separates 12-month income from principal", async () => {
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(within(main).getByRole("heading", { name: "Прогноз на 12 месяцев" })).toBeVisible();
  expect(
    within(main)
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Обновить", "Подробности"]);
  expect(main).toHaveTextContent("Прогноз дохода · купоны и дивиденды300");
  expect(main).toHaveTextContent("Возврат номинала1 000");
  expect(main).not.toHaveTextContent("1 300");
  expect(main).toHaveTextContent("Последний прогноз: 31.08.2026");
  expect(within(main).getByRole("table", { name: "Выплаты по датам" })).toBeVisible();
  expect(within(main).queryByRole("status", { name: "Требует внимания" })).toBeNull();
  expect(main).not.toHaveTextContent(/t_invest|UID-1|K-1|active|completed|v1/);
  expect(screen.queryByRole("button", { name: "Проверить все позиции T-Invest" })).toBeNull();
  expect(screen.getByLabelText("PDF отчёта Alfa")).not.toBeVisible();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it.each(["?month=8", "?month=8&from=monthly-close-v2&monthId=8&step=future_payouts"])(
  "shows unknown completeness for an empty calendar month without opening details (%s)",
  async (query) => {
    vi.mocked(listPayoutCalendar).mockResolvedValue([
      {
        ...calendarFixture[0],
        year: closedMonth.year,
        month: closedMonth.month,
        coupon: money("0.00"),
        dividend: money("0.00"),
        interest: money("0.00"),
        redemption: money("0.00"),
        other: money("0.00"),
        passive_net: money("0.00"),
        total_net: money("0.00"),
        actual_attribution_coverage: "unknown",
        items: [],
      },
    ]);
    vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
      reporting_month_id: closedMonth.id,
      positions_changed: 0,
      items: [],
    });
    vi.mocked(getCloseReadiness).mockResolvedValue({
      ...closedMonth,
      can_close: false,
      items: [],
    } as CloseReadiness);

    show(query);
    const calendar = await screen.findByRole("region", {
      name: "Календарь выплат: горизонтальная прокрутка таблицы",
    });
    expect(calendar).toBeVisible();
    expect(within(calendar).getByText("Полнота неизвестна; известная часть:")).toBeVisible();
    expect(calendar).toHaveTextContent("Июль 2026");
    expect(calendar).toHaveTextContent("0 выплат");
    expect(calendar).toHaveTextContent("Пассивный доход: 0");
    expect(calendar).toHaveTextContent("весь денежный поток: 0");
    expect(calendar).not.toHaveTextContent("999");
    expect(listPayoutCalendar).toHaveBeenCalledWith(closedMonth.id, "v1");
    expect(screen.getByRole("button", { name: "Подробности" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(previewPayouts).not.toHaveBeenCalled();
    expect(previewPayoutsBatch).not.toHaveBeenCalled();
    expect(applyPayouts).not.toHaveBeenCalled();
  },
);

it("opens advanced operations and technical diagnostics in one click", async () => {
  const user = userEvent.setup();
  show("?month=7");
  await user.click(await screen.findByRole("button", { name: "Подробности" }));
  expect(screen.getByRole("button", { name: "Проверить все позиции T-Invest" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Проверить выплаты T-Invest" })).toBeVisible();
  expect(screen.getByText(/Автообновление: completed/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Загрузка файлов месяца · PDF выплат" })).toHaveAttribute(
    "href",
    "/v2/close?month=7&panel=brokers",
  );
  await user.click(screen.getByRole("button", { name: "Подробности" }));
  expect(screen.queryByRole("button", { name: "Проверить выплаты T-Invest" })).toBeNull();
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("shows partial coverage, unmapped papers and conflicts in plain language", async () => {
  vi.mocked(getInstrumentMapping).mockResolvedValue({
    instrument_id: 10,
    state: "unmapped",
    identity: null,
    instrument_isin: "RU000SYNTH01",
    legacy_moex_secid: null,
  });
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 7,
    positions_changed: 1,
    items: [],
    forecast_as_of: "2026-08-29T12:00:00Z",
    automatic_refresh: {
      status: "partial",
      message: "technical_payload",
      reason_codes: ["mapping_ambiguous", "possible_manual_duplicate", "draft_changed"],
    },
  });
  vi.mocked(listPayoutCalendar).mockResolvedValue([
    { ...calendarFixture[0], actual_attribution_coverage: "unknown" },
  ] as never);
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  const attention = within(main).getByRole("status", { name: "Требует внимания" });
  expect(attention).toHaveTextContent("Прогноз неполный");
  expect(attention).toHaveTextContent("Bond: нет сопоставления с T-Invest");
  expect(attention).toHaveTextContent("Есть конфликт выплат");
  expect(attention).toHaveTextContent("прогноз может быть устаревшим");
  expect(attention).toHaveTextContent("Полнота выплат неизвестна");
  expect(main).toHaveTextContent("Последний прогноз: 29.08.2026");
  expect(main).not.toHaveTextContent(
    /mapping_ambiguous|possible_manual_duplicate|draft_changed|technical_payload/,
  );
  expect(within(main).getAllByRole("button")).toHaveLength(2);
});

it("keeps the previous calendar and its backend date after an offline reload without a provider request", async () => {
  const user = userEvent.setup();
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  vi.mocked(listPayoutCalendar).mockRejectedValueOnce(new Error("synthetic offline"));
  vi.mocked(getPayoutRefreshStatus).mockRejectedValueOnce(new Error("synthetic offline"));
  await user.click(within(main).getByRole("button", { name: "Обновить" }));
  expect(await within(main).findByText(/Обновление недоступно/)).toHaveTextContent(
    "Показан прежний прогноз. Последний прогноз: 31.08.2026",
  );
  expect(within(main).getByRole("table", { name: "Выплаты по датам" })).toBeVisible();
  expect(main).toHaveTextContent("Прогноз дохода · купоны и дивиденды300");
  expect(main).not.toHaveTextContent("synthetic offline");
  expect(previewPayoutsBatch).not.toHaveBeenCalled();
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
  await user.click(within(main).getByRole("button", { name: "Обновить" }));
  await waitFor(() => expect(within(main).queryByText(/Обновление недоступно/)).toBeNull());
});

it("shows the saved forecast on provider failure after entry and keeps an unknown date explicit", async () => {
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 7,
    positions_changed: 0,
    items: [],
    forecast_as_of: null,
    automatic_refresh: {
      status: "error",
      message: "provider_error",
      reason_codes: ["provider_unavailable"],
    },
  });
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(within(main).getByText(/Обновление недоступно/)).toHaveTextContent(
    "Показан прежний прогноз. Дата последнего прогноза неизвестна",
  );
  expect(main).not.toHaveTextContent(/provider_error|provider_unavailable/);
  expect(within(main).getByRole("table")).toBeVisible();
});

it("does not lose the saved calendar when only status or mapping reads fail", async () => {
  vi.mocked(getPayoutRefreshStatus).mockRejectedValue(new Error("status offline"));
  vi.mocked(getInstrumentMapping).mockRejectedValue(new Error("mapping offline"));
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(within(main).getByRole("table")).toBeVisible();
  expect(main).toHaveTextContent("Не удалось проверить сопоставление части бумаг");
  expect(main).toHaveTextContent("Дата последнего прогноза неизвестна");
});

it("sorts saved payments by date and uses exact cents without mixing currencies", async () => {
  vi.mocked(listPayoutCalendar).mockResolvedValue([
    {
      ...calendarFixture[0],
      coupon: money("90071992547409.91"),
      dividend: money("0.02"),
      items: [...calendarFixture[0].items].reverse(),
    },
    {
      ...calendarFixture[0],
      month: 10,
      coupon: { amount: "1.01", currency: "USD" },
      dividend: { amount: "0.02", currency: "USD" },
      redemption: { amount: "0.00", currency: "USD" },
      items: [],
    },
  ] as never);
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(main).toHaveTextContent("90 071 992 547 409,93 ₽ · 1,03 USD");
  const rows = within(within(main).getByRole("table")).getAllByRole("row").slice(1);
  expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
    "10.09.2026",
    "10.09.2026",
    "15.09.2026",
  ]);
});

it("does not turn invalid money into zero or retain a different version after a failed read", async () => {
  const user = userEvent.setup();
  vi.mocked(listPayoutCalendar).mockResolvedValueOnce([
    { ...calendarFixture[0], coupon: money("unknown") },
  ] as never);
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(main).toHaveTextContent("Прогноз дохода · купоны и дивидендыНе определён");
  await openDetails();
  vi.mocked(listPayoutCalendar).mockRejectedValue(new Error("version unavailable"));
  await user.clear(screen.getByLabelText("Версия прогноза"));
  await user.type(screen.getByLabelText("Версия прогноза"), "v2");
  await waitFor(() => expect(within(main).queryByRole("table")).toBeNull());
  expect(main).not.toHaveTextContent("Последний прогноз: 31.08.2026");
});

it.each([
  "?month=7#statement-import",
  "?month=7&from=monthly-close-v2&monthId=7&step=actual_payouts#statement-import",
])("legacy PDF entry %s expands the original importer and keeps the forecast", async (query) => {
  show(query);
  const input = await screen.findByLabelText("PDF отчёта Alfa");
  expect(document.getElementById("statement-import")).toHaveAttribute("open");
  expect(input).toBeVisible();
  expect(input).toHaveAttribute("id", "statement-file");
  expect(screen.getByRole("button", { name: "Проверить отчёт" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Основной прогноз" })).toBeVisible();
  expect(previewPayouts).not.toHaveBeenCalled();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("keeps the old importer collapsed until explicitly opened and preserves its file on collapse", async () => {
  const user = userEvent.setup();
  show("?month=7");
  const input = await screen.findByLabelText("PDF отчёта Alfa");
  const disclosure = document.getElementById("statement-import");
  expect(disclosure?.tagName).toBe("DETAILS");
  expect(disclosure).not.toHaveAttribute("open");
  expect(input).not.toBeVisible();
  const summary = screen.getByText("Импорт выписок (старый)");
  await user.click(summary);
  expect(disclosure).toHaveAttribute("open");
  expect(input).toBeVisible();
  const file = new File(["synthetic PDF"], "synthetic.pdf", { type: "application/pdf" });
  await user.upload(input, file);
  await user.click(summary);
  expect(input).not.toBeVisible();
  await user.click(summary);
  expect(input).toBeVisible();
  expect((input as HTMLInputElement).files?.[0]).toBe(file);
});

it("keeps CLOSED statements inspectable with applying blocked", async () => {
  show("?month=8#statement-import");
  expect(await screen.findByLabelText("PDF отчёта Alfa")).toBeVisible();
  expect(
    screen.getByText(/Проверка PDF доступна, но применение выплат заблокировано/),
  ).toBeVisible();
  expect(applyPayouts).not.toHaveBeenCalled();
});

it("shows persisted reconciliation conflicts even after transient automatic status resets", async () => {
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 7,
    positions_changed: 0,
    items: [],
    automatic_refresh: { status: "idle", message: "", reason_codes: [] },
  });
  vi.mocked(getCloseReadiness).mockResolvedValue({
    ...draftMonth,
    can_close: false,
    items: [
      {
        code: "unresolved_payout_reconciliation",
        severity: "warning",
        message: "technical diagnostic",
        context: {},
      },
    ],
  } as CloseReadiness);
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(main).toHaveTextContent("Есть несогласованные выплаты");
  expect(main).not.toHaveTextContent(/unresolved_payout_reconciliation|technical diagnostic/);
});

it("shows saved forecast before optional mapping and readiness reads complete", async () => {
  vi.mocked(getInstrumentMapping).mockReturnValue(new Promise(() => {}));
  vi.mocked(getCloseReadiness).mockReturnValue(new Promise(() => {}));
  show("?month=7");
  const main = await screen.findByRole("region", { name: "Основной прогноз" });
  expect(main).toHaveTextContent("Прогноз дохода");
  expect(within(main).getByRole("table", { name: "Выплаты по датам" })).toBeVisible();
  expect(main).not.toHaveTextContent("Не удалось проверить согласованность выплат");
  expect(applyPayouts).not.toHaveBeenCalled();
});
