import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import {
  makeUiV2ArchiveHistory,
  makeUiV2CapitalHistory,
  uiV2ArchiveMonths,
  uiV2Months,
} from "../test/uiV2Fixtures";
import UiV2ReportsPage from "../ui-v2/UiV2ReportsPage";

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

describe("UI v2 reports archive", () => {
  it("groups closed reports by year, marks the current report and keeps drafts out of history", async () => {
    const { mount, reads } = setup();
    mount();

    expect(await screen.findByRole("heading", { level: 1, name: "Отчёты" })).toBeVisible();
    await screen.findByTestId("reports-archive");
    await waitFor(() =>
      expect(screen.getByTestId("reports-row-90")).toHaveTextContent("2 761 300 ₽"),
    );
    expect(screen.getByRole("heading", { level: 2, name: "2031" })).toBeVisible();

    const group2031 = screen.getByTestId("reports-year-2031");
    const group2030 = screen.getByTestId("reports-year-2030");
    expect(within(group2031).getByTestId("reports-row-91")).toHaveAttribute("data-current", "true");
    expect(within(group2031).getByTestId("reports-row-90")).toHaveAttribute(
      "data-current",
      "false",
    );
    expect(within(group2030).getByTestId("reports-row-87")).toBeVisible();

    const rows = Array.from(group2031.querySelectorAll("tbody tr")).map(
      (row) => row.getAttribute("data-testid") ?? `gap:${row.textContent}`,
    );
    expect(rows.slice(0, 6)).toEqual([
      "reports-row-91",
      "reports-gap-2031-6",
      "reports-row-90",
      "reports-row-89",
      "reports-gap-2031-3",
      "reports-row-88",
    ]);
    expect(within(group2030).queryByText("отчёта нет")).toBeNull();
    expect(screen.queryByTestId("reports-row-12")).toBeNull();

    const currentRow = within(group2031).getByTestId("reports-row-91");
    expect(currentRow).toHaveTextContent("Текущий отчёт");
    expect(
      within(currentRow).getByRole("link", { name: "Открыть в «Мои финансы»" }),
    ).toHaveAttribute("href", "/v2");
    const olderRow = within(group2031).getByTestId("reports-row-90");
    expect(olderRow).toHaveTextContent("Утверждён");
    expect(olderRow).toHaveTextContent("31.05.2031");
    expect(olderRow).toHaveTextContent("2 761 300 ₽");
    expect(olderRow).toHaveTextContent("3 151 300 ₽");
    expect(olderRow).toHaveTextContent("− 390 000 ₽");
    expect(within(olderRow).getByRole("link", { name: "Открыть отчёт" })).toHaveAttribute(
      "href",
      "/v2/reports/90",
    );

    const draftNote = screen.getByTestId("reports-draft-note");
    expect(draftNote).toHaveTextContent("Август 2031 ещё не закрыт");
    expect(draftNote).toHaveTextContent("черновик, не отчёт");
    expect(draftNote.querySelector("a")).toHaveAttribute("href", "/v2");

    expect(screen.getByTestId("reports-archive")).toHaveAttribute("data-money-state", "confirmed");
    expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
    // Opening the archive on the normal navigation path costs no extra network:
    // only the two already-cached read models Home/Capital use.
    expect(reads.map((read) => read.split(" ")[1])).toEqual([
      "/api/months",
      "/api/analytics/capital-composition",
    ]);
    expect(screen.getByRole("link", { name: "Месяцы в текущем интерфейсе →" })).toHaveAttribute(
      "href",
      "/months",
    );
    expect(
      screen.getByText(/Поздние цены и остатки в прошлые отчёты не подставляются/i),
    ).toBeVisible();
  });

  it("keeps gap markers non-interactive and unnumbered", async () => {
    const { mount } = setup();
    mount();

    const gap = await screen.findByTestId("reports-gap-2031-6");
    expect(gap).toHaveTextContent("Июнь 2031");
    expect(gap).toHaveTextContent("отчёта нет");
    expect(within(gap).queryByRole("link")).toBeNull();
    expect(within(gap).queryByRole("button")).toBeNull();
    expect(gap).not.toHaveTextContent("0 ₽");
    expect(screen.queryByTestId("reports-gap-2031-8")).toBeNull();
    expect(screen.queryByTestId("reports-gap-2030-12")).toBeNull();
  });

  it("notes the missing second closed report without inventing rows", async () => {
    const { mount, state } = setup();
    state.months = [uiV2Months[0], uiV2Months[1]];
    state.composition = makeUiV2CapitalHistory({ firstClosed: true });
    mount();

    expect(await screen.findByTestId("reports-single-note")).toHaveTextContent(
      "История появится после второго закрытого отчёта",
    );
    await waitFor(() =>
      expect(screen.getByTestId("reports-row-91")).toHaveTextContent("2 803 900 ₽"),
    );
    expect(screen.queryByText("отчёта нет")).toBeNull();
  });

  it("hides every money value and offers a retry when the composition read fails", async () => {
    const { mount, reads, state } = setup();
    state.compositionError = true;
    mount();

    expect(await screen.findByTestId("reports-row-90")).toBeVisible();
    expect(screen.getByTestId("reports-row-90")).not.toHaveTextContent("2 761 300 ₽");
    expect(screen.getByTestId("reports-archive")).toHaveAttribute(
      "data-money-state",
      "unavailable",
    );
    expect(screen.getByText("Денежные значения отчётов временно недоступны")).toBeVisible();
    expect(reads).toContain("GET /api/analytics/capital-composition");

    state.compositionError = false;
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Повторить" }));
    await waitFor(() =>
      expect(screen.getByTestId("reports-row-90")).toHaveTextContent("2 761 300 ₽"),
    );
  });

  it("fails the money closed when the series does not confirm the latest closed report", async () => {
    const { mount, state } = setup();
    state.composition = makeUiV2CapitalHistory({ firstClosed: true });
    mount();

    expect(await screen.findByTestId("reports-row-91")).toBeVisible();
    expect(screen.getByTestId("reports-archive")).toHaveAttribute(
      "data-money-state",
      "unavailable",
    );
    expect(screen.getByTestId("reports-row-91")).not.toHaveTextContent("2 803 900 ₽");
  });

  it("shows no rows when nothing is closed yet and never reads money", async () => {
    const { mount, reads, state } = setup();
    state.months = [uiV2Months[1]];
    mount();

    expect(await screen.findByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
    expect(screen.queryByTestId("reports-archive")).toBeNull();
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
  });

  it("recovers the archive after a months read error", async () => {
    const { mount, reads, state } = setup();
    state.monthsError = true;
    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить отчёты");
    expect(reads.some((read) => read.includes("/api/analytics/"))).toBe(false);
    state.monthsError = false;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByTestId("reports-row-90")).toBeVisible();
  });

  it("shows a genuine zero report as zero and never as a missing month", async () => {
    const { mount, state } = setup();
    state.composition = {
      asset_classes: state.composition.asset_classes,
      points: makeUiV2CapitalHistory({ zero: true }).points,
    };
    mount();

    await waitFor(() => expect(screen.getByTestId("reports-row-91")).toHaveTextContent("0 ₽"));
    expect(screen.getByTestId("reports-row-91")).not.toHaveTextContent("отчёта нет");
    expect(screen.getByTestId("reports-gap-2031-6")).toHaveTextContent("—");
  });

  it("keeps the archive as a native section without a current sidebar item", async () => {
    const { mount } = setup();
    mount();

    await screen.findByTestId("reports-archive");
    expect(screen.getByRole("link", { name: "Мои финансы" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Капитал" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute("href", "/months/91");
  });
});
