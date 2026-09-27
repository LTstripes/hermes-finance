import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportingMonth } from "../api/types";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";
import { UiV2MonthPositionsSection } from "./UiV2MonthPositionsSection";

const month = {
  id: 7,
  year: 2031,
  month: 1,
  snapshot_date: "2031-01-31",
  status: "draft",
} as ReportingMonth;
const account = {
  id: 11,
  name: "Synthetic Broker",
  account_type: "brokerage",
  status: "active",
  include_in_capital: true,
  include_in_returns: true,
};
const instrument = {
  id: 21,
  name: "Synthetic Fund",
  ticker: "SYN",
  instrument_type: "fund",
  currency: "USD",
  is_active: true,
  manual_price_allowed: true,
};
const position = {
  id: 31,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  quantity: "0.500000",
  average_cost_per_unit: { amount: "1000.00", currency: "RUB" },
  market_price_per_unit: { amount: "1100.00", currency: "RUB" },
  market_value: { amount: "550.00", currency: "RUB" },
  cost_basis: { amount: "500.00", currency: "RUB" },
  unrealized_result: { amount: "50.00", currency: "RUB" },
  accrued_interest: null,
  price_source: "manual",
  price_date: "2031-01-31",
  updated_at: "2031-02-01T00:00:00Z",
  notes: null,
};
const quote = {
  reporting_month_id: 7,
  month_status: "draft",
  target_date: "2031-01-31",
  month_editable: true,
  batch_error: null,
  batch_error_reason: null,
  rows: [
    {
      position_snapshot_id: 31,
      account_id: 11,
      instrument_id: 21,
      instrument_name: "Synthetic Fund",
      instrument_type: "fund",
      mapping_state: "mapped",
      identity: {
        provider: "t_invest",
        provider_instrument_id: "synthetic",
        provider_venue_id: null,
      },
      current_market_price_per_unit: { amount: "1100.00", currency: "RUB" },
      current_price_date: "2031-01-31",
      current_price_source: "manual",
      proposed_market_price_per_unit: { amount: "0.00", currency: "RUB" },
      proposed_price_date: "2031-01-30",
      proposed_quote_kind: "last",
      proposed_raw_price: "0.00",
      proposed_raw_price_basis: "R",
      fetched_at_utc: "2031-01-31T12:00:00Z",
      freshness_status: "stale",
      status: "stale",
      failure_reason: null,
      message: null,
      apply_allowed: false,
    },
  ],
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred() {
  let release: (() => void) | undefined;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release: () => release?.() };
}

type Handler = (init?: RequestInit) => Response | Promise<Response>;
function setup(overrides: Record<string, Handler> = {}, initial: unknown[] = [position]) {
  const routes: Record<string, Handler> = {
    "GET /api/accounts": () => json([account]),
    "GET /api/instruments?active=true": () => json([instrument]),
    "GET /api/positions?month_id=7": () => json(initial),
    "GET /api/months/7": () => json(month),
    ...overrides,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${String(input)}`;
    return (
      routes[key]?.(init) ?? json({ error: { code: "not_found", message: key, details: [] } }, 404)
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  const setDirty = vi.fn();
  const context: MonthEditorContext = {
    month,
    readOnly: false,
    refresh: async () => month,
    setDirty,
    returnToClose: null,
  };
  const view = render(<UiV2MonthPositionsSection context={context} />);
  return { fetchMock, setDirty, context, ...view };
}

afterEach(() => vi.unstubAllGlobals());

describe("native month positions leaf", () => {
  it("loads only local data, keeps units and currency visible, and never auto-refreshes quotes", async () => {
    const { fetchMock, context, rerender, setDirty, unmount } = setup();
    await screen.findByText("Synthetic Fund (SYN)");
    expect(screen.getByRole("table")).toHaveTextContent("USD");
    expect(screen.getByRole("table")).toHaveTextContent("0,5");
    rerender(<UiV2MonthPositionsSection context={{ ...context }} />);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview"))).toBe(false);
    unmount();
    expect(setDirty).toHaveBeenCalledWith("positions", false);
  });

  it("creates a fractional position through canonical RUB API and confirms a month-scoped readback", async () => {
    let rows: unknown[] = [];
    const { fetchMock, setDirty } = setup(
      {
        "GET /api/positions?month_id=7": () => json(rows),
        "POST /api/positions": () => {
          rows = [position];
          return json(position, 201);
        },
      },
      [],
    );
    const user = userEvent.setup();
    await screen.findByText("Пусто");
    await user.type(screen.getByLabelText("Количество"), "0.5");
    await user.type(screen.getByLabelText("Средняя цена приобретения"), "1000");
    await user.type(screen.getByLabelText("Рыночная цена"), "1100");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));
    await screen.findByText("Synthetic Fund (SYN)");
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === "/api/positions" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      quantity: "0.5",
      average_cost_per_unit: { amount: "1000.00", currency: "RUB" },
      market_price_per_unit: { amount: "1100.00", currency: "RUB" },
    });
    expect(setDirty).toHaveBeenCalledWith("positions", false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview"))).toBe(false);
  });

  it("edits with If-Match, then deletes only after confirmation and readback", async () => {
    const revised = { ...position, quantity: "0.750000", updated_at: "2031-02-02T00:00:00Z" };
    let rows: unknown[] = [position];
    const { fetchMock } = setup({
      "GET /api/positions?month_id=7": () => json(rows),
      "PATCH /api/positions/31": () => {
        rows = [revised];
        return json(revised);
      },
      "DELETE /api/positions/31": () => {
        rows = [];
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Действия для позиции Synthetic Fund" }));
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const quantity = within(
      document.querySelector(".position-inline-edit") as HTMLElement,
    ).getByLabelText("Количество");
    await user.clear(quantity);
    await user.type(quantity, "0.75");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByRole("table")).toHaveTextContent("0,75"));
    const patch = fetchMock.mock.calls.find(([url]) => String(url) === "/api/positions/31");
    expect(patch?.[1]?.headers).toMatchObject({ "If-Match": position.updated_at });
    expect(JSON.parse(String(patch?.[1]?.body)).quantity).toBe("0.75");

    await user.click(screen.getByRole("button", { name: "Действия для позиции Synthetic Fund" }));
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url) === "/api/positions/31" && init?.method === "DELETE",
      ),
    ).toBe(false);
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Удалить" }),
    );
    await screen.findByText("Пусто");
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url) === "/api/positions/31" && init?.method === "DELETE",
      ),
    ).toBe(true);
  });

  it("freezes every inline edit field until a delayed PATCH and readback complete", async () => {
    const gate = deferred();
    const revised = { ...position, quantity: "0.750000", updated_at: "2031-02-02T00:00:00Z" };
    let rows: unknown[] = [position];
    const { fetchMock, setDirty } = setup({
      "GET /api/positions?month_id=7": () => json(rows),
      "PATCH /api/positions/31": async () => {
        await gate.promise;
        rows = [revised];
        return json(revised);
      },
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Действия для позиции Synthetic Fund" }));
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    const form = document.querySelector(".position-inline-edit") as HTMLElement;
    const quantity = within(form).getByLabelText("Количество");
    await user.clear(quantity);
    await user.type(quantity, "0.75");
    await user.click(within(form).getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/positions/31")).toBe(true),
    );
    expect(
      [...form.querySelectorAll("input,select")].every(
        (field) => (field as HTMLInputElement).disabled,
      ),
    ).toBe(true);
    await user.type(quantity, "9");
    expect(quantity).toHaveValue("0.75");
    expect(setDirty).toHaveBeenCalledWith("positions", true);
    gate.release();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull());
    expect(screen.getByRole("table")).toHaveTextContent("0,75");
    expect(setDirty).toHaveBeenCalledWith("positions", false);
  });

  it("freezes the add form through delayed POST and confirmation, then clears only its submitted draft", async () => {
    const gate = deferred();
    let rows: unknown[] = [];
    const { fetchMock, setDirty } = setup(
      {
        "GET /api/positions?month_id=7": () => json(rows),
        "POST /api/positions": async () => {
          await gate.promise;
          rows = [position];
          return json(position, 201);
        },
      },
      [],
    );
    const user = userEvent.setup();
    await screen.findByText("Пусто");
    const form = screen
      .getByRole("button", { name: "Добавить позицию" })
      .closest("form") as HTMLFormElement;
    const quantity = within(form).getByLabelText("Количество");
    await user.type(quantity, "0.5");
    await user.type(within(form).getByLabelText("Средняя цена приобретения"), "1000");
    await user.type(within(form).getByLabelText("Рыночная цена"), "1100");
    await user.click(within(form).getByRole("button", { name: "Добавить позицию" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url) === "/api/positions" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(
      [...form.querySelectorAll("input,select")].every(
        (field) => (field as HTMLInputElement).disabled,
      ),
    ).toBe(true);
    await user.type(quantity, "9");
    expect(quantity).toHaveValue("0.5");
    gate.release();
    await screen.findByText("Synthetic Fund (SYN)");
    await waitFor(() => expect(quantity).toHaveValue(""));
    expect(setDirty).toHaveBeenCalledWith("positions", false);
  });

  it("freezes quick instrument fields through delayed POST and catalog readback", async () => {
    const gate = deferred();
    const created = {
      ...instrument,
      id: 22,
      name: "Synthetic New",
      ticker: "NEW",
      currency: "RUB",
    };
    let instruments = [instrument];
    const { fetchMock } = setup({
      "GET /api/instruments?active=true": () => json(instruments),
      "POST /api/instruments": async () => {
        await gate.promise;
        instruments = [...instruments, created];
        return json(created, 201);
      },
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    const form = screen
      .getByRole("button", { name: "Создать инструмент" })
      .closest("form") as HTMLFormElement;
    const name = within(form).getByLabelText("Название инструмента");
    await user.type(name, "Synthetic New");
    await user.type(within(form).getByLabelText("Тикер"), "NEW");
    await user.click(within(form).getByRole("button", { name: "Создать инструмент" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url) === "/api/instruments" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(
      [...form.querySelectorAll("input,select")].every(
        (field) => (field as HTMLInputElement).disabled,
      ),
    ).toBe(true);
    await user.type(name, " later");
    expect(name).toHaveValue("Synthetic New");
    gate.release();
    await waitFor(() => expect(name).toHaveValue(""));
    expect(
      within(
        screen.getByRole("button", { name: "Добавить позицию" }).closest("form") as HTMLFormElement,
      ).getByLabelText("Инструмент позиции"),
    ).toHaveValue("22");
  });

  it("allows a closed month to preview but blocks apply and manual writes", async () => {
    const { context, rerender, fetchMock } = setup({
      "POST /api/months/7/quote-preview": () =>
        json({ ...quote, month_status: "closed", month_editable: false }),
    });
    await screen.findByText("Synthetic Fund (SYN)");
    rerender(
      <UiV2MonthPositionsSection
        context={{ ...context, readOnly: true, month: { ...month, status: "closed" } }}
      />,
    );
    const user = userEvent.setup();
    expect(screen.queryByRole("button", { name: "Добавить позицию" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    expect(screen.queryByRole("button", { name: "Применить выбранные" })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("ignores a delayed preview after the exact month changes", async () => {
    let release: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { context, rerender, fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => pending,
      "GET /api/positions?month_id=8": () => json([]),
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    rerender(<UiV2MonthPositionsSection context={{ ...context, month: { ...month, id: 8 } }} />);
    release?.(json(quote));
    await screen.findByText("Пусто");
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("keeps stale zero quotes separate from an explicit selection and checks the current month before apply", async () => {
    const { fetchMock } = setup({ "POST /api/months/7/quote-preview": () => json(quote) });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(await screen.findByText("Нужно выбрать отдельно")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Применить выбранные" })).toBeDisabled();
    expect(screen.getByRole("table", { name: "Предпросмотр котировок" })).toHaveTextContent("0 ₽");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("applies only the selected preview and confirms the saved price without another provider call", async () => {
    const next = {
      ...position,
      market_price_per_unit: { amount: "1200.00", currency: "RUB" },
      price_source: "t_invest",
      price_date: "2031-01-31",
    };
    let rows: unknown[] = [position];
    const freshQuote = {
      ...quote,
      rows: [
        {
          ...quote.rows[0],
          status: "ok",
          freshness_status: "ok",
          apply_allowed: true,
          proposed_market_price_per_unit: next.market_price_per_unit,
          proposed_price_date: next.price_date,
        },
      ],
    };
    const { fetchMock } = setup({
      "GET /api/positions?month_id=7": () => json(rows),
      "POST /api/months/7/quote-preview": () => json(freshQuote),
      "POST /api/months/7/quote-apply": () => {
        rows = [next];
        return json({
          reporting_month_id: 7,
          applied_count: 1,
          rows: [
            {
              position_snapshot_id: 31,
              market_price_per_unit: next.market_price_per_unit,
              price_date: next.price_date,
              price_source: next.price_source,
            },
          ],
        });
      },
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await user.click(await screen.findByRole("button", { name: "Применить выбранные" }));
    expect(await screen.findByText(/Котировки применены: 1/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).includes("quote-preview")),
    ).toHaveLength(1);
    const apply = fetchMock.mock.calls.find(([url]) => String(url).includes("quote-apply"));
    expect(JSON.parse(String(apply?.[1]?.body)).rows).toMatchObject([
      {
        position_snapshot_id: 31,
        accept_stale: false,
        expected_market_price_per_unit: { amount: "1200.00", currency: "RUB" },
      },
    ]);
  });

  it("invalidates a preview when the month closes while its provider request is pending", async () => {
    let release: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { context, rerender, fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => pending,
    });
    const user = userEvent.setup();
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    rerender(
      <UiV2MonthPositionsSection
        context={{ ...context, readOnly: true, month: { ...month, status: "closed" } }}
      />,
    );
    release?.(json(quote));
    await waitFor(() =>
      expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).toBeNull(),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("keeps a failed save dirty and never reports it as confirmed", async () => {
    const { setDirty } = setup(
      {
        "POST /api/positions": () =>
          json({ error: { code: "conflict", message: "Synthetic conflict", details: [] } }, 409),
      },
      [],
    );
    const user = userEvent.setup();
    await screen.findByText("Пусто");
    await user.type(screen.getByLabelText("Количество"), "1");
    await user.type(screen.getByLabelText("Средняя цена приобретения"), "10");
    await user.type(screen.getByLabelText("Рыночная цена"), "11");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(setDirty).toHaveBeenCalledWith("positions", true);
    expect(screen.getByLabelText("Количество")).toHaveValue("1");
  });
});
