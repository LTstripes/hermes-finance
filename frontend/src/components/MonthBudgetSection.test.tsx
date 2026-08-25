import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthBudgetSection } from "./MonthBudgetSection";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const expense = {
  id: 11,
  reporting_month_id: 7,
  category: "Аренда",
  amount: { amount: "50000.00", currency: "RUB" },
  expense_type: "mandatory",
  is_recurring: false,
  notes: "офис",
};

const saving = {
  id: 21,
  reporting_month_id: 7,
  destination: "Подушка",
  amount: { amount: "20000.00", currency: "RUB" },
  notes: "на чёрный день",
};

function setup({
  expenses = [expense],
  savings = [saving],
  readOnly = false,
}: {
  expenses?: unknown[];
  savings?: unknown[];
  readOnly?: boolean;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" && url === "/api/expenses?month_id=7") return jsonResponse(expenses);
    if (method === "GET" && url === "/api/savings?month_id=7") return jsonResponse(savings);
    if (method === "PATCH" && url === "/api/expenses/11") {
      return jsonResponse({ ...expense, amount: { amount: "51000.00", currency: "RUB" } });
    }
    if (method === "PATCH" && url === "/api/savings/21") {
      return jsonResponse({ ...saving, amount: { amount: "21000.00", currency: "RUB" } });
    }
    if (method === "POST" && url === "/api/expenses") return jsonResponse({ id: 12 }, 201);
    if (method === "POST" && url === "/api/savings") return jsonResponse({ id: 22 }, 201);
    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
      404,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MonthBudgetSection monthId={7} readOnly={readOnly} />);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthBudgetSection overflow edit", () => {
  it("keeps amount numeric and comment flexible while exposing edit/delete", async () => {
    setup();
    const user = userEvent.setup();
    const [expenseTable, savingTable] = await screen.findAllByRole("table");

    expect(expenseTable).toHaveTextContent(/50\s*000\s*₽/);
    expect(expenseTable).toHaveTextContent("офис");
    expect(within(expenseTable).queryByRole("button", { name: "Удал." })).toBeNull();

    await user.click(
      within(expenseTable).getByRole("button", { name: "Действия для расхода «Аренда»" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toHaveClass(
      "overflow-menu__item--danger",
    );

    await user.keyboard("{Escape}");
    await user.click(
      within(savingTable).getByRole("button", { name: "Действия для откладывания «Подушка»" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeEnabled();
  });

  it("patches an expense from preloaded values", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();
    const [expenseTable] = await screen.findAllByRole("table");
    await user.click(
      within(expenseTable).getByRole("button", { name: "Действия для расхода «Аренда»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    expect(screen.getByDisplayValue("Аренда")).toBeInTheDocument();
    expect(screen.getByDisplayValue("офис")).toBeInTheDocument();
    const amount = screen.getByDisplayValue("50000.00");
    await user.clear(amount);
    await user.type(amount, "51000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/expenses/11" && init?.method === "PATCH",
      );
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        category: "Аренда",
        amount: { amount: "51000.00", currency: "RUB" },
        notes: "офис",
      });
    });
  });

  it("patches a saving allocation from preloaded values", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();
    const tables = await screen.findAllByRole("table");
    await user.click(
      within(tables[1]).getByRole("button", { name: "Действия для откладывания «Подушка»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    expect(screen.getByDisplayValue("Подушка")).toBeInTheDocument();
    const amount = screen.getByDisplayValue("20000.00");
    await user.clear(amount);
    await user.type(amount, "21000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/savings/21" && init?.method === "PATCH",
      );
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        destination: "Подушка",
        amount: { amount: "21000.00", currency: "RUB" },
      });
    });
  });

  it("still creates a new expense without going through overflow", async () => {
    const fetchMock = setup({ expenses: [], savings: [] });
    const user = userEvent.setup();
    await screen.findByText("Расходов пока нет.");
    await user.type(screen.getByLabelText("Категория расхода"), "Еда");
    await user.type(screen.getByLabelText("Сумма расхода"), "3000");
    await user.click(screen.getByRole("button", { name: "Добавить расход" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input) === "/api/expenses" && init?.method === "POST",
        ),
      ).toBe(true);
    });
  });

  it("disables budget mutations in a closed month", async () => {
    setup({ readOnly: true });
    const user = userEvent.setup();
    const [expenseTable] = await screen.findAllByRole("table");
    await user.click(
      within(expenseTable).getByRole("button", { name: "Действия для расхода «Аренда»" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Добавить расход" })).not.toBeInTheDocument();
  });
});
