import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const sampleMonths = [
  {
    id: 2,
    year: 2026,
    month: 7,
    status: "draft",
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  {
    id: 1,
    year: 2026,
    month: 6,
    status: "closed",
    snapshot_date: "2026-06-30",
    source: "manual",
  },
];

const emptySummary = {
  month: sampleMonths[0],
  salary_tax: {
    tax: { amount: "0.00", currency: "RUB" },
    calculated_net: { amount: "0.00", currency: "RUB" },
  },
  salary_actual_net: { amount: "0.00", currency: "RUB" },
};

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return new Response(
        JSON.stringify({
          error: { code: "not_found", message: `no mock for ${key}`, details: [] },
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
    return handler(init);
  });
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function periodCell(label: RegExp): HTMLElement {
  const table = screen.getByRole("table");
  const cell = within(table).getByText(label);
  const row = cell.closest("tr");
  if (!row) {
    throw new Error("row not found");
  }
  return row;
}

function monthEditorHandlers(month: (typeof sampleMonths)[0], incomes: unknown[] = []) {
  return {
    [`GET /api/months/${month.id}`]: () => jsonResponse(month),
    [`GET /api/incomes?month_id=${month.id}`]: () => jsonResponse(incomes),
    [`GET /api/months/${month.id}/summary`]: () =>
      jsonResponse({
        ...emptySummary,
        month,
        salary_tax: {
          tax: { amount: "26000.00", currency: "RUB" },
          calculated_net: { amount: "174000.00", currency: "RUB" },
        },
        salary_actual_net: { amount: "170000.00", currency: "RUB" },
      }),
    "GET /api/accounts": () =>
      jsonResponse([
        {
          id: 1,
          name: "Депозиты",
          account_type: "deposit",
          status: "active",
          external_code: null,
          include_in_capital: true,
          include_in_returns: true,
          notes: null,
        },
      ]),
    [`GET /api/deposits?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/cash-balances?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/cash-balances/total?month_id=${month.id}`]: () =>
      jsonResponse({
        reporting_month_id: month.id,
        total: { amount: "0.00", currency: "RUB" },
        total_in_capital: { amount: "0.00", currency: "RUB" },
      }),
    "GET /api/instruments?active=true": () =>
      jsonResponse([
        {
          id: 10,
          name: "Сбербанк",
          instrument_type: "stock",
          isin: null,
          ticker: "SBER",
          moex_secid: null,
          currency: "RUB",
          nominal_value: null,
          is_active: true,
          manual_price_allowed: true,
          notes: null,
        },
      ]),
    [`GET /api/positions?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/investment-flows?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/expected-flows?month_id=${month.id}&forecast_version=v1`]: () => jsonResponse([]),
    [`GET /api/expenses?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/savings?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/debts?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/properties?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/comments?month_id=${month.id}`]: () => jsonResponse([]),
    [`GET /api/months/${month.id}/dashboard`]: () =>
      jsonResponse({
        mortgage: {
          mortgage_balance: { amount: "0.00", currency: "RUB" },
          coverage_pct: null,
          gap: { amount: "0.00", currency: "RUB" },
        },
      }),
  };
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the dashboard in the application layout", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );

    render(<App />);

    expect(screen.getByText("Hermes Finance")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Дашборд" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Основная навигация" })).toBeInTheDocument();
    expect(screen.getByText("Ликвидный капитал")).toBeInTheDocument();
  });

  it("shows backend connected after a successful health check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ status: "ok", version: "0.1.0" }),
      }),
    );

    render(<App />);

    expect(await screen.findByText("Backend подключён")).toBeInTheDocument();
    expect(screen.getByText("API v0.1.0")).toBeInTheDocument();
  });

  it("shows backend unavailable when the health check fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(await screen.findByText("Backend недоступен")).toBeInTheDocument();
  });

  it("lists months, creates a draft, opens editor, and deletes with confirm", async () => {
    const user = userEvent.setup();
    const months = [...sampleMonths];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse(months),
        "POST /api/months": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}")) as {
            year: number;
            month: number;
            snapshot_date: string;
          };
          const created = {
            id: 3,
            year: body.year,
            month: body.month,
            status: "draft",
            snapshot_date: body.snapshot_date,
            source: "manual",
          };
          months.unshift(created);
          return jsonResponse(created, 201);
        },
        ...monthEditorHandlers(sampleMonths[0]),
        "DELETE /api/months/2": () => {
          const idx = months.findIndex((m) => m.id === 2);
          if (idx >= 0) {
            months.splice(idx, 1);
          }
          return new Response(null, { status: 204 });
        },
      }),
    );

    render(<App />);

    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    expect(screen.getByRole("heading", { level: 1, name: "Месяцы" })).toBeInTheDocument();

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText(/Июль/)).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText(/Июнь/)).toBeInTheDocument();

    const juneRow = periodCell(/Июнь/);
    expect(within(juneRow).queryByRole("button", { name: "Удалить" })).toBeNull();

    await user.clear(screen.getByLabelText("Год"));
    await user.type(screen.getByLabelText("Год"), "2026");
    await user.selectOptions(screen.getByLabelText("Месяц"), "8");
    await user.clear(screen.getByLabelText("Дата снимка"));
    await user.type(screen.getByLabelText("Дата снимка"), "2026-08-31");
    await user.click(screen.getByRole("button", { name: "Создать месяц" }));

    expect(await within(screen.getByRole("table")).findByText(/Август/)).toBeInTheDocument();

    const julyRow = periodCell(/Июль/);
    await user.click(within(julyRow).getByRole("link", { name: "Открыть" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Июль/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Зарплата gross")).toBeInTheDocument();
    expect(screen.getByLabelText(/Cashback/i)).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /К списку/i }));
    expect(await screen.findByRole("heading", { level: 1, name: "Месяцы" })).toBeInTheDocument();
    expect(await screen.findByRole("table")).toBeInTheDocument();

    const julyAgain = periodCell(/Июль/);
    await user.click(within(julyAgain).getByRole("button", { name: "Удалить" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Удалить draft" }));

    expect(await within(screen.getByRole("table")).findByText(/Август/)).toBeInTheDocument();
    expect(within(screen.getByRole("table")).queryByText(/Июль/)).not.toBeInTheDocument();
  });

  it("navigates to goals placeholder from the sidebar", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([]),
      }),
    );

    render(<App />);

    await user.click(screen.getByRole("link", { name: /Цели/i }));
    expect(screen.getByRole("heading", { level: 1, name: "Цели" })).toBeInTheDocument();
    expect(screen.getByText("API /api/goals отсутствует")).toBeInTheDocument();
  });

  it("clones a month into the next period and opens the new draft editor", async () => {
    const user = userEvent.setup();
    const months = [...sampleMonths];
    const clonedMonth = {
      id: 9,
      year: 2026,
      month: 8,
      status: "draft",
      snapshot_date: "2026-08-31",
      source: "manual",
    };

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse(months),
        "POST /api/months/2/clone": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}")) as {
            year: number;
            month: number;
            snapshot_date: string;
          };
          const cloned = {
            id: 9,
            year: body.year,
            month: body.month,
            status: "draft",
            snapshot_date: body.snapshot_date,
            source: "manual",
          };
          months.unshift(cloned);
          return jsonResponse(cloned, 201);
        },
        ...monthEditorHandlers(clonedMonth),
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    expect(await screen.findByRole("table")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Создать следующий месяц" }));
    expect(screen.getByRole("dialog", { name: /Создать следующий месяц/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Клонировать" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Август/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Зарплата gross")).toBeInTheDocument();
  });

  it("edits salary fields, shows dirty state, and saves incomes", async () => {
    const user = userEvent.setup();
    const posts: unknown[] = [];
    const month = sampleMonths[0];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        "POST /api/incomes": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          posts.push(body);
          return jsonResponse(
            {
              id: 100 + posts.length,
              reporting_month_id: month.id,
              received_at: null,
              is_recurring: Boolean(body.is_recurring),
              include_in_cash_flow: true,
              include_in_passive_income: false,
              notes: null,
              ...body,
            },
            201,
          );
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByLabelText("Зарплата gross")).toBeInTheDocument();
    expect(screen.queryByText(/несохранённые изменения/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Зарплата gross"), "200000");
    await user.type(screen.getByLabelText("Фактический net (employer)"), "170000");
    await user.type(screen.getByLabelText(/Cashback/i), "500");

    expect(screen.getAllByText(/несохранённые изменения/i).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText(/Сохранено/i)).toBeInTheDocument();
    expect(posts.some((p) => (p as { income_type: string }).income_type === "salary")).toBe(true);
    expect(posts.some((p) => (p as { income_type: string }).income_type === "cashback")).toBe(true);
  });

  it("adds a deposit and cash row on the month editor", async () => {
    const user = userEvent.setup();
    const month = sampleMonths[0];
    const deposits: unknown[] = [];
    const cashRows: unknown[] = [];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        [`GET /api/deposits?month_id=${month.id}`]: () => jsonResponse(deposits),
        [`GET /api/cash-balances?month_id=${month.id}`]: () => jsonResponse(cashRows),
        [`GET /api/cash-balances/total?month_id=${month.id}`]: () => {
          let totalKopecks = 0;
          for (const row of cashRows) {
            const amount = (row as { amount: { amount: string } }).amount.amount;
            const [whole, frac = "00"] = amount.split(".");
            totalKopecks += Number(whole) * 100 + Number(frac.padEnd(2, "0").slice(0, 2));
          }
          const text = `${Math.floor(totalKopecks / 100)}.${String(totalKopecks % 100).padStart(2, "0")}`;
          return jsonResponse({
            reporting_month_id: month.id,
            total: { amount: text, currency: "RUB" },
            total_in_capital: { amount: text, currency: "RUB" },
          });
        },
        "POST /api/deposits": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 50 + deposits.length,
            reporting_month_id: month.id,
            account_id: body.account_id,
            name: body.name,
            deposit_type: body.deposit_type,
            balance: body.balance,
            annual_rate: body.annual_rate,
            expected_monthly_interest: { amount: "1000.00", currency: "RUB" },
            actual_interest_received: body.actual_interest_received ?? {
              amount: "0.00",
              currency: "RUB",
            },
            notes: null,
            updated_at: "2026-07-31T12:00:00",
          };
          deposits.push(created);
          return jsonResponse(created, 201);
        },
        "POST /api/cash-balances": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 70 + cashRows.length,
            reporting_month_id: month.id,
            name: body.name,
            amount: body.amount,
            currency: "RUB",
            include_in_capital: body.include_in_capital !== false,
            notes: null,
          };
          cashRows.push(created);
          return jsonResponse(created, 201);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByRole("heading", { level: 2, name: "Депозиты" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Денежные средства" }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Название вклада"), "Вклад Альфа");
    await user.clear(screen.getByLabelText("Баланс вклада"));
    await user.type(screen.getByLabelText("Баланс вклада"), "100000");
    await user.click(screen.getByRole("button", { name: "Добавить вклад" }));

    expect(await screen.findByText("Вклад Альфа")).toBeInTheDocument();
    expect(screen.getAllByText(/1\s*000\s*₽/).length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText("Название cash"), "Кошелёк");
    await user.type(screen.getByLabelText("Сумма cash"), "2500.50");
    await user.click(screen.getByRole("button", { name: "Добавить cash" }));

    expect(await screen.findByText("Кошелёк")).toBeInTheDocument();
    expect(screen.getAllByText(/2\s*500[,.]50\s*₽/).length).toBeGreaterThan(0);
  });

  it("adds a brokerage position with backend-calculated market value", async () => {
    const user = userEvent.setup();
    const month = sampleMonths[0];
    const accounts = [
      {
        id: 1,
        name: "Депозиты",
        account_type: "deposit",
        status: "active",
        external_code: null,
        include_in_capital: true,
        include_in_returns: true,
        notes: null,
      },
      {
        id: 2,
        name: "Брокер",
        account_type: "brokerage",
        status: "active",
        external_code: null,
        include_in_capital: true,
        include_in_returns: true,
        notes: null,
      },
    ];
    const positions: unknown[] = [];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        "GET /api/accounts": () => jsonResponse(accounts),
        [`GET /api/positions?month_id=${month.id}`]: () => jsonResponse(positions),
        "POST /api/positions": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 80 + positions.length,
            reporting_month_id: month.id,
            account_id: body.account_id,
            instrument_id: body.instrument_id,
            quantity: body.quantity,
            average_cost_per_unit: body.average_cost_per_unit,
            market_price_per_unit: body.market_price_per_unit,
            market_value: { amount: "12500.00", currency: "RUB" },
            cost_basis: { amount: "10000.00", currency: "RUB" },
            unrealized_result: { amount: "2500.00", currency: "RUB" },
            accrued_interest: body.accrued_interest ?? null,
            price_source: body.price_source ?? "manual",
            price_date: body.price_date,
            notes: null,
            updated_at: "2026-07-31T12:00:00",
          };
          positions.push(created);
          return jsonResponse(created, 201);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByText("Позиции")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Счёт позиции"), "2");
    await user.selectOptions(screen.getByLabelText("Инструмент позиции"), "10");
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "10");
    await user.clear(screen.getByLabelText("Average cost"));
    await user.type(screen.getByLabelText("Average cost"), "1000");
    await user.clear(screen.getByLabelText("Market price"));
    await user.type(screen.getByLabelText("Market price"), "1250");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));

    expect(await screen.findAllByText(/SBER/)).not.toHaveLength(0);
    expect(await screen.findAllByText(/12\s*500\s*₽/)).not.toHaveLength(0);
    expect(screen.getAllByText(/2\s*500\s*₽/).length).toBeGreaterThan(0);
  });

  it("adds actual coupon and redemption flows with passive total", async () => {
    const user = userEvent.setup();
    const month = sampleMonths[0];
    const accounts = [
      {
        id: 2,
        name: "Брокер",
        account_type: "brokerage",
        status: "active",
        external_code: null,
        include_in_capital: true,
        include_in_returns: true,
        notes: null,
      },
    ];
    const flows: unknown[] = [];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        "GET /api/accounts": () => jsonResponse(accounts),
        [`GET /api/investment-flows?month_id=${month.id}`]: () => jsonResponse(flows),
        "POST /api/investment-flows": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 90 + flows.length,
            reporting_month_id: month.id,
            account_id: body.account_id,
            instrument_id: body.instrument_id ?? null,
            flow_type: body.flow_type,
            event_date: body.event_date,
            gross_amount: body.gross_amount,
            tax_amount: body.tax_amount ?? { amount: "0.00", currency: "RUB" },
            commission_amount: body.commission_amount ?? { amount: "0.00", currency: "RUB" },
            net_amount: body.net_amount,
            currency: "RUB",
            source: body.source,
            notes: null,
          };
          flows.push(created);
          return jsonResponse(created, 201);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByText("Фактические потоки")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Тип потока"), "coupon");
    await user.selectOptions(screen.getByLabelText("Счёт выплаты"), "2");
    await user.clear(screen.getByLabelText("Gross"));
    await user.type(screen.getByLabelText("Gross"), "1000");
    await user.clear(screen.getByLabelText("Net"));
    await user.type(screen.getByLabelText("Net"), "870");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));

    expect(await screen.findByText("passive income")).toBeInTheDocument();
    expect(screen.getAllByText(/870\s*₽/).length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText("Тип потока"), "redemption");
    await user.clear(screen.getByLabelText("Gross"));
    await user.type(screen.getByLabelText("Gross"), "5000");
    await user.clear(screen.getByLabelText("Net"));
    await user.type(screen.getByLabelText("Net"), "5000");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));

    expect(await screen.findByText(/не доход \(погашение\)/)).toBeInTheDocument();
    // passive total stays 870, redemption separate
    expect(screen.getByText(/Passive income \(net\)/i)).toBeInTheDocument();
  });

  it("adds mandatory expense and saving allocation", async () => {
    const user = userEvent.setup();
    const month = sampleMonths[0];
    const expenses: unknown[] = [];
    const savings: unknown[] = [];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        [`GET /api/expenses?month_id=${month.id}`]: () => jsonResponse(expenses),
        [`GET /api/savings?month_id=${month.id}`]: () => jsonResponse(savings),
        "POST /api/expenses": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 11,
            reporting_month_id: month.id,
            category: body.category,
            amount: body.amount,
            expense_type: body.expense_type,
            is_recurring: false,
            notes: body.notes ?? null,
          };
          expenses.push(created);
          return jsonResponse(created, 201);
        },
        "POST /api/savings": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 12,
            reporting_month_id: month.id,
            destination: body.destination,
            amount: body.amount,
            notes: body.notes ?? null,
          };
          savings.push(created);
          return jsonResponse(created, 201);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByRole("heading", { level: 2, name: "Расходы" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Категория расхода"), "Аренда");
    await user.type(screen.getByLabelText("Сумма расхода"), "50000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    expect(await screen.findByText("Аренда")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Назначение"), "Подушка");
    await user.type(screen.getByLabelText("Сумма savings"), "10000");
    await user.click(screen.getByRole("button", { name: "Добавить откладывание" }));
    expect(await screen.findByText("Подушка")).toBeInTheDocument();
  });

  it("adds credit card debt, property and month comment", async () => {
    const user = userEvent.setup();
    const month = sampleMonths[0];
    const debts: unknown[] = [];
    const properties: unknown[] = [];
    const comments: unknown[] = [];

    vi.stubGlobal(
      "fetch",
      mockFetchRouter({
        "GET /api/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
        "GET /api/months": () => jsonResponse([month]),
        ...monthEditorHandlers(month),
        [`GET /api/debts?month_id=${month.id}`]: () => jsonResponse(debts),
        [`GET /api/properties?month_id=${month.id}`]: () => jsonResponse(properties),
        [`GET /api/comments?month_id=${month.id}`]: () => jsonResponse(comments),
        "POST /api/debts": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 21,
            reporting_month_id: month.id,
            debt_type: body.debt_type,
            name: body.name,
            current_balance: body.current_balance,
            include_in_liquid_capital: true,
            notes: null,
          };
          debts.push(created);
          return jsonResponse(created, 201);
        },
        "POST /api/properties": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 22,
            reporting_month_id: month.id,
            name: body.name,
            estimated_value: body.estimated_value,
            mortgage_balance: body.mortgage_balance,
            monthly_payment: body.monthly_payment,
            notes: null,
          };
          properties.push(created);
          return jsonResponse(created, 201);
        },
        "POST /api/comments": async (init) => {
          const body = JSON.parse(String(init?.body ?? "{}"));
          const created = {
            id: 23,
            reporting_month_id: month.id,
            position: comments.length + 1,
            text: body.text,
          };
          comments.push(created);
          return jsonResponse(created, 201);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    await user.click(
      within(await screen.findByRole("table")).getByRole("link", { name: "Открыть" }),
    );

    expect(await screen.findByRole("heading", { level: 2, name: "Долги" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Текущий баланс долга"), "15000");
    await user.click(screen.getByRole("button", { name: "Добавить долг" }));
    expect(await screen.findByText("Кредитка")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Название объекта"), "Квартира");
    await user.type(screen.getByLabelText("Стоимость"), "10000000");
    await user.type(screen.getByLabelText("Остаток ипотеки"), "4000000");
    await user.type(screen.getByLabelText("Ежемесячный платёж"), "45000");
    await user.click(screen.getByRole("button", { name: "Добавить объект" }));
    expect(await screen.findByText("Квартира")).toBeInTheDocument();
    expect(screen.getAllByText(/Mortgage coverage/i).length).toBeGreaterThan(0);

    expect(screen.getByRole("heading", { level: 2, name: "Комментарии" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Основная цель" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Новый комментарий"), "Первый месяц");
    await user.click(screen.getByRole("button", { name: "Добавить комментарий" }));
    expect(await screen.findByText("Первый месяц")).toBeInTheDocument();
  });
});
