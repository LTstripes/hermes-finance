import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppLayout } from "./AppLayout";

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<h1>Дашборд test</h1>} />
          <Route path="analytics" element={<h1>Аналитика test</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it(
    "exposes the 0.3 information architecture and keyboard-usable analytics navigation",
    async () => {
      const user = userEvent.setup();
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => ({ status: "ok", version: "0.3.0-dev" }),
        }),
      );

      renderLayout();

      const nav = screen.getByRole("navigation", { name: "Основная навигация" });
      expect(within(nav).getByRole("link", { name: /Дашборд/i })).toBeInTheDocument();
      const analytics = within(nav).getByRole("link", { name: /Аналитика/i });
      expect(within(nav).getByRole("link", { name: /Месяцы/i })).toBeInTheDocument();
      expect(
        within(nav).getByRole("link", { name: /Счета и инструменты/i }),
      ).toBeInTheDocument();
      expect(within(nav).getByRole("link", { name: /Цели/i })).toBeInTheDocument();

      analytics.focus();
      expect(analytics).toHaveFocus();
      await user.keyboard("{Enter}");
      expect(screen.getByRole("heading", { name: "Аналитика test" })).toBeInTheDocument();

      expect(screen.queryByText(/MVP · 127\.0\.0\.1/i)).toBeNull();
    },
  );

  it("shows runtime failures globally and points to Settings diagnostics", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderLayout();

    expect(await screen.findByRole("alert")).toHaveTextContent("Сервер недоступен");
    expect(screen.getByRole("link", { name: /Диагностика/i })).toHaveAttribute(
      "href",
      "/settings#diagnostics",
    );
  });
});
