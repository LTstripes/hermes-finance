import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import {
  type DraftPayoutContext,
  type DraftPayoutResult,
  getDraftPayoutContext,
  listPayoutCalendar,
  refreshDraftPayouts,
} from "../api/payouts";
import { MonthDraftPayouts } from "./MonthDraftPayouts";

vi.mock("../api/payouts", () => ({
  getDraftPayoutContext: vi.fn(),
  listPayoutCalendar: vi.fn(),
  refreshDraftPayouts: vi.fn(),
}));
const cta = "Получить и сохранить прогнозы Т-Инвест";
const read = "Обновить чтение сохранённых прогнозов";
const context: DraftPayoutContext = {
  reporting_month_id: 1,
  snapshot_date: "2030-01-31",
  status: "draft",
  context_digest: "a".repeat(64),
  eligible_positions: 2,
  items: [1, 2].map((id) => ({
    account_id: id,
    account_name: `Счёт ${id}`,
    instrument_id: 1,
    instrument_name: "Бумага",
    isin: "RU000A000000",
    position_snapshot_id: id,
    quantity: String(id * 10),
    eligible: true,
    reason_codes: [],
  })),
};
const saved: DraftPayoutResult = {
  reporting_month_id: 1,
  summary: { updated: 2, unchanged: 0, unsupported: 0, needs_review: 0, error: 0 },
  items: context.items.map((i) => ({ ...i, status: "updated", saved_payout_ids: [i.account_id] })),
};

function show(props: Partial<Parameters<typeof MonthDraftPayouts>[0]> = {}) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <BrowserRouter>
        <MonthDraftPayouts monthId={1} closed={false} {...props} />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/v2/close?month=1&panel=payouts");
  vi.mocked(getDraftPayoutContext).mockResolvedValue(context);
  vi.mocked(listPayoutCalendar).mockResolvedValue([]);
  vi.mocked(refreshDraftPayouts).mockResolvedValue(saved);
});

test("confirmed DRAFT enables one explicit batch and GET readback; render/focus/reload never POST", async () => {
  const view = show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: cta }));
  fireEvent.click(screen.getByRole("button", { name: /Получаем и сохраняем/ }));
  expect(await screen.findByText(/Позиций обновлено: 2/)).toBeVisible();
  expect(refreshDraftPayouts).toHaveBeenCalledExactlyOnceWith(1, context.context_digest);
  expect(getDraftPayoutContext).toHaveBeenCalledTimes(2);
  expect(listPayoutCalendar).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/Объявлено\/прогноз \(налог неизвестен\)/)).toBeVisible();
  expect(screen.getByText(/Возврат номинала · отдельно от дохода/)).toBeVisible();
  view.unmount();
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Позиций обновлено/)).not.toBeInTheDocument();
});

test.each(["source-only", "closed", "dirty", "failed-get"])(
  "blocks automatic save for %s",
  async (mode) => {
    if (mode === "source-only")
      vi.mocked(getDraftPayoutContext).mockResolvedValue({
        ...context,
        eligible_positions: 0,
        items: [],
      });
    if (mode === "failed-get")
      vi.mocked(getDraftPayoutContext).mockRejectedValue(new Error("GET unavailable"));
    show({ closed: mode === "closed", disabled: mode === "dirty" });
    await waitFor(() => expect(getDraftPayoutContext).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.getByRole("button", { name: cta })).toBeDisabled();
    expect(refreshDraftPayouts).not.toHaveBeenCalled();
  },
);

test.each(["lost-ack", "lost-get"])(
  "%s is unresolved until explicit GET recovery without replay",
  async (mode) => {
    const pending = vi.fn();
    if (mode === "lost-ack")
      vi.mocked(refreshDraftPayouts).mockRejectedValueOnce(new Error("lost ACK"));
    else
      vi.mocked(listPayoutCalendar)
        .mockResolvedValueOnce([])
        .mockRejectedValueOnce(new Error("lost GET"))
        .mockResolvedValue([]);
    show({ onPendingChange: pending });
    await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: cta }));
    expect(await screen.findByText(/Результат всего запроса не подтверждён/)).toBeVisible();
    expect(screen.getByRole("button", { name: cta })).toBeDisabled();
    expect(pending).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: read }));
    await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
    expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
    expect(pending).toHaveBeenLastCalledWith(false);
    expect(screen.queryByText(/Позиций обновлено/)).not.toBeInTheDocument();
  },
);

test("old mounted CTA cannot send after native history switches month before React commit", async () => {
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  window.history.pushState({ key: "new-month" }, "", "/v2/close?month=2&panel=payouts");
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});
