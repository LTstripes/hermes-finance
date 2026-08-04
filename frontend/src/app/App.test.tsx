import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the dashboard in the application layout", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    render(<App />);

    expect(screen.getByText("Hermes Finance")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Дашборд" }),
    ).toBeInTheDocument();
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    render(<App />);

    expect(await screen.findByText("Backend недоступен")).toBeInTheDocument();
  });
});
