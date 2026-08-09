import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthCloseoutSection } from "./MonthCloseoutSection";

const monthId = 7;

const kpis = {
  liquid_capital_net: { amount: "1000000.00", currency: "RUB" },
  liquid_capital_delta: null,
  forecast_monthly_passive_income: { amount: "15000.00", currency: "RUB" },
  passive_income_average: { amount: "12000.00", currency: "RUB" },
  passive_income_average_months: 6,
  passive_income_average_complete: false,
  goal_progress_pct: "42.5",
  goal_target: { amount: "100000.00", currency: "RUB" },
  mandatory_expenses: { amount: "50000.00", currency: "RUB" },
  mandatory_expense_coverage_pct: "40.0",
  mortgage_balance: { amount: "0.00", currency: "RUB" },
  mortgage_coverage_pct: null,
};

const dashboard = {
  month: {
    id: monthId,
    year: 2026,
    month: 7,
    status: "draft",
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  kpis,
  mortgage: {
    mortgage_balance: { amount: "0.00", currency: "RUB" },
    coverage_pct: null,
    gap: { amount: "0.00", currency: "RUB" },
  },
  warnings: ["Среднее за доступный период: учтено 6 месяцев из 12."],
  calculation_version: "1.0",
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return jsonResponse(
        { error: { code: "not_found", message: `no mock for ${key}`, details: [] } },
        404,
      );
    }
    return handler(init);
  });
}

function setup({ status }: { status: "draft" | "closed" }) {
  const onStatusChanged = vi.fn();
  const month = {
    id: monthId,
    year: 2026,
    month: 7,
    status,
    snapshot_date: "2026-07-31",
    source: "manual",
  };
  const fetchMock = mockFetchRouter({
    "GET /api/accounts": () => jsonResponse([]),
    "GET /api/comments?month_id=7": () => jsonResponse([]),
    "GET /api/months/7/summary": () =>
      jsonResponse({
        month,
        salary_tax: {
          tax: { amount: "0.00", currency: "RUB" },
          calculated_net: { amount: "0.00", currency: "RUB" },
        },
        salary_actual_net: { amount: "0.00", currency: "RUB" },
      }),
    "GET /api/months/7/dashboard": () => jsonResponse(dashboard),
    [`POST /api/months/${monthId}/close`]: () => jsonResponse({ ...month, status: "closed" }),
    [`POST /api/months/${monthId}/reopen`]: () => jsonResponse({ ...month, status: "draft" }),
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MonthCloseoutSection
      monthId={monthId}
      onStatusChanged={onStatusChanged}
      readOnly={status === "closed"}
      status={status}
      year={2026}
    />,
  );
  return { fetchMock, onStatusChanged };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthCloseoutSection closeout panel", () => {
  it("shows KPI preview and warnings for a draft month", async () => {
    setup({ status: "draft" });
    expect(await screen.findByText("Закрытие месяца")).toBeInTheDocument();
    expect(screen.getByText(/Liquid capital:/)).toBeInTheDocument();
    expect(screen.getByText(/Passive avg:/)).toBeInTheDocument();
    expect(screen.getByText(/Passive forecast:/)).toBeInTheDocument();
    expect(screen.getByText(/учтено 6 месяцев из 12/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeInTheDocument();
  });

  it("exposes accessible labels for symbol-only comment buttons", async () => {
    const month = {
      id: monthId,
      year: 2026,
      month: 7,
      status: "draft",
      snapshot_date: "2026-07-31",
      source: "manual",
    };
    const fetchMock = mockFetchRouter({
      "GET /api/accounts": () => jsonResponse([]),
      "GET /api/comments?month_id=7": () =>
        jsonResponse([
          { id: 1, position: 1, text: "Первый", reporting_month_id: monthId },
          { id: 2, position: 2, text: "Второй", reporting_month_id: monthId },
        ]),
      "GET /api/months/7/summary": () =>
        jsonResponse({
          month,
          salary_tax: {
            tax: { amount: "0.00", currency: "RUB" },
            calculated_net: { amount: "0.00", currency: "RUB" },
          },
          salary_actual_net: { amount: "0.00", currency: "RUB" },
        }),
      "GET /api/months/7/dashboard": () => jsonResponse(dashboard),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MonthCloseoutSection
        monthId={monthId}
        onStatusChanged={() => {}}
        readOnly={false}
        status="draft"
        year={2026}
      />,
    );
    expect(
      await screen.findAllByRole("button", { name: "Переместить комментарий выше" }),
    ).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Переместить комментарий ниже" })).toHaveLength(2);
  });

  it("closes the month after confirmation and notifies the parent", async () => {
    const { fetchMock, onStatusChanged } = setup({ status: "draft" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === `/api/months/${monthId}/close` && init?.method === "POST",
      ),
    ).toBe(true);
    expect(onStatusChanged).toHaveBeenCalled();
  });

  it("offers reopen for a closed month", async () => {
    const { fetchMock, onStatusChanged } = setup({ status: "closed" });
    const user = userEvent.setup();
    expect(await screen.findByRole("button", { name: "Открыть заново" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Открыть заново" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Открыть заново" }));
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === `/api/months/${monthId}/reopen` && init?.method === "POST",
      ),
    ).toBe(true);
    expect(onStatusChanged).toHaveBeenCalled();
  });
});
