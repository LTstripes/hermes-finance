import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import {
  type DraftPayoutContext,
  type DraftPayoutResult,
  getDraftPayoutContext,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  refreshDraftPayouts,
} from "../api/payouts";
import { MonthDraftPayouts } from "./MonthDraftPayouts";

vi.mock("../api/payouts", () => ({
  getDraftPayoutContext: vi.fn(),
  getPayoutRefreshStatus: vi.fn(),
  listPayoutCalendar: vi.fn(),
  refreshDraftPayouts: vi.fn(),
}));
const cta = "Обновить прогноз Т-Инвест";
const read = "Проверить сохранённые прогнозы";
const context: DraftPayoutContext = {
  reporting_month_id: 1,
  snapshot_date: "2030-01-31",
  status: "draft",
  context_digest: "a".repeat(64),
  view_digest: "c".repeat(64),
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
  readback_digest: "c".repeat(64),
  summary: { updated: 2, unchanged: 0, unsupported: 0, needs_review: 0, error: 0 },
  items: context.items.map((i) => ({ ...i, status: "updated", saved_payout_ids: [i.account_id] })),
};

function show(
  props: Partial<Parameters<typeof MonthDraftPayouts>[0]> = {},
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <MonthDraftPayouts monthId={1} closed={false} {...props} />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/v2/close?month=1&panel=payouts");
  vi.mocked(getDraftPayoutContext).mockResolvedValue(context);
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 1,
    positions_changed: 0,
    items: [],
    forecast_as_of: null,
  });
  vi.mocked(listPayoutCalendar).mockResolvedValue([]);
  vi.mocked(refreshDraftPayouts).mockResolvedValue(saved);
});

test("confirmed DRAFT enables one explicit batch and GET readback; render/focus/reload never POST", async () => {
  const view = show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: cta }));
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 2/)).toBeVisible();
  expect(refreshDraftPayouts).toHaveBeenCalledExactlyOnceWith(1, context.context_digest);
  expect(getDraftPayoutContext).toHaveBeenCalledTimes(2);
  expect(listPayoutCalendar).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("link", { name: "Календарь выплат" })).toHaveAttribute(
    "href",
    "/v2/data/payouts?month=1",
  );
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  view.unmount();
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Обновлено позиций/)).not.toBeInTheDocument();
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
    if (mode === "lost-ack")
      vi.mocked(refreshDraftPayouts).mockRejectedValueOnce(new Error("lost ACK"));
    else
      vi.mocked(listPayoutCalendar)
        .mockResolvedValueOnce([])
        .mockRejectedValueOnce(new Error("lost GET"))
        .mockResolvedValue([]);
    show();
    await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: cta }));
    expect(await screen.findByText(/Не удалось подтвердить результат/)).toBeVisible();
    expect(screen.getByRole("button", { name: cta })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: read }));
    await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
    expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Обновлено позиций/)).not.toBeInTheDocument();
    if (mode === "lost-ack")
      expect(screen.getByText(/не подтверждает его завершение/)).toBeVisible();
    else expect(screen.queryByText(/не подтверждает его завершение/)).toBeNull();
  },
);

test("old mounted CTA cannot send after native history switches month before React commit", async () => {
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  window.history.pushState({ key: "new-month" }, "", "/v2/close?month=2&panel=payouts");
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});

test.each(["initial", "refresh"])(
  "dependency change during a delayed %s GET cannot leave its old snapshot current",
  async (mode) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["positions"], [{ quantity: "10" }]);
    let complete: ((value: DraftPayoutContext) => void) | undefined;
    const delay = () =>
      new Promise<DraftPayoutContext>((resolve) => {
        complete = resolve;
      });
    if (mode === "initial") vi.mocked(getDraftPayoutContext).mockImplementationOnce(delay);
    show({}, client);
    if (mode === "refresh") {
      await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
      vi.mocked(getDraftPayoutContext).mockImplementationOnce(delay);
      await act(async () => {
        void client.invalidateQueries();
      });
    }
    await waitFor(() => expect(complete).toBeDefined());
    vi.mocked(getDraftPayoutContext).mockResolvedValue({ ...context, eligible_positions: 0 });
    await act(async () => {
      if (mode === "initial") client.setQueryData(["positions"], [{ quantity: "20" }]);
      else
        await client.fetchQuery({
          queryKey: ["positions"],
          queryFn: async () => [{ quantity: "20" }],
        });
    });
    await act(async () => {
      complete?.(context);
    });
    await waitFor(() =>
      expect(getDraftPayoutContext).toHaveBeenCalledTimes(mode === "initial" ? 2 : 3),
    );
    await waitFor(() =>
      expect(
        client.getQueryData<DraftPayoutContext>(["draft-payouts", 1, undefined])
          ?.eligible_positions,
      ).toBe(0),
    );
    expect(screen.getByRole("button", { name: cta })).toBeDisabled();
    expect(refreshDraftPayouts).not.toHaveBeenCalled();
  },
);

test("global refresh reads the panel once; changed dependency facts still invalidate it", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const keys = [["broker-months", 1], ["source-intakes"], ["instruments"], ["positions"]];
  const facts = [{ id: 1 }];
  for (const queryKey of keys) await client.fetchQuery({ queryKey, queryFn: async () => facts });
  show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  let complete: ((value: DraftPayoutContext) => void) | undefined;
  vi.mocked(getDraftPayoutContext).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  await act(async () => {
    void client.invalidateQueries();
  });
  expect(getDraftPayoutContext).toHaveBeenCalledTimes(2);
  expect(listPayoutCalendar).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeDisabled());
  await act(async () => {
    complete?.(context);
  });
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  // Identical background dependency reads do not amplify a completed refresh.
  await act(async () => {
    for (const queryKey of keys) await client.fetchQuery({ queryKey, queryFn: async () => facts });
  });
  expect(getDraftPayoutContext).toHaveBeenCalledTimes(2);
  expect(listPayoutCalendar).toHaveBeenCalledTimes(2);
  // A real dependency change still requires a new authoritative context GET.
  vi.mocked(getDraftPayoutContext).mockResolvedValue({ ...context, eligible_positions: 0 });
  await act(async () => {
    await client.fetchQuery({ queryKey: keys[0], queryFn: async () => [{ id: 2 }] });
  });
  await waitFor(() => expect(getDraftPayoutContext).toHaveBeenCalledTimes(3));
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeDisabled());
  expect(listPayoutCalendar).toHaveBeenCalledTimes(3);
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});

test.each(["available", "closed", "dirty", "no-action", "unknown"])(
  "reason copy and remediation match the actual payout screen: %s",
  async (mode) => {
    const code =
      mode === "no-action"
        ? "position_not_positive"
        : mode === "unknown"
          ? "future_valuation_flow_error"
          : "mapping_ambiguous";
    vi.mocked(getDraftPayoutContext).mockResolvedValue({
      ...context,
      items: [{ ...context.items[0], eligible: false, reason_codes: [code] }],
    });
    show({ closed: mode === "closed", disabled: mode === "dirty" });
    await screen.findByText(/Некоторые данные требуют проверки/);
    fireEvent.click(screen.getByText("Подробнее"));
    expect(screen.getByText(code)).not.toBeVisible();
    if (mode === "available")
      expect(screen.getByRole("link", { name: "Исправить" })).toHaveAttribute(
        "href",
        "/v2/data/catalogs",
      );
    else expect(screen.queryByRole("link", { name: "Исправить" })).toBeNull();
    if (mode === "unknown") expect(screen.getByText("Значение сейчас недоступно")).toBeVisible();
    expect(screen.getByText(/Счёт 1 · Бумага · RU000A000000/)).toBeVisible();
    expect(refreshDraftPayouts).not.toHaveBeenCalled();
  },
);

test("partial failure separates the error and hides its details", async () => {
  vi.mocked(refreshDraftPayouts).mockResolvedValue({
    ...saved,
    summary: { updated: 1, unchanged: 0, unsupported: 0, needs_review: 0, error: 1 },
    items: [
      saved.items[0],
      {
        ...saved.items[1],
        status: "error",
        reason_codes: ["provider_error"],
        saved_payout_ids: [],
      },
    ],
  });
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 1/)).toBeVisible();
  expect(screen.getByText(/Не удалось обновить часть данных/)).toBeVisible();
  expect(screen.getByText("provider_error")).not.toBeVisible();
  fireEvent.click(screen.getByText("Подробнее об ошибке"));
  expect(screen.getByText(/Счёт 2 · Бумага/)).toBeVisible();
});

test("automatic partial failure remains visible after reopening", async () => {
  vi.mocked(getPayoutRefreshStatus).mockResolvedValue({
    reporting_month_id: 1,
    positions_changed: 0,
    items: [],
    forecast_as_of: null,
    automatic_refresh: { status: "partial", message: "", reason_codes: ["provider_error"] },
  });
  show();
  expect(await screen.findByText(/При автоматическом обновлении часть данных/)).toBeVisible();
  expect(screen.getByText("Подробнее об ошибке")).toBeVisible();
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});

test("reads a later automatic status only after explicit refresh", async () => {
  const status = { reporting_month_id: 1, positions_changed: 0, items: [], forecast_as_of: null };
  vi.mocked(getPayoutRefreshStatus)
    .mockResolvedValueOnce({
      ...status,
      automatic_refresh: { status: "pending", message: "", reason_codes: [] },
    })
    .mockResolvedValue({
      ...status,
      automatic_refresh: { status: "error", message: "", reason_codes: ["provider_error"] },
    });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  show({}, client);
  await waitFor(() => expect(getPayoutRefreshStatus).toHaveBeenCalledTimes(1));
  await act(async () => client.invalidateQueries({ queryKey: ["payout-refresh-status", 1] }));
  expect(
    await screen.findByText(/При автоматическом обновлении часть данных/, {}, { timeout: 8000 }),
  ).toBeVisible();
  expect(getPayoutRefreshStatus).toHaveBeenCalledTimes(2);
}, 10000);

test("status read failure is visible with details hidden", async () => {
  vi.mocked(getPayoutRefreshStatus).mockRejectedValue(new Error("status unavailable"));
  show();
  expect(
    await screen.findByText("Не удалось прочитать статус автоматического обновления."),
  ).toBeVisible();
  expect(screen.getByText("status unavailable")).not.toBeVisible();
});

test("unconfirmed result survives leaving the panel and prevents a repeat until recovery", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let rejectRequest: ((error: Error) => void) | undefined;
  vi.mocked(refreshDraftPayouts).mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        rejectRequest = reject;
      }),
  );
  const view = show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  view.unmount();
  const unloading = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unloading);
  expect(unloading.defaultPrevented).toBe(true);
  show({}, client);
  expect(screen.getByRole("button", { name: /Обновляем прогноз/ })).toBeDisabled();
  await act(async () => {
    rejectRequest?.(new Error("lost ACK"));
  });
  expect(await screen.findByText(/Не удалось подтвердить результат/)).toBeVisible();
  expect(screen.getByRole("button", { name: cta })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: read }));
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
});

test("unconfirmed result survives a fresh client after reload", async () => {
  sessionStorage.setItem("draft-payout-unconfirmed:1", "1");
  show();
  expect(await screen.findByText(/Не удалось подтвердить результат/)).toBeVisible();
  expect(screen.getByRole("button", { name: cta })).toBeDisabled();
  await waitFor(() => expect(screen.getByRole("button", { name: read })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: read }));
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(sessionStorage.getItem("draft-payout-unconfirmed:1")).toBe("unknown-reviewed");
  expect(screen.getByText(/не подтверждает его завершение/)).toBeVisible();
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});

test("status readback failure after a confirmed refresh is shown without replay", async () => {
  vi.mocked(getPayoutRefreshStatus).mockRejectedValueOnce(new Error("status readback failed"));
  // The first read may fail independently of a confirmed forecast readback.
  show();
  expect(
    await screen.findByText("Не удалось прочитать статус автоматического обновления."),
  ).toBeVisible();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  vi.mocked(getPayoutRefreshStatus).mockRejectedValue(new Error("status readback failed"));
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 2/)).toBeVisible();
  expect(screen.getByText("Не удалось прочитать статус автоматического обновления.")).toBeVisible();
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
});

test("a changed context hides an earlier result and shows current issues", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 2/)).toBeVisible();
  await act(async () => {
    client.setQueryData(["draft-payouts", 1, undefined], {
      ...context,
      context_digest: "b".repeat(64),
      view_digest: "b".repeat(64),
      items: [{ ...context.items[0], eligible: false, reason_codes: ["mapping_ambiguous"] }],
    });
  });
  await waitFor(() => expect(screen.queryByText(/Обновлено позиций: 2/)).not.toBeInTheDocument());
  expect(screen.getByText(/Некоторые данные требуют проверки/)).toBeVisible();
});

test("fresh unconfirmed state blocks a click from a stale rendered button", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  const button = screen.getByRole("button", { name: cta });
  act(() => {
    client.setQueryData(["draft-payout-operation", 1], {
      busy: false,
      unconfirmed: true,
      result: null,
      notice: null,
    });
    fireEvent.click(button);
  });
  expect(refreshDraftPayouts).not.toHaveBeenCalled();
});

test("unknown outcome remains explicit after reread and reload; retry is manual", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(refreshDraftPayouts).mockRejectedValueOnce(new Error("lost ACK"));
  const view = show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  await screen.findByText(/Не удалось подтвердить результат/);
  fireEvent.click(screen.getByRole("button", { name: read }));
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(screen.getByText(/не подтверждает его завершение/)).toBeVisible();
  view.unmount();
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  expect(screen.getByText(/не подтверждает его завершение/)).toBeVisible();
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 2/)).toBeVisible();
  expect(screen.getByText(/не подтверждает его завершение/)).toBeVisible();
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(2);
});

test("shows partial result after forecast changes digest, but hides it if source changes", async () => {
  const nextContext = { ...context, context_digest: "b".repeat(64), view_digest: "b".repeat(64) };
  vi.mocked(getDraftPayoutContext).mockResolvedValueOnce(context).mockResolvedValue(nextContext);
  vi.mocked(refreshDraftPayouts).mockResolvedValue({
    ...saved,
    readback_digest: "b".repeat(64),
    summary: { updated: 1, unchanged: 0, unsupported: 0, needs_review: 0, error: 1 },
    items: [
      saved.items[0],
      {
        ...saved.items[1],
        status: "error",
        reason_codes: ["provider_error"],
        saved_payout_ids: [],
      },
    ],
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  show({}, client);
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Обновлено позиций: 1/)).toBeVisible();
  expect(screen.getByText(/Не удалось обновить часть данных/)).toBeVisible();
  fireEvent.click(screen.getByText("Подробнее об ошибке"));
  expect(screen.getByText(/Счёт 2 · Бумага/)).toBeVisible();
  await act(async () => {
    client.setQueryData(["draft-payouts", 1, undefined], {
      ...nextContext,
      context_digest: "d".repeat(64),
      view_digest: "e".repeat(64),
    });
  });
  await waitFor(() => expect(screen.queryByText(/Обновлено позиций: 1/)).not.toBeInTheDocument());
});

test("does not bind a response to a source changed during the request", async () => {
  vi.mocked(getDraftPayoutContext)
    .mockResolvedValueOnce(context)
    .mockResolvedValue({
      ...context,
      context_digest: "b".repeat(64),
      view_digest: "d".repeat(64),
    });
  show();
  await waitFor(() => expect(screen.getByRole("button", { name: cta })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: cta }));
  expect(await screen.findByText(/Не удалось подтвердить результат/)).toBeVisible();
  expect(screen.queryByText(/Обновлено позиций/)).toBeNull();
  expect(refreshDraftPayouts).toHaveBeenCalledTimes(1);
});
