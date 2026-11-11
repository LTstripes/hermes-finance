import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import {
  makeUiV2ArchiveHistory,
  makeUiV2CapitalHistory,
  makeUiV2PassiveHistory,
  uiV2ArchiveMonths,
  uiV2Months,
} from "../test/uiV2Fixtures";
import { moneyText } from "./valueFormat";
import UiV2ReportsPage from "./UiV2ReportsPage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function setup(path = "/v2/reports") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2ArchiveMonths,
    composition: makeUiV2ArchiveHistory(),
    income: makeUiV2PassiveHistory(),
    incomeError: false,
    monthsError: false,
    compositionError: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = options?.method ?? "GET";
      reads.push(`${method} ${url.pathname}${url.search}`);
      if (method !== "GET") throw new Error(`Unexpected write: ${method}`);
      let data: unknown;
      let failed = false;
      switch (url.pathname) {
        case "/api/months":
          data = state.months;
          failed = state.monthsError;
          break;
        case "/api/analytics/capital-composition":
          data = state.composition;
          failed = state.compositionError;
          break;
        case "/api/analytics/passive-income":
          data = state.income;
          failed = state.incomeError;
          break;
        default:
          throw new Error(`Unexpected API: ${url.pathname}${url.search}`);
      }
      return new Response(
        JSON.stringify(
          failed
            ? { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } }
            : data,
        ),
        { status: failed ? 503 : 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <Routes>
            <Route path="v2/reports" element={<UiV2ReportsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { client, mount, reads, state };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("unified months list at the reports address", () => {
  it("shows canonical closed capital and passive income alongside drafts, without computing deltas", async () => {
    const { mount, reads } = setup();
    mount();
    expect(await screen.findByRole("heading", { name: "Все месяцы", level: 1 })).toBeVisible();
    const row = await screen.findByTestId("reports-row-90");
    await waitFor(() => expect(row).toHaveTextContent("2 761 300 ₽"));
    expect(within(row).getByRole("link", { name: "Открыть" })).toHaveAttribute(
      "href",
      "/v2/close?month=90",
    );
    expect(screen.getByTestId("reports-row-12")).toHaveTextContent("Черновик");
    expect(screen.queryByRole("columnheader", { name: "Изменение" })).toBeNull();
    expect(screen.queryByText("отчёта нет")).toBeNull();
    expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
    expect(reads).toContain("GET /api/analytics/passive-income?reporting_month_id=91");
    const income = makeUiV2PassiveHistory().points.find((point) => point.reporting_month_id === 90);
    expect(income).toBeDefined();
    expect(within(row).getAllByRole("cell")[2]).toHaveAttribute(
      "title",
      moneyText(income!.passive_income_actual),
    );
  });
  it("keeps the exact known subtotal with a short partial label and one explanation", async () => {
    const { mount, state } = setup();
    // Select by ID because the fixture also contains a prior-year point.
    const point = state.composition.points.find((point) => point.reporting_month_id === 90)!;
    point.portfolio_source_coverage = {
      status: "partial",
      reason_codes: [],
      missing_account_ids: [2],
    };
    mount();
    const row = await screen.findByTestId("reports-row-90");
    await waitFor(() => expect(row).toHaveTextContent("2 761 300 ₽неполный"));
    expect(screen.getAllByText(/Неполный капитал — итог известных записей/)).toHaveLength(1);
    expect(within(row).queryByText(/нет снимка счёта/)).toBeNull();
  });
  it.each([false, true])(
    "hides unavailable capital even with partial source coverage %s",
    async (sourcePartial) => {
      const { mount, state } = setup();
      const point = state.composition.points.find((point) => point.reporting_month_id === 90)!;
      point.portfolio_source_coverage = {
        status: "unavailable",
        reason_codes: [],
        missing_account_ids: [2],
        ...(sourcePartial
          ? {
              source_account_financial_coverage: {
                status: "partial" as const,
                reason_codes: [],
                account_ids: [2],
                intake_count: 1,
              },
            }
          : {}),
      };
      mount();
      const row = await screen.findByTestId("reports-row-90");
      await waitFor(() => expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("—"));
      expect(row).not.toHaveTextContent("2 761 300 ₽");
      expect(within(row).queryByText("неполный")).toBeNull();
    },
  );
  it("collapses consecutive missing capital without hiding the individual month actions", async () => {
    const { mount, state } = setup();
    state.months = state.months.filter(
      (month) => month.id === 91 || month.id === 90 || month.id === 89,
    );
    state.composition.points = state.composition.points.filter(
      (point) => point.reporting_month_id === 91,
    );
    mount();
    const summary = await screen.findByText(/Апрель 2031 — Май 2031 · без капитала · 2 мес/);
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(summary);
    expect(
      within(details)
        .getAllByRole("link", { name: "Открыть" })
        .map((link) => link.getAttribute("href")),
    ).toEqual(["/v2/close?month=90", "/v2/close?month=89"]);
  });
  it("keeps the single closed report and never invents a preceding report", async () => {
    const { mount, state } = setup();
    state.months = [uiV2Months[0], uiV2Months[1]];
    state.composition = makeUiV2CapitalHistory({ firstClosed: true });
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("reports-row-91")).toHaveTextContent("2 803 900 ₽"),
    );
    expect(screen.queryByText("отчёта нет")).toBeNull();
  });
  it("hides failed capital and recovers through the existing refresh action", async () => {
    const { mount, state } = setup();
    state.compositionError = true;
    mount();
    await screen.findByText(/Часть сумм недоступна/);
    expect(screen.getByTestId("months-table")).not.toHaveTextContent("2 761 300 ₽");
    state.compositionError = false;
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    await waitFor(() =>
      expect(screen.getByTestId("reports-row-90")).toHaveTextContent("2 761 300 ₽"),
    );
  });
  it("fails capital closed when the latest report identity does not match", async () => {
    const { mount, state, client } = setup();
    state.composition.points.pop();
    mount();
    await screen.findByTestId("months-table");
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(screen.getByTestId("months-table")).not.toHaveTextContent("2 761 300 ₽");
  });
  it("shows draft actions without reading closed money when no month is closed", async () => {
    const { mount, reads, state } = setup();
    state.months = [uiV2Months[1]];
    mount();
    expect(await screen.findByRole("link", { name: "Открыть" })).toHaveAttribute(
      "href",
      "/v2/close?month=12",
    );
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  });
  it("recovers from a month read error without substituting money", async () => {
    const { mount, reads, state } = setup();
    state.monthsError = true;
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Список месяцев недоступен");
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
    state.monthsError = false;
    fireEvent.click(screen.getByRole("button", { name: "Обновить список" }));
    await screen.findByTestId("reports-row-90");
  });
  it("shows known zero as zero and never as missing capital", async () => {
    const { mount, state } = setup();
    state.composition.points = makeUiV2CapitalHistory({ zero: true }).points;
    mount();
    await waitFor(() => expect(screen.getByTestId("reports-row-91")).toHaveTextContent("0 ₽"));
  });
  it.each(["latest", "snapshot"])(
    "rejects passive income for a different %s identity",
    async (mismatch) => {
      const { mount, state, client } = setup();
      if (mismatch === "latest") state.income.latest_closed_report_id = 999;
      else
        state.income.points = state.income.points.map((point) => ({
          ...point,
          snapshot_date: "2031-01-01",
        }));
      mount();
      await waitFor(() =>
        expect(screen.getByTestId("reports-row-90")).toHaveTextContent("2 761 300 ₽"),
      );
      await waitFor(() => expect(client.isFetching()).toBe(0));
      expect(
        within(screen.getByTestId("reports-row-90")).getAllByRole("cell")[2],
      ).toHaveTextContent("—");
    },
  );
});
