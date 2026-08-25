import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthAssetsSection } from "./MonthAssetsSection";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = {
  id: 11,
  name: "Депозиты",
  account_type: "deposit",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const deposit = {
  id: 21,
  reporting_month_id: 7,
  account_id: 11,
  name: "Вклад Альфа",
  deposit_type: "deposit",
  balance: { amount: "100000.00", currency: "RUB" },
  annual_rate: "12.00",
  expected_monthly_interest: { amount: "1000.00", currency: "RUB" },
  actual_interest_received: { amount: "900.00", currency: "RUB" },
  notes: null,
  updated_at: "2031-01-31T00:00:00",
};

function setup({
  deposits = [deposit],
  readOnly = false,
}: {
  deposits?: unknown[];
  readOnly?: boolean;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" && url === "/api/accounts") return jsonResponse([account]);
    if (method === "GET" && url === "/api/deposits?month_id=7") return jsonResponse(deposits);
    if (method === "GET" && url === "/api/cash-balances?month_id=7") return jsonResponse([]);
    if (method === "GET" && url === "/api/cash-balances/total?month_id=7") {
      return jsonResponse({
        total: { amount: "0.00", currency: "RUB" },
        total_in_capital: { amount: "0.00", currency: "RUB" },
      });
    }
    if (method === "PATCH" && url === "/api/deposits/21") {
      return jsonResponse({
        ...deposit,
        balance: { amount: "110000.00", currency: "RUB" },
        updated_at: "2031-01-31T01:00:00",
      });
    }
    if (method === "DELETE" && url === "/api/deposits/21") {
      return new Response(null, { status: 204 });
    }
    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
      404,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MonthAssetsSection monthId={7} readOnly={readOnly} />);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthAssetsSection deposit actions", () => {
  it("hides inline Изм./Удал. and exposes overflow edit/delete", async () => {
    setup();
    const user = userEvent.setup();
    const table = await screen.findByRole("table");

    expect(within(table).queryByRole("button", { name: "Изм." })).toBeNull();
    expect(within(table).queryByRole("button", { name: "Удал." })).toBeNull();
    await user.click(
      within(table).getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toHaveClass(
      "overflow-menu__item--danger",
    );
  });

  it("loads current deposit values and patches on save", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));

    expect(screen.getByDisplayValue("Вклад Альфа")).toBeInTheDocument();
    expect(screen.getByDisplayValue("100000.00")).toBeInTheDocument();
    const balance = screen.getByDisplayValue("100000.00");
    await user.clear(balance);
    await user.type(balance, "110000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/deposits/21" && init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        name: "Вклад Альфа",
        balance: { amount: "110000.00", currency: "RUB" },
      });
    });
  });

  it("keeps delete behind a confirmed overflow path", async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    expect(screen.getByRole("alertdialog", { name: "Удалить вклад?" })).toHaveTextContent(
      "Вклад Альфа",
    );
  });

  it("disables deposit mutations in a closed month", async () => {
    setup({ readOnly: true });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Действия для вклада «Вклад Альфа»" }));
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Добавить вклад" })).not.toBeInTheDocument();
  });
});
