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

  it("lists months, creates a draft, opens detail, and deletes with confirm", async () => {
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
        "GET /api/months/2": () => jsonResponse(sampleMonths[0]),
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

    // closed row has no delete
    const juneRow = periodCell(/Июнь/);
    expect(within(juneRow).queryByRole("button", { name: "Удалить" })).toBeNull();

    // create August
    await user.clear(screen.getByLabelText("Год"));
    await user.type(screen.getByLabelText("Год"), "2026");
    await user.selectOptions(screen.getByLabelText("Месяц"), "8");
    await user.clear(screen.getByLabelText("Дата снимка"));
    await user.type(screen.getByLabelText("Дата снимка"), "2026-08-31");
    await user.click(screen.getByRole("button", { name: "Создать месяц" }));

    expect(await within(screen.getByRole("table")).findByText(/Август/)).toBeInTheDocument();

    // open draft july
    const julyRow = periodCell(/Июль/);
    await user.click(within(julyRow).getByRole("link", { name: "Открыть" }));
    expect(await screen.findByText("31.07.2026")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: /Июль/ })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /К списку/i }));
    expect(await screen.findByRole("heading", { level: 1, name: "Месяцы" })).toBeInTheDocument();
    expect(await screen.findByRole("table")).toBeInTheDocument();

    // delete july with confirm
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

  it("clones a month into the next period and opens the new draft", async () => {
    const user = userEvent.setup();
    const months = [...sampleMonths];

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
        "GET /api/months/9": () => {
          const found = months.find((m) => m.id === 9);
          return found
            ? jsonResponse(found)
            : jsonResponse({ error: { code: "not_found", message: "missing", details: [] } }, 404);
        },
      }),
    );

    render(<App />);
    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    expect(await screen.findByRole("table")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Создать следующий месяц" }));
    expect(screen.getByRole("dialog", { name: /Создать следующий месяц/i })).toBeInTheDocument();
    expect(screen.getByText(/Будет скопировано/i)).toBeInTheDocument();
    expect(screen.getByText(/Не копируется/i)).toBeInTheDocument();

    // defaults to August 2026 from July source
    expect(screen.getByLabelText("Целевой год")).toHaveValue(2026);
    expect(screen.getByLabelText("Целевой месяц")).toHaveValue("8");

    await user.click(screen.getByRole("button", { name: "Клонировать" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Август/ })).toBeInTheDocument();
    expect(screen.getByText("31.08.2026")).toBeInTheDocument();
  });
});
