import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";

import { createQueryClient } from "../queryClient";
import { totalIncomeFixture } from "../test/totalIncomeFixture";
import { TotalIncomeHomeRow, TotalIncomeSection, TotalIncomeWidget } from "./TotalIncome";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows API headlines, partial coverage, estimates once and no bonus, without filling missing months", () => {
  const data = totalIncomeFixture();
  render(<TotalIncomeSection data={data} />);
  expect(screen.getByText("120 000 ₽")).toBeVisible();
  expect(screen.getAllByText("460 000 ₽")).toHaveLength(2);
  expect(screen.getAllByText("за 4 из 12 мес")).toHaveLength(3);
  expect(screen.getByTestId("total-income-warnings")).toHaveTextContent(
    "Зарплата за 1 мес оценена по апрельской (04.2031). Пассивка учитывается с 04.2031",
  );
  expect(screen.getByTestId("total-income-month-88")).toHaveAttribute("data-estimate", "true");
  expect(screen.getAllByTestId(/^total-income-month-/)).toHaveLength(4);
  expect(screen.queryByTestId("total-income-bonus-legend")).toBeNull();
  expect(screen.getByText("Сейчас ≈ 125 000 ₽ в месяц")).toBeVisible();
  expect(screen.getByTestId("total-income-average-line")).toBeInTheDocument();
});

it("switches the average, bonus and months using the selected window; year and rolling totals stay fixed", () => {
  const data = totalIncomeFixture();
  data.windows.rolling_12.monthly_average = { amount: "70000.15", currency: "RUB" };
  data.windows.rolling_12.bonus_smoothed_monthly = { amount: "2000.00", currency: "RUB" };
  data.windows.rolling_12.months_used = ["2031-07"];
  data.windows.rolling_12.warnings = ["Один пробел", "Один пробел"];
  render(<TotalIncomeSection data={data} />);
  fireEvent.click(
    within(screen.getByRole("group", { name: "Период общего дохода" })).getByRole("button", {
      name: "12 мес",
    }),
  );
  expect(screen.getByText("70 000 ₽").getAttribute("title")?.replaceAll(" ", " ")).toBe(
    "70 000,15 ₽",
  );
  expect(screen.getAllByText("460 000 ₽")).toHaveLength(2);
  expect(screen.getByTestId("total-income-bonus-legend")).toBeVisible();
  expect(screen.getAllByTestId(/^total-income-month-/)).toHaveLength(1);
  expect(screen.getByTestId("total-income-warnings")).toHaveTextContent(/^Один пробел$/);
});

it("does not label complete coverage partial or turn unknown money into zero", () => {
  const data = totalIncomeFixture();
  for (const window of Object.values(data.windows)) {
    window.months_observed = 12;
    window.warnings = [];
  }
  data.windows.calendar_year.monthly_average = null;
  data.windows.calendar_year.current_level = null;
  render(<TotalIncomeSection data={data} />);
  expect(screen.queryByText(/из 12 мес/)).toBeNull();
  expect(screen.getByText("Недоступно")).toBeVisible();
  expect(screen.queryByTestId("total-income-average-line")).toBeNull();
  expect(screen.queryByTestId("total-income-warnings")).toBeNull();
  expect(screen.queryByText(/Сейчас ≈/)).toBeNull();
});

it("uses only calendar year API share and average on home; hides unknown share, preserves zero", () => {
  const data = totalIncomeFixture();
  data.windows.rolling_12.passive_share_pct = "99.9";
  const view = render(
    <MemoryRouter>
      <TotalIncomeHomeRow data={data} />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("total-income-home")).toHaveTextContent(
    "пассивка закрывает 16,7% дохода",
  );
  expect(screen.getByRole("link", { name: "Весь доход →" })).toHaveAttribute("href", "/v2/income");
  data.windows.calendar_year.passive_share_pct = "0.0";
  view.rerender(
    <MemoryRouter>
      <TotalIncomeHomeRow data={data} />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("total-income-home")).toHaveTextContent(
    "пассивка закрывает 0,0% дохода",
  );
  data.windows.calendar_year.passive_share_pct = null;
  view.rerender(
    <MemoryRouter>
      <TotalIncomeHomeRow data={data} />
    </MemoryRouter>,
  );
  expect(screen.queryByText(/пассивка закрывает/)).toBeNull();
});

it("shows only retry on network failure, rejects stale identity and recovers", async () => {
  let failed = true;
  const data = totalIncomeFixture();
  data.latest_closed_report_id = 90;
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify(failed ? { error: { code: "unavailable", message: "Synthetic" } } : data),
        { status: failed ? 503 : 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TotalIncomeWidget monthId={91} />
    </QueryClientProvider>,
  );
  await screen.findByRole("alert");
  expect(screen.queryByTestId("total-income-section")).toBeNull();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  await screen.findByRole("alert");
  expect(screen.queryByTestId("total-income-section")).toBeNull();
  data.latest_closed_report_id = 91;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByTestId("total-income-section")).toBeVisible();
  expect(String(fetcher.mock.calls[0])).not.toContain("8000");
});

it("keeps the home row silent while loading, offers retry only after a failure", async () => {
  let failed = true;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetcher = vi.fn(async () => {
    await gate;
    return new Response(
      JSON.stringify(
        failed ? { error: { code: "unavailable", message: "Synthetic" } } : totalIncomeFixture(91),
      ),
      { status: failed ? 503 : 200 },
    );
  });
  vi.stubGlobal("fetch", fetcher);
  const { container } = render(
    <MemoryRouter>
      <QueryClientProvider client={createQueryClient()}>
        <TotalIncomeWidget compact monthId={91} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  expect(container).toBeEmptyDOMElement();
  release();
  await screen.findByRole("alert");
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByTestId("total-income-home")).toBeVisible();
});
