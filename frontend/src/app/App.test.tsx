import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

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

  it("navigates to placeholder sections from the sidebar", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );

    render(<App />);

    await user.click(screen.getByRole("link", { name: /Месяцы/i }));
    expect(screen.getByRole("heading", { level: 1, name: "Месяцы" })).toBeInTheDocument();
    expect(screen.getByText("E02", { selector: ".pending-badge" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Цели/i }));
    expect(screen.getByRole("heading", { level: 1, name: "Цели" })).toBeInTheDocument();
    expect(screen.getByText("API /api/goals отсутствует")).toBeInTheDocument();
  });
});
