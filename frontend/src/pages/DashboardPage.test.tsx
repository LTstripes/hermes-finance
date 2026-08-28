import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import { DashboardPage } from "./DashboardPage";

vi.mock("../components/charts/CapitalChart", () => ({
  CapitalChart: () => <div>capital chart stub</div>,
}));
vi.mock("../components/charts/PassiveIncomeChart", () => ({
  PassiveIncomeChart: () => <div>passive chart stub</div>,
}));

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const months = [
  {
    id: 1,
    year: 2031,
    month: 1,
    status: "closed",
    snapshot_date: "2031-01-31",
    source: "manual",
  },
  {
    id: 2,
    year: 2031,
    month: 2,
    status: "draft",
    snapshot_date: "2031-02-28",
    source: "manual",
  },
];

function dashboard(
  monthId: number,
  warning: string | null = null,
  historyStartMonth: string | null = null,
) {
  const month = months.find((row) => row.id === monthId) ?? months[0];
  return {
    month,
    kpis: {
      liquid_capital_net: { amount: "4820500.00", currency: "RUB" },
      liquid_capital_delta: { amount: "120000.00", currency: "RUB" },
      passive_income_actual: { amount: "860.00", currency: "RUB" },
      passive_income_delta: { amount: "-10.00", currency: "RUB" },
      forecast_monthly_passive_income: { amount: "86420.00", currency: "RUB" },
      forecast_annual_passive_income: { amount: "1037040.00", currency: "RUB" },
      passive_income_average: { amount: "85200.00", currency: "RUB" },
      passive_income_average_months: 6,
      passive_income_average_complete: false,
      passive_income_history_start_month: historyStartMonth,
      passive_income_average_months_used: historyStartMonth ? ["2031-05", "2031-06"] : [],
      goal_progress_pct: "68.0",
      goal_target: { amount: "100000.00", currency: "RUB" },
      mandatory_expenses: { amount: "150000.00", currency: "RUB" },
      mandatory_expense_coverage_pct: "56.8",
      actual_mandatory_expense_coverage_pct: "56.7",
      mortgage_balance: { amount: "12450000.00", currency: "RUB" },
      mortgage_coverage_pct: "38.7",
    },
    summary: {
      forecast: {
        breakdown: {
          expected_deposit_interest: { amount: "1200000.00", currency: "RUB" },
          expected_coupon_net: { amount: "50000.00", currency: "RUB" },
          expected_dividend_component: { amount: "100000.00", currency: "RUB" },
          other_expected_capital_income: { amount: "0.00", currency: "RUB" },
        },
        is_approximate: true,
        warnings: [
          "Проценты по вкладам оценены по текущему месячному прогнозу × 12; срок и изменение ставки не моделируются.",
        ],
      },
    },
    mortgage: {
      mortgage_balance: { amount: "12450000.00", currency: "RUB" },
      coverage_pct: "38.7",
      gap: { amount: "7629500.00", currency: "RUB" },
    },
    historical_series: [],
    asset_allocation: [],
    result_by_account: [],
    result_by_instrument_class: [],
    warnings: warning ? [warning] : [],
    calculation_version: "g04-test",
  };
}

function setupDashboard(
  dashboardResponse: (monthId: number) => Response,
  monthsResponse: Response = jsonResponse(months),
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/months") return monthsResponse;
    if (url === "/api/months/2/dashboard") return dashboardResponse(2);
    if (url === "/api/months/1/dashboard") return dashboardResponse(1);
    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${url}`, details: [] } },
      404,
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DashboardPage R03-04 semantics", () => {
  it("keeps four overview blocks with distinct fact, forecast and coverage semantics", async () => {
    const fetchMock = setupDashboard((monthId) =>
      jsonResponse(dashboard(monthId, monthId === 2 ? "Среднее доступно за 6 месяцев" : null)),
    );
    const user = userEvent.setup();

    const selector = await screen.findByLabelText("Отчётный месяц");
    await waitFor(() => expect(selector).toHaveValue("2"));
    expect(await screen.findByText(/4\s*820\s*500\s*₽/)).toBeInTheDocument();

    const overview = screen.getByRole("region", { name: "Ключевое состояние" });
    expect(within(overview).getAllByRole("article")).toHaveLength(4);
    expect(within(overview).getByText("Изменение за месяц")).toBeInTheDocument();
    expect(within(overview).getByText("Факт · выбранный месяц")).toBeInTheDocument();
    expect(within(overview).getByText("Прогноз · эквивалент за месяц")).toBeInTheDocument();
    expect(within(overview).getByText("Прогноз / цель")).toBeInTheDocument();
    expect(within(overview).getByText("Вклады")).toBeInTheDocument();
    expect(within(overview).getByText("Купоны")).toBeInTheDocument();
    expect(within(overview).getByText("Дивиденды")).toBeInTheDocument();
    expect(within(overview).getByText("Прочее")).toBeInTheDocument();
    expect(within(overview).getByText("Часть прогноза оценочная")).toBeInTheDocument();
    await user.click(within(overview).getByRole("button", { name: "Как составлен прогноз" }));
    expect(screen.getByText(/Ручной процент складывается с этой оценкой/)).toBeInTheDocument();
    expect(within(overview).getByText("6 закрытых месяцев из 12")).toBeInTheDocument();
    expect(within(overview).getByText("Покрытие расходов")).toBeInTheDocument();
    expect(within(overview).getByText("Среднее за закрытые месяцы")).toBeInTheDocument();
    expect(within(overview).getByText("Прогноз покрытия")).toBeInTheDocument();
    expect(within(overview).getByText("Покрытие ипотеки")).toBeInTheDocument();
    expect(within(overview).getByText("Остаток ипотеки")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Настроить цель →" })).toHaveAttribute(
      "href",
      "/goals",
    );

    expect(screen.queryByText("Среднее доступно за 6 месяцев")).toBeNull();
    expect(screen.queryByText(/По мере закрытия новых месяцев окно обновляется/)).toBeNull();
    await user.click(
      within(overview).getByRole("button", { name: "Почему среднее пока неполное" }),
    );
    expect(screen.getByText(/По мере закрытия новых месяцев окно обновляется/)).toBeInTheDocument();

    expect(screen.queryByText("Результат по классам и счетам")).toBeNull();
    expect(screen.queryByText("Распределение активов")).toBeNull();
    expect(screen.queryByText("Отчётные месяцы")).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть месяц" })).toHaveAttribute(
      "href",
      "/months/2",
    );
    expect(screen.getByRole("link", { name: "Все месяцы" })).toHaveAttribute("href", "/months");
    expect(screen.getByRole("link", { name: "Аналитика" })).toHaveAttribute("href", "/analytics");

    await user.selectOptions(selector, "1");
    expect(selector).toHaveValue("1");
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/months/1/dashboard"),
    ).toBe(true);
  });

  it("shows localized dashboard errors without bringing technical cards back", async () => {
    setupDashboard(() =>
      jsonResponse(
        { error: { code: "internal_error", message: "Dashboard API failed", details: [] } },
        500,
      ),
    );

    const alerts = await screen.findAllByRole("alert");
    expect(
      alerts.some(
        (alert) => alert.textContent === "Внутренняя ошибка приложения. Попробуй обновить данные.",
      ),
    ).toBe(true);
    expect(screen.getAllByText("Не удалось загрузить показатели")).toHaveLength(2);
    expect(screen.queryByText("Dashboard API failed")).toBeNull();
    expect(screen.queryByText("Распределение активов")).toBeNull();
    expect(screen.queryByText("Результат по классам и счетам")).toBeNull();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
  });

  it("presents backend-provided passive-income coverage and boundary metadata", async () => {
    setupDashboard(() => jsonResponse(dashboard(2, null, "2031-05")));

    const overview = await screen.findByRole("region", { name: "Ключевое состояние" });
    expect(await within(overview).findByText(/2031-05/)).toBeInTheDocument();
    expect(
      await within(overview).findByText(/Учтено 6 закрытых месяцев из 12/),
    ).toBeInTheDocument();
  });

  it("keeps dashboard cache entries separate and revalidates when returning", async () => {
    const fetchMock = setupDashboard((monthId) => jsonResponse(dashboard(monthId)));
    const user = userEvent.setup();
    const selector = await screen.findByLabelText("Отчётный месяц");
    await screen.findByText(/4\s*820\s*500\s*₽/);

    await user.selectOptions(selector, "1");
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/1/dashboard"),
      ).toHaveLength(1);
    });
    await user.selectOptions(selector, "2");
    await waitFor(() => expect(selector).toHaveValue("2"));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/2/dashboard"),
      ).toHaveLength(2);
    });

    expect(
      fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/2/dashboard"),
    ).toHaveLength(2);
  });

  it("cancels the previous selected-month request and ignores a late response", async () => {
    const requests = new Map<
      number,
      { resolve: (response: Response) => void; signal?: AbortSignal }
    >();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/months") return Promise.resolve(jsonResponse(months));
      const match = /\/api\/months\/(\d+)\/dashboard$/.exec(url);
      if (!match) return Promise.resolve(jsonResponse({ error: "not found" }, 404));
      const monthId = Number(match[1]);
      return new Promise<Response>((resolve) => {
        requests.set(monthId, { resolve, signal: init?.signal ?? undefined });
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const selector = await screen.findByLabelText("Отчётный месяц");
    await waitFor(() => expect(requests.get(2)).toBeDefined());
    const oldRequest = requests.get(2);
    const user = userEvent.setup();
    await user.selectOptions(selector, "1");
    await waitFor(() => expect(oldRequest?.signal?.aborted).toBe(true));

    const current = dashboard(1);
    current.kpis.liquid_capital_net.amount = "111.00";
    requests.get(1)?.resolve(jsonResponse(current));
    expect(await screen.findByText(/111\s*₽/)).toBeInTheDocument();

    const stale = dashboard(2);
    stale.kpis.liquid_capital_net.amount = "222.00";
    oldRequest?.resolve(jsonResponse(stale));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText(/111\s*₽/)).toBeInTheDocument();
    expect(screen.queryByText(/222\s*₽/)).toBeNull();
  });
});
