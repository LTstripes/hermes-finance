import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { makeUiV2Checklist, makeUiV2Workflow } from "../test/uiV2Fixtures";
import {
  isIncompleteMonthDraft,
  MonthKpis,
  MonthOverview,
  MonthStepStrip,
  INCOMPLETE_MONTH_COPY,
} from "./UiV2MonthOverview";

const pathFor = (panel: string) => `/v2/close?month=12&panel=${panel}`;

function renderOverview(workflow: MonthCloseWorkflow) {
  return render(
    <MemoryRouter>
      <MonthOverview pathFor={pathFor} workflow={workflow} />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("Month overview (#1079 stage 2)", () => {
  it.each(["overview", "close"] as const)(
    "hides incomplete draft comparisons in %s KPIs",
    (variant) => {
      const workflow = makeUiV2Workflow();
      workflow.checklist = makeUiV2Checklist();
      const brokers = workflow.checklist.steps.find((step) => step.id === "brokers");
      if (!brokers || !workflow.final_review.available) throw new Error("Fixture missing");
      brokers.state = "empty";
      workflow.final_review.kpis.liquid_capital_delta = { amount: "-123.00", currency: "RUB" };
      workflow.final_review.kpis.passive_income_delta = { amount: "-45.00", currency: "RUB" };
      const view = render(<MonthKpis workflow={workflow} variant={variant} />);
      expect(view.container).toHaveTextContent("неполный · без брокерских счетов");
      expect(view.container).not.toHaveTextContent(/за месяц|к прошлому месяцу|%/);
      for (const label of ["Пассивный доход", "Покрытие расходов"]) {
        const tile = screen.getByText(label).closest("div") as HTMLElement;
        expect(within(tile).getByText("—")).toBeVisible();
        expect(tile).toHaveTextContent("после загрузки выписок");
      }
      brokers.state = "done";
      view.rerender(<MonthKpis workflow={workflow} variant={variant} />);
      expect(view.container).not.toHaveTextContent("неполный · без брокерских счетов");
      expect(view.container).toHaveTextContent("к прошлому месяцу");
    },
  );

  it("uses only the explicit empty broker step in an open month", () => {
    const workflow = makeUiV2Workflow();
    expect(isIncompleteMonthDraft(workflow)).toBe(false);
    workflow.checklist = makeUiV2Checklist();
    const brokers = workflow.checklist.steps.find((step) => step.id === "brokers");
    if (!brokers) throw new Error("Fixture missing");
    for (const state of ["done", "attention", "optional"] as const) {
      brokers.state = state;
      expect(isIncompleteMonthDraft(workflow)).toBe(false);
    }
    brokers.state = "empty";
    expect(isIncompleteMonthDraft(workflow)).toBe(true);
    workflow.month.status = "closed";
    expect(isIncompleteMonthDraft(workflow)).toBe(false);
  });

  it("keeps Close available, with progress and three checklist-ordered next steps without expenses", () => {
    const workflow = makeUiV2Workflow();
    workflow.checklist = makeUiV2Checklist();
    const brokers = workflow.checklist.steps.find((step) => step.id === "brokers");
    if (!brokers) throw new Error("Fixture missing");
    brokers.state = "empty";
    workflow.checklist.expenses.mandatory_items = [];
    renderOverview(workflow);
    expect(screen.getByText(INCOMPLETE_MONTH_COPY)).toBeVisible();
    const remaining = screen.getByRole("navigation", { name: "Что осталось" });
    expect(
      within(remaining)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual([pathFor("income"), pathFor("budget"), pathFor("brokers")]);
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "value",
      String(workflow.checklist.completed_count),
    );
    expect(screen.getByRole("link", { name: "Закрыть месяц" })).toHaveAttribute(
      "href",
      pathFor("close"),
    );
  });
  it("shows closed warnings once using the final review's existing findings", () => {
    const workflow = makeUiV2Workflow({ monthId: 91 });
    workflow.checklist = makeUiV2Checklist({ closed: true, attention: true });
    renderOverview(workflow);
    expect(screen.getAllByText("Закрыт с замечаниями: 2")).toHaveLength(1);
    expect(screen.queryByText(/из 10/)).toBeNull();
    expect(screen.queryByText(/есть замечания|замечание требует решения/)).toBeNull();
    expect(screen.getByRole("link", { name: "Итоги и замечания" })).toHaveAttribute(
      "href",
      pathFor("close"),
    );
  });

  it("rounds overview money and retains exact kopecks in titles", () => {
    const workflow = makeUiV2Workflow();
    if (!workflow.final_review.available) throw new Error("Review missing");
    workflow.final_review.kpis.liquid_capital_net = { amount: "1234.50", currency: "RUB" };
    workflow.final_review.kpis.portfolio_source_coverage = {
      status: "complete",
      reason_codes: [],
      missing_account_ids: [],
    };
    renderOverview(workflow);
    const figure = screen.getByTitle("1 234,50 ₽");
    expect(figure).toHaveTextContent("1 235 ₽");
  });
  it("leads with the month result and lists sections with state and key figure", () => {
    const workflow = makeUiV2Workflow();
    workflow.checklist = makeUiV2Checklist({ attention: true });
    renderOverview(workflow);

    const result = document.querySelector<HTMLElement>('dl[aria-label="Итог месяца"]');
    if (!result) throw new Error("Month result is missing");
    expect(within(result).getByText("Ликвидный капитал")).toBeVisible();
    expect(within(result).getByText("Покрытие расходов")).toBeVisible();

    const nav = screen.getByRole("navigation", { name: "Разделы месяца" });
    expect(within(nav).getAllByRole("link")).toHaveLength(10);
    expect(within(nav).getByRole("heading", { level: 2 })).toHaveTextContent("Что требует решения");
    expect(within(nav).getByText("5 из 10")).toBeVisible();

    const brokers = within(nav).getByRole("link", { name: /Брокерские выписки/ });
    expect(brokers).toHaveAccessibleName(/требует решения/);
    expect(brokers).toHaveTextContent("1 замечание требует решения");
    expect(brokers).toHaveTextContent("2 выписки");

    const income = within(nav).getByRole("link", { name: /Зарплата и другие доходы/ });
    expect(income).toHaveTextContent("Не заполнено");
    // An empty section shows a dash, never a zero fact.
    expect(income).toHaveTextContent("—");
    expect(within(nav).getByRole("link", { name: /Комментарии/ })).toHaveTextContent(
      "Необязательно",
    );
    expect(within(nav).getByRole("link", { name: /Выплаты/ })).toHaveTextContent(
      "Ожидается ещё 4 выплаты",
    );

    expect(within(nav).getByText("Готово 5 из 10")).toBeVisible();
    expect(within(nav).getByRole("link", { name: "Закрыть месяц" })).toHaveAttribute(
      "href",
      pathFor("close"),
    );
  });

  it("shows missing capital snapshots as unknown rather than a zero sum", () => {
    const workflow = makeUiV2Workflow();
    if (!workflow.final_review.available) throw new Error("Synthetic review is missing");
    workflow.final_review.kpis = {
      ...workflow.final_review.kpis,
      liquid_capital_net: { amount: "0.00", currency: "RUB" },
      liquid_capital_delta: { amount: "-1000.00", currency: "RUB" },
      portfolio_source_coverage: {
        status: "unavailable",
        reason_codes: ["no_capital_snapshots"],
        missing_account_ids: [],
      },
    };
    renderOverview(workflow);
    const result = document.querySelector<HTMLElement>('dl[aria-label="Итог месяца"]');
    if (!result) throw new Error("Month result is missing");
    const capital = within(result).getByText("Ликвидный капитал").closest("div") as HTMLElement;
    expect(capital).toHaveTextContent("—");
    expect(capital).not.toHaveTextContent("0 ₽");
    expect(capital).not.toHaveTextContent("за месяц");
    expect(within(capital).getByTestId("portfolio-coverage-note")).toHaveTextContent(
      "Нет снимков капитала",
    );
  });

  it("shows mandatory expenses without any rows as not entered", () => {
    const workflow = makeUiV2Workflow();
    const checklist = makeUiV2Checklist();
    checklist.expenses = { ...checklist.expenses, mandatory_items: [] };
    workflow.checklist = checklist;
    renderOverview(workflow);
    const result = document.querySelector<HTMLElement>('dl[aria-label="Итог месяца"]');
    if (!result) throw new Error("Month result is missing");
    const expenses = within(result).getByText("Обязательные расходы").closest("div") as HTMLElement;
    expect(expenses).toHaveTextContent("—");
    expect(expenses).toHaveTextContent("не заполнено");
  });

  it("keeps the mandatory list equal to its total and shows other expenses once", () => {
    const workflow = makeUiV2Workflow();
    workflow.checklist = makeUiV2Checklist();
    renderOverview(workflow);
    const expenses = screen.getByRole("region", { name: "Обязательные расходы" });
    expect(within(expenses).getAllByRole("listitem")).toHaveLength(4);
    expect(within(expenses).getByText("Итого").parentElement).toHaveTextContent("61 200 ₽");
    expect(expenses).toHaveTextContent("Прочие расходы 4 300 ₽ в покрытие не входят.");
  });

  it("marks a closed month read-only and offers its review instead of Close", () => {
    const workflow = makeUiV2Workflow({ monthId: 91 });
    workflow.checklist = makeUiV2Checklist({ closed: true });
    renderOverview(workflow);
    const nav = screen.getByRole("navigation", { name: "Разделы месяца" });
    expect(within(nav).queryByRole("heading", { level: 2 })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Закрыть месяц" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Итоги и замечания" })).toBeVisible();
    expect(screen.queryByText(/Прочие расходы/)).toBeNull();
  });

  it("still lists every section when an older backend sends no checklist", () => {
    const workflow = makeUiV2Workflow();
    delete workflow.checklist;
    renderOverview(workflow);
    const nav = screen.getByRole("navigation", { name: "Разделы месяца" });
    expect(within(nav).getAllByRole("link")).toHaveLength(10);
    expect(screen.queryByRole("region", { name: "Обязательные расходы" })).toBeNull();
  });

  it("marks the open section in the compact strip", () => {
    render(
      <MemoryRouter>
        <MonthStepStrip checklist={makeUiV2Checklist()} current="budget" pathFor={pathFor} />
      </MemoryRouter>,
    );
    const strip = screen.getByRole("navigation", { name: "Разделы месяца" });
    expect(within(strip).getByRole("link", { name: /Расходы и план/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("uses completed marks without duplicated warnings for closed attention steps on overview and strip", () => {
    const workflow = makeUiV2Workflow({ monthId: 91 });
    workflow.checklist = makeUiV2Checklist({ attention: true });
    render(
      <MemoryRouter>
        <MonthOverview workflow={workflow} pathFor={pathFor} />
        <MonthStepStrip checklist={workflow.checklist} closed current="close" pathFor={pathFor} />
      </MemoryRouter>,
    );
    const brokers = screen.getAllByRole("link", { name: /Брокерские выписки/ });
    expect(brokers).toHaveLength(2);
    for (const link of brokers) {
      expect(link).not.toHaveAccessibleName(/есть замечания/);
      expect(link).toHaveAttribute("data-state", "noted");
      expect(link).not.toHaveTextContent("1 замечание");
      expect(link).not.toHaveTextContent(/!|требует решения|требуют решения/);
      expect(link.querySelector('[aria-hidden="true"]')).toHaveTextContent("✓");
    }
  });

  it("shows only supplied deltas and preserves unknown and explicit zero in close tiles", () => {
    const workflow = makeUiV2Workflow();
    if (!workflow.final_review.available) throw new Error("Review missing");
    workflow.checklist = makeUiV2Checklist();
    workflow.final_review.kpis.liquid_capital_delta = null;
    workflow.final_review.kpis.passive_income_delta = { amount: "0.00", currency: "RUB" };
    workflow.final_review.investments.market_value = null;
    workflow.final_review.kpis.mandatory_expenses = { amount: "0.00", currency: "RUB" };
    const view = render(<MonthKpis workflow={workflow} variant="close" />);
    const kpis = screen.getByLabelText("Итоги месяца");
    expect(kpis).not.toHaveTextContent("за месяц");
    expect(kpis).toHaveTextContent("0 ₽ к прошлому месяцу");
    expect(within(kpis).getByText("Инвестиции").parentElement).toHaveTextContent("Недоступно");
    expect(within(kpis).getByText("Обязательные расходы").parentElement).toHaveTextContent("0 ₽");
    workflow.checklist.expenses.mandatory_items = [];
    view.rerender(<MonthKpis workflow={workflow} variant="close" />);
    expect(within(kpis).queryByText("Обязательные расходы")).toBeNull();
  });
});
