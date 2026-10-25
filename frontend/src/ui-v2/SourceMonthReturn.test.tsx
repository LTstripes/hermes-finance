import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { formatSourceReturnRate as sourceReturnRate } from "../lib/sourceReturnFormat";
import { SourceMonthReturn, sourceReturnMoney } from "./SourceMonthReturn";

afterEach(() => vi.unstubAllGlobals());

function renderReturn(months: unknown[], patch = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            source_account: "SYN-OCT",
            authority: "provisional",
            financial_authority: "none",
            months,
            ...patch,
          }),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <SourceMonthReturn account="SYN-OCT" period="2030-10" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const monthly = {
  opening_date: "2030-09-30",
  closing_date: "2030-10-31",
  growth_kopecks: 0,
  modified_dietz_return: "0",
  reason_codes: [],
  missing_endpoint: false,
};

it.each([
  { months: [] },
  { months: [{ ...monthly, closing_date: "2030-10-20", growth_kopecks: 123456 }] },
  { months: [{ ...monthly, opening_date: "2030-08-31", growth_kopecks: 123456 }] },
])(
  "requires exact October EOD boundaries rather than displaying a historical or partial result (%j)",
  async ({ months }) => {
    renderReturn(months);
    expect(await screen.findByText(/нет доказанных границ этого месяца/)).toHaveTextContent(
      "2030-09-30 и 2030-10-31",
    );
    expect(screen.queryByText(/1\s234,56/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0,00%/)).not.toBeInTheDocument();
  },
);

it("keeps a supported zero separate from NULL and states the missing evidence", async () => {
  renderReturn([
    {
      ...monthly,
      modified_dietz_return: null,
      missing_endpoint: true,
      reason_codes: ["missing_endpoint", "unrecognized_money"],
    },
  ]);
  expect(await screen.findByText(/0.*₽.*Доходность недоступна/)).toBeVisible();
  expect(screen.getByText(/Нужны подтверждённые EOD/)).toHaveTextContent("2030-10-31");
  fireEvent.click(screen.getByText("Подробнее о предварительном расчёте"));
  expect(screen.getByText("Есть нераспознанная денежная операция.")).toBeVisible();
});

it("does not display a response for another account", async () => {
  renderReturn([monthly], { source_account: "SYN-OTHER" });
  expect(await screen.findByRole("status")).toHaveTextContent("не подтверждены");
  expect(screen.queryByText(/0,00%/)).not.toBeInTheDocument();
});

it("keeps exact kopecks at MAX_SAFE_INTEGER and refuses an already imprecise JSON integer", () => {
  expect(sourceReturnMoney(Number.MAX_SAFE_INTEGER)).toBe(
    "90\u00a0071\u00a0992\u00a0547\u00a0409,91\u00a0₽",
  );
  expect(sourceReturnMoney(-Number.MAX_SAFE_INTEGER)).toBe(
    "−90\u00a0071\u00a0992\u00a0547\u00a0409,91\u00a0₽",
  );
  expect(sourceReturnMoney(Number.MAX_SAFE_INTEGER + 1)).toContain("вне точного диапазона");
  expect(sourceReturnMoney(null)).toBe("—");
});

it("converts the Decimal fraction to percentage text without binary financial arithmetic", () => {
  expect(sourceReturnRate("0.002309773164046106")).toBe("0,23%");
  expect(sourceReturnRate("-0.007720534510707254")).toBe("−0,77%");
  expect(sourceReturnRate("0E-60")).toBe("0,00%");
  expect(sourceReturnRate(null)).toBe("—");
});
