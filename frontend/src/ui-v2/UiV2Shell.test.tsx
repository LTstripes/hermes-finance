import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import { UiV2Shell } from "./UiV2Shell";

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>
  );
}

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/v2"]}>
      <UiV2Shell active="home" header={<h1>Мои финансы</h1>}>
        <p>Контент</p>
      </UiV2Shell>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("UiV2Shell native navigation", () => {
  it("keeps Close keyboard-operable and every shell link in v2", async () => {
    const user = userEvent.setup();
    renderShell();
    expect(screen.getByText("Основной интерфейс")).toBeVisible();
    const close = screen.getByRole("link", { name: "Закрыть месяц" });
    expect(close).toHaveAttribute("href", "/v2/close");
    close.focus();
    expect(close).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/close");
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^(\/v2(?:\/|$)|#)/);
    }
    expect(screen.queryByText(/предыдущем интерфейсе/i)).not.toBeInTheDocument();
  });

  it.each([
    ["Экспорт и копии", "/v2/data/files"],
    ["Настройки", "/v2/data/app"],
    ["Отчётные месяцы", "/v2/data/months"],
    ["Счета и справочники", "/v2/data/catalogs"],
    ["История и результаты", "/v2/capital/performance"],
    ["Доход и цели", "/v2/income/goals"],
  ])("links %s to its native workspace", (label, href) => {
    renderShell();
    expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    expect(screen.queryByRole("link", { name: /UI v1/ })).not.toBeInTheDocument();
  });
});
