import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import UiV2MonthlyReturnsPage from "./UiV2MonthlyReturnsPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const intake = {
  id: 1,
  head_seq: 1,
  manifest_digest: "m",
  covered_from: "2030-04-01",
  covered_to: "2030-04-30",
  state: { reporting_month_id: null },
  document: { source_accounts: ["SYNTH-01"] },
  observations: [{ id: 1 }],
  exceptions: [],
  financial_authority: "none",
};
const totals = {
  buys_cost_kopecks: 10000,
  sells_proceeds_kopecks: 0,
  price_effect_kopecks: 2500,
  coupons_kopecks: 300,
  dividends_kopecks: 200,
  assumed_income_kopecks: 0,
  confirmed_income_kopecks: 500,
  income_kopecks: 500,
  total_kopecks: 3000,
  capital_base_kopecks: 110000,
  return_percent: "2.727",
  income_assumptions_used: false,
  income_complete: true,
  flags: [],
  approximate: false,
};
const monthly = {
  source_account: "SYNTH-01",
  authority: "provisional",
  financial_authority: "none",
  currency: "RUB",
  approximate: true,
  gaps: [],
  flows: [],
  defaults_applied: [],
  segments: [],
  period: {
    contributions_kopecks: 20000,
    withdrawals_kopecks: 5000,
    growth_kopecks: 3000,
    chained_return: "0.03",
    xirr_annualized_return: "0.36",
    xirr_period_return: "0.03",
    assumptions_used: false,
    missing_endpoint: false,
    chain_reason_codes: [],
    growth_reason_codes: [],
    xirr_reason_codes: [],
    approximate: true,
  },
  months: [
    {
      opening_date: "2030-03-31",
      closing_date: "2030-04-30",
      opening_kopecks: 100000,
      closing_kopecks: 118000,
      contributions_kopecks: 20000,
      withdrawals_kopecks: 5000,
      growth_kopecks: 3000,
      modified_dietz_return: "0.027",
      assumptions_used: false,
      missing_endpoint: false,
      reason_codes: [],
      approximate: true,
      intake_ids: [1],
      flags: [],
      previous_closing_kopecks: null,
      coupons_kopecks: 300,
      dividends_kopecks: 200,
      income_assumptions_used: false,
    },
  ],
};
const instruments = {
  source_account: "SYNTH-01",
  authority: "provisional",
  financial_authority: "none",
  currency: "RUB",
  gaps: [],
  income: [],
  instruments: [
    {
      isin: "SYNTH000001",
      source_name: "Синтетическая акция",
      instrument_type: "stock",
      months: [
        {
          ...totals,
          month: "2030-04-01",
          opening_quantity: "10",
          closing_quantity: "10",
          opening_value_kopecks: 100000,
          closing_value_kopecks: 112500,
          intake_ids: [1],
        },
      ],
      all_time: {
        ...totals,
        available_months: ["2030-04-01"],
        missing_months: [],
        partial_months: [],
        partial: false,
      },
    },
  ],
};
function setup(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", fetcher);
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <UiV2MonthlyReturnsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

test("shows contributions apart from growth and instrument price and income", async () => {
  setup(
    vi.fn(async (input) => {
      const url = String(input);
      if (url.includes("/monthly?")) return json(monthly);
      if (url.includes("/instruments?")) return json(instruments);
      return json([intake]);
    }),
  );
  expect(await screen.findByRole("heading", { name: "За всё время" })).toBeVisible();
  const summary = screen.getByTestId("returns-monthly-total");
  expect(summary).toHaveTextContent("Взносы: 200,00 ₽");
  expect(summary).toHaveTextContent("Рост отдельно: 30,00 ₽");
  expect(summary).toHaveTextContent("XIRR, годовых: 36 %");
  expect(summary).toHaveTextContent("TWRR: 3 %");
  const instrument = screen.getByTestId("returns-instrument-table");
  expect(instrument).toHaveTextContent("Изменение цены");
  expect(instrument).toHaveTextContent("Купоны");
  expect(instrument).toHaveTextContent("Дивиденды");
  expect(within(instrument).getAllByText("полные данные")).toHaveLength(2);
});

test("uploads every synthetic file independently and keeps per-file flags", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/broker-months/intakes"))
      return json({ intake_id: 2, request_id: "r", head_seq: 1, duplicate: false });
    if (url.endsWith("/2"))
      return json({
        ...intake,
        id: 2,
        observations: [{ id: 1 }, { id: 2 }],
        exceptions: ["unknown_section"],
      });
    if (url.includes("source-returns/monthly")) return json(monthly);
    if (url.includes("source-returns/instruments")) return json(instruments);
    return json([intake]);
  });
  setup(fetcher);
  await screen.findByLabelText("XML-файлы");
  await userEvent.upload(screen.getByLabelText("XML-файлы"), [
    new File(["<synthetic/>"], "one.xml", { type: "text/xml" }),
    new File(["<synthetic/>"], "two.xml", { type: "text/xml" }),
  ]);
  expect((await screen.findByText(/one.xml: Сохранен/)).closest("li")).toHaveTextContent(
    "Флаги: unknown_section",
  );
  expect(screen.getByText(/two.xml: Сохранен/).closest("li")).toHaveTextContent(
    "Сохранено наблюдений: 2",
  );
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).endsWith("/api/broker-months/intakes")),
  ).toHaveLength(2);
});
