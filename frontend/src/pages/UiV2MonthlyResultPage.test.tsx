import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportingMonth } from "../api/types";
import { rub } from "../lib/money";
import { createQueryClient } from "../queryClient";
import { uiV2Months } from "../test/uiV2Fixtures";
import UiV2MonthlyResultPage from "../ui-v2/UiV2MonthlyResultPage";

const latest = uiV2Months[0];
const older = uiV2Months[2];

function result(month: ReportingMonth) {
  return {
    month,
    result_by_account: [
      {
        account_id: 7,
        account_name: "Тестовый счёт",
        account_type: "brokerage",
        cash_income: rub("125.00"),
        unrealized_result: rub("-40.00"),
      },
      {
        account_id: 8,
        account_name: "Нулевой счёт",
        account_type: "iis",
        cash_income: rub("0.00"),
        unrealized_result: rub("0.00"),
      },
    ],
    result_by_instrument_class: [
      {
        instrument_type: "bond",
        market_value: rub("800.00"),
        cost_basis: rub("840.00"),
        realized_result: rub("125.00"),
        unrealized_result: rub("-40.00"),
      },
      {
        instrument_type: "stock",
        market_value: null,
        cost_basis: null,
        realized_result: rub("15.00"),
        unrealized_result: null,
      },
    ],
  };
}

type DashboardFixture = Omit<ReturnType<typeof result>, "result_by_account"> & {
  result_by_account?: ReturnType<typeof result>["result_by_account"];
};

function Navigation() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <output data-testid="location">{`${location.pathname}${location.search}`}</output>
      <button onClick={() => navigate(-1)} type="button">
        Back
      </button>
      <button
        onClick={() => navigate(`/v2/capital/monthly-result?month=${older.id}`)}
        type="button"
      >
        Older
      </button>
      <button
        onClick={() => navigate(`/v2/capital/monthly-result?month=${latest.id}`)}
        type="button"
      >
        Latest
      </button>
    </>
  );
}

function setup(path = "/v2/capital/monthly-result") {
  const months = [...uiV2Months];
  const reads: string[] = [];
  const state = {
    months,
    failMonths: false,
    failDashboard: false,
    payload: result(latest) as DashboardFixture,
    pendingOlder: null as Promise<void> | null,
    pendingLatest: null as Promise<void> | null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = options?.method ?? "GET";
      reads.push(`${method} ${url.pathname}`);
      if (method !== "GET") throw new Error(`Unexpected write: ${method}`);
      const failed = url.pathname === "/api/months" ? state.failMonths : state.failDashboard;
      const data = url.pathname === "/api/months" ? state.months : state.payload;
      if (url.pathname !== "/api/months" && !/^\/api\/months\/\d+\/dashboard$/.test(url.pathname)) {
        throw new Error(`Unexpected API: ${url.pathname}`);
      }
      if (url.pathname === `/api/months/${older.id}/dashboard` && state.pendingOlder) {
        await state.pendingOlder;
      }
      if (url.pathname === `/api/months/${latest.id}/dashboard` && state.pendingLatest) {
        await state.pendingLatest;
      }
      return new Response(
        JSON.stringify(
          failed
            ? { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } }
            : data,
        ),
        {
          status: failed ? 503 : 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    }),
  );
  const client = createQueryClient();
  const mounted = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Navigation />
        <Routes>
          <Route path="v2/capital/monthly-result" element={<UiV2MonthlyResultPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, reads, state, ...mounted };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("UiV2MonthlyResultPage", () => {
  it("defaults explicitly to latest CLOSED and keeps exact row money and view URL", async () => {
    const { reads } = setup();
    const accounts = await screen.findByRole("table", { name: "Результат по счетам" });
    expect(reads).toContain(`GET /api/months/${latest.id}/dashboard`);
    expect(
      screen.getByText(/Нереализованный результат — состояние открытых позиций/),
    ).toBeInTheDocument();
    expect(within(accounts).getByText("Тестовый счёт")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Текущий отчёт →" })).toHaveAttribute("href", "/v2");
    expect(within(accounts).getByText(/\+85\s*₽/)).toBeInTheDocument();
    expect(within(accounts).getAllByText(/^0\s*₽$/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "По классам" }));
    const classes = screen.getByRole("table", { name: "Результат по классам инструментов" });
    expect(screen.getByTestId("location")).toHaveTextContent("view=classes");
    expect(within(classes).getByText(/^800\s*₽$/)).toBeInTheDocument();
    expect(within(classes).getByText(/^840\s*₽$/)).toBeInTheDocument();
    const cashOnly = within(classes).getByText("Акции").closest("tr");
    if (!cashOnly) throw new Error("Cash-only class row missing");
    expect(within(cashOnly).getAllByText("—")).toHaveLength(4);
    expect(within(cashOnly).getByText(/\+15\s*₽/)).toBeInTheDocument();
    expect(reads.filter((read) => read.endsWith("/dashboard"))).toHaveLength(1);
  });

  it("loads an older CLOSED month from URL and preserves it through view switching", async () => {
    const { reads, state } = setup(`/v2/capital/monthly-result?month=${older.id}&view=classes`);
    state.payload = result(older);
    await screen.findByRole("table", { name: "Результат по классам инструментов" });
    expect(reads).toContain(`GET /api/months/${older.id}/dashboard`);
    expect(screen.getByTestId("v2-report-context")).toHaveAttribute("data-context", "historical");
    fireEvent.click(screen.getByRole("button", { name: "По счетам" }));
    expect(screen.getByTestId("location")).toHaveTextContent(`month=${older.id}&view=accounts`);
    expect(screen.getByRole("link", { name: "Отчёт месяца →" })).toHaveAttribute(
      "href",
      `/v2/reports/${older.id}`,
    );
  });

  it("switches the closed month locally and restores the URL context with Back", async () => {
    const { state } = setup("/v2/capital/monthly-result?view=classes");
    await screen.findByRole("table", { name: "Результат по классам инструментов" });
    state.payload = result(older);
    fireEvent.change(screen.getByLabelText("Закрытый месяц"), {
      target: { value: String(older.id) },
    });
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(`view=classes&month=${older.id}`),
    );
    await screen.findByRole("table", { name: "Результат по классам инструментов" });
    state.payload = result(latest);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/v2/capital/monthly-result?view=classes",
      ),
    );
    await screen.findByRole("table", { name: "Результат по классам инструментов" });
  });

  it.each(["month=bad", "month=999", "month=12", "month=91&month=90", "month=0"])(
    "never substitutes latest for invalid explicit %s",
    async (search) => {
      const { reads } = setup(`/v2/capital/monthly-result?${search}`);
      expect(await screen.findByText("Закрытый отчёт не найден")).toBeInTheDocument();
      expect(reads.filter((read) => read.endsWith("/dashboard"))).toHaveLength(0);
    },
  );

  it("hides a reopened month and stale dashboard response", async () => {
    const { client, state } = setup(`/v2/capital/monthly-result?month=${latest.id}`);
    await screen.findByRole("table", { name: "Результат по счетам" });
    state.months[0] = { ...latest, status: "draft" };
    await client.invalidateQueries({ queryKey: ["months"] });
    expect(await screen.findByText("Закрытый отчёт не найден")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("keeps the previous month hidden after a new URL and mismatched dashboard response", async () => {
    const { reads } = setup();
    await screen.findByRole("table", { name: "Результат по счетам" });
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    expect(await screen.findByText("Результат отчёта не подтверждён")).toBeInTheDocument();
    expect(reads).toContain(`GET /api/months/${older.id}/dashboard`);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("does not show a late response from the previous URL", async () => {
    const { reads, state } = setup();
    await screen.findByRole("table", { name: "Результат по счетам" });
    let releaseOlder: (() => void) | undefined;
    state.pendingOlder = new Promise<void>((resolve) => {
      releaseOlder = resolve;
    });
    state.payload = result(older);
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => expect(reads).toContain(`GET /api/months/${older.id}/dashboard`));
    expect(screen.queryByRole("table")).toBeNull();
    state.payload = result(latest);
    fireEvent.click(screen.getByRole("button", { name: "Latest" }));
    releaseOlder?.();
    await screen.findByRole("table", { name: "Результат по счетам" });
    expect(screen.getByTestId("location")).toHaveTextContent(`month=${latest.id}`);
    expect(screen.getByTestId("v2-report-context")).toHaveTextContent("Июль 2031");
  });

  it("hides cached values through restore invalidation and ignores a late pre-restore read with reused month identity", async () => {
    const { client, reads, state } = setup();
    await screen.findByRole("table", { name: "Результат по счетам" });
    let releaseOld: (() => void) | undefined;
    state.pendingLatest = new Promise<void>((resolve) => {
      releaseOld = resolve;
    });
    const priorRead = client.invalidateQueries({ queryKey: ["dashboard", latest.id] });
    await waitFor(() =>
      expect(
        reads.filter((read) => read === `GET /api/months/${latest.id}/dashboard`),
      ).toHaveLength(2),
    );
    expect(screen.queryByRole("table")).toBeNull();

    // Restore retains id/year/month/snapshot_date but replaces monetary facts.
    state.payload = {
      ...result(latest),
      result_by_account: [
        {
          account_id: 7,
          account_name: "После восстановления",
          account_type: "brokerage",
          cash_income: rub("300.00"),
          unrealized_result: rub("0.00"),
        },
      ],
    };
    state.pendingLatest = null;
    const restoredRead = client.invalidateQueries();
    await waitFor(() =>
      expect(
        reads.filter((read) => read === `GET /api/months/${latest.id}/dashboard`),
      ).toHaveLength(3),
    );
    expect(screen.queryByText(/Тестовый счёт/)).toBeNull();
    releaseOld?.();
    await Promise.all([priorRead, restoredRead]);
    const table = await screen.findByRole("table", { name: "Результат по счетам" });
    expect(within(table).getByText("После восстановления")).toBeInTheDocument();
    expect(within(table).queryByText("Тестовый счёт")).toBeNull();
    expect(screen.getByTestId("v2-report-context")).toHaveTextContent("Июль 2031");
  });

  it("keeps positions-only and account-only cash events in their canonical rows", async () => {
    const { client, state } = setup();
    await screen.findByRole("table", { name: "Результат по счетам" });
    state.payload = {
      ...result(latest),
      result_by_account: [
        {
          account_id: 7,
          account_name: "Позиции",
          account_type: "brokerage",
          cash_income: rub("0.00"),
          unrealized_result: rub("95.00"),
        },
        {
          account_id: 8,
          account_name: "Только событие",
          account_type: "cash",
          cash_income: rub("15.00"),
          unrealized_result: rub("0.00"),
        },
      ],
      result_by_instrument_class: [
        {
          instrument_type: "bond",
          market_value: rub("195.00"),
          cost_basis: rub("100.00"),
          realized_result: rub("0.00"),
          unrealized_result: rub("95.00"),
        },
      ],
    };
    await client.invalidateQueries({ queryKey: ["dashboard", latest.id] });
    const accounts = await screen.findByRole("table", { name: "Результат по счетам" });
    expect(within(accounts).getByText("Позиции").closest("tr")).toHaveTextContent("+95");
    expect(within(accounts).getByText("Только событие").closest("tr")).toHaveTextContent("+15");
    fireEvent.click(screen.getByRole("button", { name: "По классам" }));
    const classes = screen.getByRole("table", { name: "Результат по классам инструментов" });
    expect(within(classes).getAllByRole("row")).toHaveLength(2);
    expect(within(classes).getByText("Облигации").closest("tr")).toHaveTextContent("0");
  });

  it("distinguishes request failure, missing slice and empty slice", async () => {
    const { client, state } = setup();
    await screen.findByRole("table", { name: "Результат по счетам" });
    state.failDashboard = true;
    await client.invalidateQueries({ queryKey: ["dashboard", latest.id] });
    expect(await screen.findByText("Не удалось загрузить денежный результат")).toBeInTheDocument();
    state.failDashboard = false;
    state.payload = { ...result(latest), result_by_account: undefined };
    await client.invalidateQueries({ queryKey: ["dashboard", latest.id] });
    expect(await screen.findByText("Детализация недоступна")).toBeInTheDocument();
    state.payload = { ...result(latest), result_by_account: [] };
    await client.invalidateQueries({ queryKey: ["dashboard", latest.id] });
    expect(await screen.findByText("Нет строк результата")).toBeInTheDocument();
  });
});
