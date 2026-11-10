import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";
import { UiV2Tabs } from "./UiV2Tabs";

afterEach(cleanup);

it("marks the active link and preserves month, destination query and hash", () => {
  render(
    <MemoryRouter initialEntries={["/v2/capital?month=12&unrelated=1"]}>
      <UiV2Tabs
        label="Раздел капитала"
        tabs={[
          { label: "Обзор", to: "/v2/capital", active: true },
          { label: "Распределение", to: "/v2/capital/allocation?view=class#table", active: false },
        ]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole("navigation", { name: "Раздел капитала" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "Распределение" })).toHaveAttribute(
    "href",
    "/v2/capital/allocation?view=class&month=12#table",
  );
  expect(screen.getByRole("link", { name: "Распределение" })).not.toHaveAttribute("aria-current");
});

it("leaves a month-free destination month-free", () => {
  render(
    <MemoryRouter>
      <UiV2Tabs label="Раздел" tabs={[{ label: "Обзор", to: "/v2/capital", active: true }]} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("link")).toHaveAttribute("href", "/v2/capital");
});
