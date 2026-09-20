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

function renderShell(v1ReturnPath: string) {
  return render(
    <MemoryRouter initialEntries={["/v2"]}>
      <UiV2Shell active="home" header={<h1>Мои финансы</h1>} v1ReturnPath={v1ReturnPath}>
        <p>Контент</p>
      </UiV2Shell>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("UiV2Shell rollback", () => {
  it("keeps a visible, keyboard-operable contextual UI v1 return", async () => {
    const user = userEvent.setup();
    renderShell("/months/12/close#actual_payouts");

    const rollback = screen.getByRole("link", { name: /UI v1/ });
    expect(rollback).toHaveAttribute("href", "/months/12/close#actual_payouts");
    rollback.focus();
    expect(rollback).toHaveFocus();

    await user.keyboard("{Enter}");

    expect(screen.getByTestId("location")).toHaveTextContent("/months/12/close#actual_payouts");
  });

  it("uses the durable v1 home when the caller has no contextual return", () => {
    renderShell("/v1");

    expect(screen.getByRole("link", { name: /UI v1/ })).toHaveAttribute("href", "/v1");
  });
});
