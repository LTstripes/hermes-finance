import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import { makeUiV2Freshness, makeUiV2ProviderCapabilities } from "../test/uiV2DataFixtures";
import { uiV2Months } from "../test/uiV2Fixtures";
import UiV2DataSourcesPage from "../ui-v2/UiV2DataSourcesPage";

function setup(path = "/v2/data") {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    freshness: makeUiV2Freshness(),
    capabilities: makeUiV2ProviderCapabilities(),
    monthsError: false,
    freshnessError: false,
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
        case "/api/months/12/freshness-provenance":
          data = state.freshness;
          failed = state.freshnessError;
          break;
        case "/api/months/91/freshness-provenance":
          data = makeUiV2Freshness(uiV2Months[0]);
          break;
        case "/api/market-data/providers/capabilities":
          data = state.capabilities;
          break;
        default:
          throw new Error(`Unexpected read: ${url.pathname}`);
      }
      if (failed) {
        return new Response(
          JSON.stringify({ error: { code: "x", message: "fail", details: [] } }),
          {
            status: 503,
            headers: { "Content-Type": "application/json" },
          },
        );
      }
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="v2/data" element={<UiV2DataSourcesPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { mount, reads, state };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UI v2 Data sources", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to newest DRAFT and shows freshness without inventing a score", async () => {
    const { mount, reads } = setup();
    mount();
    expect(await screen.findByRole("heading", { name: "Источники и актуальность" })).toBeTruthy();
    expect(await screen.findByTestId("data-month-context")).toHaveTextContent("Август 2031");
    expect(screen.getByTestId("data-month-context")).toHaveTextContent("Черновик");
    expect(await screen.findByTestId("freshness-family-market_quotes")).toHaveTextContent(
      "Рыночные котировки",
    );
    expect(screen.getByTestId("freshness-clocks")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(reads.some((item) => item.includes("broker-reconciliation"))).toBe(false);
    expect(reads.filter((item) => item.includes("freshness-provenance"))).toEqual([
      "GET /api/months/12/freshness-provenance",
    ]);
  });

  it("fail-closes on invalid and missing month identity", async () => {
    const invalid = setup("/v2/data?month=012");
    invalid.mount();
    expect(await screen.findByText(/Некорректный параметр месяца/)).toBeTruthy();
    expect(screen.queryByTestId("freshness-clocks")).toBeNull();
    cleanup();
    vi.unstubAllGlobals();

    const missing = setup("/v2/data?month=404");
    missing.mount();
    expect(await screen.findByText(/Месяц не найден/)).toBeTruthy();
    expect(screen.queryByTestId("freshness-clocks")).toBeNull();
  });

  it("uses explicit closed month identity when requested", async () => {
    const { mount, reads } = setup("/v2/data?month=91");
    mount();
    expect(await screen.findByTestId("data-month-context")).toHaveTextContent("Июль 2031");
    expect(await screen.findByTestId("freshness-clocks")).toBeTruthy();
    await waitFor(() => expect(reads).toContain("GET /api/months/91/freshness-provenance"));
  });

  it("hides freshness numbers when DTO identity does not match the selected month", async () => {
    const client = createQueryClient();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/months") {
          return new Response(JSON.stringify(uiV2Months), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.pathname === "/api/months/91/freshness-provenance") {
          // Wrong identity on purpose.
          return new Response(JSON.stringify(makeUiV2Freshness(uiV2Months[1])), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.pathname === "/api/market-data/providers/capabilities") {
          return new Response(JSON.stringify(makeUiV2ProviderCapabilities()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(url.pathname);
      }),
    );
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/v2/data?month=91"]}>
          <Routes>
            <Route path="v2/data" element={<UiV2DataSourcesPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("data-month-context")).toHaveTextContent("Июль 2031");
    expect(
      await screen.findByRole("heading", { name: "Ответ не соответствует выбранному месяцу" }),
    ).toBeTruthy();
    expect(screen.queryByTestId("freshness-clocks")).toBeNull();
  });

  it("keeps provider capability disclosure collapsed and read-only", async () => {
    const user = userEvent.setup();
    const { mount } = setup();
    mount();
    const disclosure = await screen.findByTestId("provider-capabilities");
    expect(disclosure).not.toHaveAttribute("open");
    await user.click(within(disclosure).getByText(/возможности источника/i));
    expect(disclosure).toHaveAttribute("open");
    expect(within(disclosure).getByText(/T-Invest/)).toBeTruthy();
  });

  it("offers labelled Monthly Close handoff for provider families", async () => {
    const { mount } = setup();
    mount();
    const family = await screen.findByTestId("freshness-family-market_quotes");
    const link = within(family).getByRole("link", { name: /Открыть шаг закрытия/ });
    expect(link).toHaveAttribute("href", "/months/12/close#market_quotes");
  });

  it("shows mode-grouped Data/App subnav with v1 escape", async () => {
    const { mount } = setup();
    mount();
    expect(await screen.findByRole("navigation", { name: /Разделы данных/ })).toBeTruthy();
    await screen.findByTestId("data-month-context");
    expect(screen.getByRole("link", { name: "Сверка портфеля" })).toHaveAttribute(
      "href",
      "/v2/data/reconciliation?month=12",
    );
    expect(screen.getByRole("link", { name: /В текущем интерфейсе/ })).toHaveAttribute(
      "href",
      "/freshness",
    );
  });
});
