import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { listExpectedFlows } from "../api/expectedFlows";
import { listInstruments } from "../api/instruments";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import {
  applyPayouts,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  previewPayouts,
  previewPayoutsBatch,
} from "../api/payouts";
import { listPositions } from "../api/positions";
import type { CloseReadiness, ReportingMonth } from "../api/types";
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
} as never;

const secondPosition = {
  id: 12,
  reporting_month_id: 7,
  account_id: 1,
  instrument_id: 10,
  quantity: "5",
} as never;

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
        expected_date: "2026-09-15",
        flow_type: "redemption",
        account_id: 1,
        account_name: "Synthetic",
        instrument_id: 10,
        instrument_name: "Bond",
        expected_net_amount: money("1000.00"),
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

const previewFixture = {
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
  await waitFor(() => expect(listPayoutCalendar).toHaveBeenCalledTimes(2));
  expect(getPayoutRefreshStatus).toHaveBeenCalledTimes(2);
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
  expect(await screen.findByText(/Месяц закрыт/)).toBeInTheDocument();
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
    selected_count: 0,
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
