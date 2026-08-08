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

    expect(await screen.findByText("Депозиты")).toBeInTheDocument();
    expect(screen.getByText("Денежные средства")).toBeInTheDocument();

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
});
