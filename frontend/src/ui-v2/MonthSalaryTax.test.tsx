import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IncomeEntry, MonthSummary } from "../api/types";
import { salaryFixture } from "../test/monthSalaryTaxFixtures";
import { makeUiV2Checklist, makeUiV2Workflow } from "../test/uiV2Fixtures";
import { MonthSalaryTax } from "./MonthSalaryTax";
import { MonthOverview } from "./UiV2MonthOverview";

const money = (amount: string) => ({ amount, currency: "RUB" });

function setup({ overview = false, report = false } = {}) {
  const monthId = 91;
  const state = { ...salaryFixture(monthId), failed: false, incomes: [] as IncomeEntry[] };
  state.incomes = [state.salary];
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      expect(init?.method).toBe("GET");
      requests.push(`${url.pathname}${url.search}`);
      if (url.pathname === "/api/incomes") {
        expect(url.searchParams.get("month_id")).toBe(String(monthId));
        return new Response(JSON.stringify(state.incomes));
      }
      expect(url.pathname).toBe(`/api/months/${monthId}/summary`);
      expect(url.searchParams.get("include_capital_change")).toBe("false");
      return new Response(
        JSON.stringify(
          state.failed
            ? { error: { code: "unavailable", message: "Unavailable", details: [] } }
            : state.summary,
        ),
        { status: state.failed ? 503 : 200 },
      );
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const workflow = makeUiV2Workflow({ monthId });
  workflow.checklist = makeUiV2Checklist({ closed: true });
  const mount = () =>
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          {overview ? (
            <MonthOverview
              workflow={workflow}
              pathFor={(panel) => `/v2/close?month=${monthId}&panel=${panel}`}
            />
          ) : (
            <MonthSalaryTax monthId={monthId} report={report} />
          )}
        </MemoryRouter>
      </QueryClientProvider>,
    );
  return { state, client, mount, requests };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("read-only month salary tax", () => {
  it.each([false, true])(
    "shows API tax and rates in overview/report=%s without using saved withholding",
    async (report) => {
      const { mount } = setup({ overview: !report, report });
      mount();
      const block = await screen.findByRole("region", { name: "Налог на зарплату" });
      expect(block).toHaveTextContent("До налога 100 000 ₽");
      expect(block).toHaveTextContent("Налог (13% + 15%) 14 000,01 ₽");
      expect(block).toHaveTextContent("На руки 85 999,99 ₽");
      expect(block).not.toHaveTextContent("Выплата отличается");
      expect(block).not.toHaveTextContent("Эффективная");
      if (!report)
        expect(block.closest("li")).toContainElement(
          screen.getByRole("link", { name: /Зарплата и другие доходы/ }),
        );
    },
  );

  it("explains a difference above 1 000 ₽ once without showing a derived delta", async () => {
    const { mount, state } = setup();
    state.summary.salary_actual_net = money("87500.00");
    mount();
    const block = await screen.findByRole("region", { name: "Налог на зарплату" });
    expect(within(block).getAllByText(/Выплата отличается/)).toHaveLength(1);
    expect(block).toHaveTextContent("Фактически на руки 87 500 ₽, по расчёту — 85 999,99 ₽.");
  });

  it.each(["86000.00", "86999.99", "84999.99"])(
    "keeps a difference up to 1 000 ₽ quiet (actual %s)",
    async (amount) => {
      const { mount, state } = setup();
      state.summary.salary_actual_net = money(amount);
      mount();
      const block = await screen.findByRole("region", { name: "Налог на зарплату" });
      expect(block).not.toHaveTextContent("Выплата отличается");
    },
  );

  it("explains a shortfall above 1 000 ₽", async () => {
    const { mount, state } = setup();
    state.summary.salary_actual_net = money("84999.98");
    mount();
    const block = await screen.findByRole("region", { name: "Налог на зарплату" });
    expect(within(block).getAllByText(/Выплата отличается/)).toHaveLength(1);
  });

  it.each(["", "UNKNOWN", null])(
    "hides unavailable tax %s without a zero placeholder",
    async (amount) => {
      const { mount, state, client } = setup();
      state.summary.salary_tax.tax = { amount, currency: "RUB" } as unknown as MoneyValueForTest;
      const view = mount();
      await waitFor(() => expect(client.isFetching()).toBe(0));
      expect(view.container).toBeEmptyDOMElement();
    },
  );

  it("retains known zero tax and compares net by exact kopecks", async () => {
    const { mount, state } = setup();
    state.summary.salary_tax = { tax: money("0.00"), calculated_net: money("100000.0"), parts: [] };
    state.summary.salary_actual_net = money("100000.00");
    mount();
    const block = await screen.findByRole("region", { name: "Налог на зарплату" });
    expect(block).toHaveTextContent("Налог 0 ₽");
    expect(block).not.toHaveTextContent("Выплата отличается");
  });

  it("does not create a salary block for an empty month", async () => {
    const { mount, state, client } = setup();
    state.incomes = [];
    const view = mount();
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(view.container).toBeEmptyDOMElement();
  });

  it.each(["wrong-month", "copied-salary"])("hides %s facts", async (kind) => {
    const { mount, state, client } = setup();
    if (kind === "wrong-month") state.summary.month.id = 92;
    else state.salary.actual_fact_origin = "clone_template_v1";
    const view = mount();
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(view.container).toBeEmptyDOMElement();
  });

  it("does not turn an unavailable actual net into zero or a mismatch", async () => {
    const { mount, state } = setup();
    state.summary.salary_actual_net = money("");
    mount();
    const block = await screen.findByRole("region", { name: "Налог на зарплату" });
    expect(block).not.toHaveTextContent("На руки");
    expect(block).not.toHaveTextContent("Выплата отличается");
    expect(block).toHaveTextContent("14 000,01 ₽");
  });

  it("does not aggregate gross from legacy salary rows", async () => {
    const { mount, state } = setup();
    state.incomes.push({ ...state.salary, id: 2 });
    mount();
    const block = await screen.findByRole("region", { name: "Налог на зарплату" });
    expect(block).not.toHaveTextContent("До налога");
    expect(block).toHaveTextContent("Налог (13% + 15%) 14 000,01 ₽");
  });

  it("hides stale values after a failed summary refetch", async () => {
    const { mount, state, client } = setup();
    mount();
    await screen.findByRole("region", { name: "Налог на зарплату" });
    state.failed = true;
    await client.invalidateQueries({ queryKey: ["month-income-summary", 91] });
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Налог на зарплату" })).toBeNull(),
    );
  });
});

type MoneyValueForTest = MonthSummary["salary_tax"]["tax"];
