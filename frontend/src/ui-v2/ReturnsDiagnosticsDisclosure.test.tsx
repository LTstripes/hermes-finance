import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { contextFixture, may, overviewFixture } from "./returns/fixtures";
import UiV2ReturnsAccountPage from "./UiV2ReturnsAccountPage";

vi.mock("./ReturnsSourceDiagnostics", () => ({
  default: function SyntheticPendingForm() {
    const [edits, setEdits] = useState(0);
    return (
      <button type="button" onClick={() => setEdits(edits + 1)}>
        Синтетическая форма: {edits}
      </button>
    );
  },
}));
afterEach(() => vi.unstubAllGlobals());

test("details load on disclosure and keep pending form state after collapse", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (input: string) =>
        new Response(
          JSON.stringify(input.includes("/context") ? contextFixture : overviewFixture()),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter
        initialEntries={[
          `/v2/returns/account?scope=source:SYNTH-A&start=${may.start}&end=${may.end}`,
        ]}
      >
        <UiV2ReturnsAccountPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.queryByRole("button", { name: "Синтетическая форма: 0" })).toBeNull();
  const user = userEvent.setup();
  const summary = screen.getByText("Подробнее о данных", { exact: true });
  await user.click(summary);
  await user.click(await screen.findByRole("button", { name: "Синтетическая форма: 0" }));
  await user.click(summary);
  expect(summary.closest("details")).not.toHaveAttribute("open");
  // Role queries in JSDOM can still find descendants of a closed native details.
  expect(screen.getByRole("button", { name: "Синтетическая форма: 1" })).not.toBeVisible();
  await user.click(summary);
  expect(await screen.findByRole("button", { name: "Синтетическая форма: 1" })).toBeVisible();
});
