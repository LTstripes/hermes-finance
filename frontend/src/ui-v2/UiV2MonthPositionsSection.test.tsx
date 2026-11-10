import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
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
function setup(
  overrides: Record<string, Handler> = {},
  initial: unknown[] = [position],
  options: { readOnly?: boolean; closed?: boolean; url?: string } = {},
) {
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
    month: options.closed ? { ...month, status: "closed" } : month,
    readOnly: options.readOnly ?? false,
    refresh: async () => month,
    setDirty,
    returnToClose: null,
  };
  const view = render(<UiV2MonthPositionsSection context={context} />, {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[options.url ?? "/"]}>{children}</MemoryRouter>
    ),
  });
  return { fetchMock, setDirty, context, ...view };
}

afterEach(() => vi.unstubAllGlobals());

describe("native month positions leaf", () => {
  it("hides empty native price/result columns, unknown totals and source actions, explaining once", async () => {
    setup({}, [
      {
        ...position,
        price_source: "broker_statement_native",
        average_cost_per_unit: null,
        market_price_per_unit: null,
        cost_basis: null,
        unrealized_result: null,
      },
    ]);
    await screen.findByText("Synthetic Fund (SYN)");
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("550");
    expect(within(table).queryByText("—")).toBeNull();
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Инструмент", "Кол-во", "Стоимость, ₽"]);
    expect(screen.queryByText("Нет подтверждённой суммы")).toBeNull();
    expect(screen.queryByText(/Себестоимость:/)).toBeNull();
    expect(screen.queryByText(/Нереализованный результат:/)).toBeNull();
    expect(screen.queryByText("Как читаются итоги позиции")).toBeNull();
    expect(screen.queryByText(/прокрутить вправо/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Действия для позиции/ })).toBeNull();
    expect(screen.getAllByText(/Брокерская выписка даёт количество и стоимость/)).toHaveLength(1);
    expect(screen.getByRole("link", { name: "«Доходности»" })).toHaveAttribute(
      "href",
      "/v2/returns",
    );
    expect(within(table).queryByText(/Выписка|31\.01\.2031/)).toBeNull();
    expect(screen.getAllByText(/Итого:/)).toHaveLength(1);
  });

  it("groups and sorts exact values by account and row, and recomputes display shares for filters", async () => {
    const second = { ...account, id: 12, name: "Synthetic IIS", account_type: "iis" };
    const bond = {
      ...instrument,
      id: 22,
      name: "Synthetic Bond",
      ticker: null,
      instrument_type: "bond",
    };
    const small = {
      ...position,
      id: 32,
      instrument_id: 22,
      market_value: { amount: "50.00", currency: "RUB" },
    };
    setup(
      {
        "GET /api/accounts": () =>
          json([
            account,
            second,
            { ...account, id: 13, name: "Empty Deposit", account_type: "deposit" },
          ]),
        "GET /api/instruments?active=true": () => json([instrument, bond]),
      },
      [
        small,
        position,
        {
          ...position,
          id: 33,
          account_id: 12,
          market_value: { amount: "900.00", currency: "RUB" },
        },
      ],
    );
    const table = await screen.findByRole("table");
    const bodies = table.querySelectorAll("tbody");
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toHaveTextContent("Synthetic IIS 1 поз.");
    expect(bodies[0]).toHaveTextContent("60,0%");
    expect(bodies[1]).toHaveTextContent("Synthetic Broker 2 поз.");
    const rows = within(bodies[1]).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Synthetic Fund");
    expect(rows[2]).toHaveTextContent("Synthetic Bond");
    expect(rows[1]).toHaveTextContent("36,7%");
    const accountFilter = screen.getByLabelText("Фильтр: счёт");
    expect(
      within(accountFilter)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Все счета", "Synthetic Broker", "Synthetic IIS"]);
    expect(
      within(screen.getByLabelText("Фильтр: тип инструмента"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Все типы", "Облигации", "Фонды"]);
    const user = userEvent.setup();
    await user.selectOptions(accountFilter, "11");
    expect(table.querySelectorAll("tbody")).toHaveLength(1);
    expect(table.querySelector("tbody th")).toHaveTextContent("100,0%");
    expect(within(table).getAllByRole("row")[2]).toHaveTextContent("91,7%");
  });

  it("preserves zero values and leaves statement-only cells blank instead of dashes", async () => {
    setup({}, [
      {
        ...position,
        average_cost_per_unit: null,
        market_price_per_unit: null,
        unrealized_result: null,
        cost_basis: null,
        price_source: "broker_statement_native",
      },
      {
        ...position,
        id: 32,
        average_cost_per_unit: { amount: "0.00", currency: "RUB" },
        unrealized_result: { amount: "0.00", currency: "RUB" },
      },
    ]);
    const table = await screen.findByRole("table");
    expect(
      within(table).getByRole("columnheader", { name: "Цена покупки, ₽" }),
    ).toBeInTheDocument();
    expect(within(table).queryAllByText("—")).toHaveLength(0);
    expect(within(table).getAllByText("0")).toHaveLength(2);
    expect(within(table).getAllByRole("button", { name: /Действия для позиции/ })).toHaveLength(1);
    expect(screen.queryByText(/Себестоимость:/)).toBeNull();
    expect(screen.queryByText(/Нереализованный результат:/)).toBeNull();
    const user = userEvent.setup();
    await user.click(within(table).getByRole("button", { name: /Действия для позиции/ }));
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeEnabled();
  });

  it.each([{ readOnly: true }, { closed: true }])(
    "omits the actions column when %j",
    async (options) => {
      setup({}, [position], options);
      const table = await screen.findByRole("table");
      expect(within(table).queryByRole("columnheader", { name: "Действия" })).toBeNull();
      expect(within(table).queryByRole("button")).toBeNull();
      expect(screen.getByText(/Себестоимость:/)).toHaveTextContent("500");
      expect(screen.getByText(/Нереализованный результат:/)).toHaveTextContent("50");
    },
  );

  it("links exact ISIN with account and the full current URL as back, without help chips", async () => {
    const url = "/v2/data/months/7?section=positions&source=local#positions";
    setup(
      { "GET /api/instruments?active=true": () => json([{ ...instrument, isin: "XX0000000001" }]) },
      [position],
      { url },
    );
    const link = await screen.findByRole("link", { name: "Synthetic Fund (SYN)" });
    const href = new URL(link.getAttribute("href") ?? "", "http://localhost");
    expect(href.pathname).toBe("/v2/returns/instrument/XX0000000001");
    expect(href.searchParams.get("capital_account")).toBe("11");
    expect(href.searchParams.get("back")).toBe(url);
    expect(
      within(screen.getByRole("table")).queryByRole("button", {
        name: /Полное название|Детали оценки/,
      }),
    ).toBeNull();
  });

  it("shows valuation exceptions once under value and accrued interest under price", async () => {
    setup({}, [{ ...position, accrued_interest: { amount: "3.00", currency: "RUB" } }]);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText(/Вручную · 31\.01\.2031/)).toHaveLength(1);
    const nkd = within(table).getByText(/НКД 3/);
    expect(nkd.closest("td")).toHaveTextContent(/1\s100/);
  });

  it("updates column visibility, the single statement explanation and totals with the current filter", async () => {
    setup(
      {
        "GET /api/accounts": () => json([account, { ...account, id: 12, account_type: "iis" }]),
      },
      [
        position,
        {
          ...position,
          id: 32,
          account_id: 12,
          average_cost_per_unit: null,
          market_price_per_unit: null,
          cost_basis: null,
          unrealized_result: null,
          price_source: "broker_statement_native",
        },
        {
          ...position,
          id: 33,
          account_id: 12,
          average_cost_per_unit: null,
          market_price_per_unit: null,
          cost_basis: null,
          unrealized_result: null,
          price_source: "broker_statement_native",
        },
      ],
    );
    const table = await screen.findByRole("table");
    const filter = screen.getByLabelText("Фильтр: счёт");
    expect(
      within(filter)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Все счета", "Synthetic Broker (Брокерский)", "Synthetic Broker (ИИС)"]);
    expect(screen.getAllByText(/Брокерская выписка даёт/)).toHaveLength(1);
    const user = userEvent.setup();
    await user.selectOptions(filter, "12");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(within(table).queryByText("—")).toBeNull();
    await user.selectOptions(filter, "11");
    expect(within(table).getByRole("columnheader", { name: "Цена, ₽" })).toBeInTheDocument();
    expect(screen.queryByText(/Брокерская выписка даёт/)).toBeNull();
    expect(screen.getByText(/Себестоимость:/)).toBeInTheDocument();
    expect(within(table).queryByRole("link")).toBeNull();
  });

  it("orders money by exact kopecks", async () => {
    setup({}, [
      {
        ...position,
        id: 32,
        quantity: "1",
        market_value: { amount: "90071992547409.01", currency: "RUB" },
      },
      {
        ...position,
        id: 33,
        quantity: "2",
        market_value: { amount: "90071992547409.02", currency: "RUB" },
      },
    ]);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(within(rows[2]).getAllByRole("cell")[1]).toHaveTextContent("2");
  });

  it("does not invent a share for zero total or hide known zero totals", async () => {
    setup({}, [
      {
        ...position,
        market_value: { amount: "0.00", currency: "RUB" },
        cost_basis: { amount: "0.00", currency: "RUB" },
        unrealized_result: { amount: "0.00", currency: "RUB" },
      },
    ]);
    const table = await screen.findByRole("table");
    const cells = within(within(table).getAllByRole("row")[2]).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent).join("")).not.toMatch(/%/);
    expect(screen.getByText(/Себестоимость:/)).toHaveTextContent("0 ₽");
    expect(screen.getByText(/Нереализованный результат:/)).toHaveTextContent("0 ₽");
  });
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
      preview_id: "synthetic-preview-id",
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
    expect(JSON.parse(String(apply?.[1]?.body)).preview_id).toBe("synthetic-preview-id");
    expect(JSON.parse(String(apply?.[1]?.body)).rows).toMatchObject([
      {
        position_snapshot_id: 31,
        accept_stale: false,
        expected_market_price_per_unit: { amount: "1200.00", currency: "RUB" },
      },
    ]);
  });

  it.each(["preview_evidence_invalid", "preview_changed", "network", "readback"])(
    "requires a new explicit preview after %s without resubmitting Apply",
    async (failure) => {
      const freshQuote = {
        ...quote,
        preview_id: "synthetic-preview-id",
        rows: [{ ...quote.rows[0], status: "ok", freshness_status: "ok", apply_allowed: true }],
      };
      const { fetchMock } = setup({
        "POST /api/months/7/quote-preview": () => json(freshQuote),
        "POST /api/months/7/quote-apply": () => {
          if (failure === "network") return Promise.reject(new TypeError("Failed to fetch"));
          if (failure === "readback")
            return json({
              reporting_month_id: 7,
              applied_count: 1,
              rows: [
                {
                  position_snapshot_id: 31,
                  market_price_per_unit: { amount: "200.00", currency: "RUB" },
                  price_date: "2031-01-31",
                  price_source: "t_invest",
                },
              ],
            });
          return json({ error: { code: failure, message: "synthetic", details: [] } }, 409);
        },
      });
      const user = userEvent.setup();
      await screen.findByText("Synthetic Fund (SYN)");
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview"))).toBe(
        false,
      );
      await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
      await user.click(await screen.findByRole("button", { name: "Применить выбранные" }));
      const message =
        failure === "preview_evidence_invalid"
          ? /Предпросмотр больше недействителен/
          : failure === "preview_changed"
            ? /Котировка изменилась/
            : /Результат применения не подтверждён/;
      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Применить выбранные" })).not.toBeInTheDocument();
      expect(screen.queryByText(/Котировки применены/)).not.toBeInTheDocument();
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).includes("quote-apply")),
      ).toHaveLength(1);
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).includes("quote-preview")),
      ).toHaveLength(1);
    },
  );

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

  it("maps an unmapped quote row contextually and requires an explicit new preview", async () => {
    const user = userEvent.setup();
    const unmappedRow = {
      ...quote.rows[0],
      status: "unmapped",
      mapping_state: "unmapped",
      identity: null,
      proposed_market_price_per_unit: null,
      proposed_price_date: null,
      proposed_quote_kind: null,
      proposed_raw_price: null,
      proposed_raw_price_basis: null,
      fetched_at_utc: null,
      freshness_status: null,
      failure_reason: "unmapped",
      apply_allowed: false,
    };
    const mappedRow = {
      ...quote.rows[0],
      status: "ok",
      freshness_status: "ok",
      apply_allowed: true,
    };
    const mappedIdentity = {
      provider: "t_invest",
      provider_instrument_id: "synthetic-uid",
      provider_venue_id: null,
    };
    let mappingState = "unmapped";
    let previewCalls = 0;
    const { fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => {
        previewCalls += 1;
        return json({ ...quote, rows: [mappingState === "mapped" ? mappedRow : unmappedRow] });
      },
      "GET /api/instruments/21/market-mapping": () =>
        json({
          instrument_id: 21,
          state: mappingState,
          identity: mappingState === "mapped" ? mappedIdentity : null,
          instrument_isin: null,
          legacy_moex_secid: null,
        }),
      "PUT /api/instruments/21/market-mapping?verify=true": () => {
        mappingState = "mapped";
        return json({
          instrument_id: 21,
          state: "mapped",
          identity: mappedIdentity,
          instrument_isin: null,
          legacy_moex_secid: null,
        });
      },
    });
    await screen.findByText("Synthetic Fund (SYN)");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-preview"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("market-mapping"))).toBe(
      false,
    );

    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    expect(screen.getByText("Внешний источник не настроен")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("market-mapping"))).toBe(
      false,
    );

    await user.click(screen.getByRole("button", { name: "Сопоставить инструмент Synthetic Fund" }));
    const dialog = await screen.findByRole("dialog", { name: "Источник котировки" });
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url) === "/api/instruments/21/market-mapping" && (init?.method ?? "GET") === "GET",
      ),
    ).toBe(true);
    await user.type(
      within(dialog).getByLabelText("Идентификатор инструмента T-Invest"),
      "synthetic-uid",
    );
    await user.click(within(dialog).getByRole("button", { name: "Сохранить источник" }));
    await waitFor(() => expect(mappingState).toBe("mapped"));
    const put = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url) === "/api/instruments/21/market-mapping?verify=true" && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
      provider: "t_invest",
      provider_instrument_id: "synthetic-uid",
    });
    expect(await within(dialog).findByText("T-Invest · synthetic-uid")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).toBeNull();
    expect(screen.getByText(/Сопоставление сохранено/)).toBeInTheDocument();
    expect(screen.getByText(/Запроси новый предпросмотр/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    expect(previewCalls).toBe(2);
    expect(screen.getByRole("button", { name: "Применить выбранные" })).toBeEnabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("keeps the existing preview when a contextual mapping save fails", async () => {
    const user = userEvent.setup();
    const unmappedRow = {
      ...quote.rows[0],
      status: "unmapped",
      mapping_state: "unmapped",
      identity: null,
      proposed_market_price_per_unit: null,
      proposed_price_date: null,
      failure_reason: "unmapped",
      apply_allowed: false,
    };
    const { fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => json({ ...quote, rows: [unmappedRow] }),
      "GET /api/instruments/21/market-mapping": () =>
        json({
          instrument_id: 21,
          state: "unmapped",
          identity: null,
          instrument_isin: null,
          legacy_moex_secid: null,
        }),
      "PUT /api/instruments/21/market-mapping?verify=true": () =>
        json(
          {
            error: {
              code: "mapping_verify_failed",
              message: "Инструмент не подтверждён внешним источником.",
              details: [],
            },
          },
          409,
        ),
    });
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    await user.click(screen.getByRole("button", { name: "Сопоставить инструмент Synthetic Fund" }));
    const dialog = await screen.findByRole("dialog", { name: "Источник котировки" });
    await user.type(
      within(dialog).getByLabelText("Идентификатор инструмента T-Invest"),
      "synthetic-uid",
    );
    await user.click(within(dialog).getByRole("button", { name: "Сохранить источник" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /Инструмент не подтверждён внешним источником/,
    );
    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.getByRole("table", { name: "Предпросмотр котировок" })).toBeInTheDocument();
    expect(screen.queryByText(/Сопоставление сохранено/)).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("opens the validated mapping flow for an ambiguous quote row", async () => {
    const user = userEvent.setup();
    const ambiguousRow = {
      ...quote.rows[0],
      status: "ambiguous",
      failure_reason: "ambiguous",
      apply_allowed: false,
    };
    const existingIdentity = {
      provider: "t_invest",
      provider_instrument_id: "old-uid",
      provider_venue_id: null,
    };
    let saved = false;
    const { fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => json({ ...quote, rows: [ambiguousRow] }),
      "GET /api/instruments/21/market-mapping": () =>
        json({
          instrument_id: 21,
          state: "mapped",
          identity: existingIdentity,
          instrument_isin: null,
          legacy_moex_secid: null,
        }),
      "PUT /api/instruments/21/market-mapping?verify=true": () => {
        saved = true;
        return json({
          instrument_id: 21,
          state: "mapped",
          identity: { ...existingIdentity, provider_instrument_id: "synthetic-uid" },
          instrument_isin: null,
          legacy_moex_secid: null,
        });
      },
    });
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    expect(screen.getByText("Нельзя выбрать источник автоматически")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сопоставить инструмент Synthetic Fund" }));
    const dialog = await screen.findByRole("dialog", { name: "Источник котировки" });
    expect(within(dialog).getByText("T-Invest · old-uid")).toBeInTheDocument();
    const uid = within(dialog).getByLabelText("Идентификатор инструмента T-Invest");
    await user.clear(uid);
    await user.type(uid, "synthetic-uid");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить источник" }));
    await waitFor(() => expect(saved).toBe(true));
    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).toBeNull();
    expect(screen.getByText(/Сопоставление сохранено/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("quote-apply"))).toBe(false);
  });

  it("invalidates the preview when quote updates are excluded from the dialog", async () => {
    const user = userEvent.setup();
    const unmappedRow = {
      ...quote.rows[0],
      status: "unmapped",
      mapping_state: "unmapped",
      identity: null,
      proposed_market_price_per_unit: null,
      proposed_price_date: null,
      failure_reason: "unmapped",
      apply_allowed: false,
    };
    let excluded = false;
    const { fetchMock } = setup({
      "POST /api/months/7/quote-preview": () => json({ ...quote, rows: [unmappedRow] }),
      "GET /api/instruments/21/market-mapping": () =>
        json({
          instrument_id: 21,
          state: excluded ? "excluded" : "unmapped",
          identity: null,
          instrument_isin: null,
          legacy_moex_secid: null,
        }),
      "PUT /api/instruments/21/market-mapping/exclusion": () => {
        excluded = true;
        return json({
          instrument_id: 21,
          state: "excluded",
          identity: null,
          instrument_isin: null,
          legacy_moex_secid: null,
        });
      },
    });
    await screen.findByText("Synthetic Fund (SYN)");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await screen.findByRole("table", { name: "Предпросмотр котировок" });
    await user.click(screen.getByRole("button", { name: "Сопоставить инструмент Synthetic Fund" }));
    const dialog = await screen.findByRole("dialog", { name: "Источник котировки" });
    await user.click(within(dialog).getByRole("button", { name: "Отключить обновление" }));
    await waitFor(() => expect(excluded).toBe(true));
    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).toBeNull();
    expect(screen.getByText(/Обновление котировок для инструмента отключено/)).toBeInTheDocument();
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
