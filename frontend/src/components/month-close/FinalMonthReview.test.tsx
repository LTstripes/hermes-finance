import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { FinalMonthReview } from "../../api/monthCloseWorkflow";
import { rub } from "../../lib/money";
import { FinalMonthReview as FinalMonthReviewView } from "./FinalMonthReview";

function review(): FinalMonthReview {
  const month = {
    id: 17,
    year: 2025,
    month: 4,
    status: "draft" as const,
    snapshot_date: "2025-04-30",
    source: "manual",
  };
  return {
    available: true,
    reason_code: null,
    month_header: month,
    kpis: {
      liquid_capital_net: rub("900000.00"),
      liquid_capital_delta: rub("10000.00"),
      passive_income_actual: rub("12000.00"),
      passive_income_delta: null,
      forecast_monthly_passive_income: rub("15000.00"),
      forecast_annual_passive_income: rub("180000.00"),
      passive_income_average: rub("11000.00"),
      passive_income_average_months: 3,
      passive_income_average_complete: false,
      goal_progress_pct: "42.0",
      goal_target: rub("25000.00"),
      mandatory_expenses: rub("70000.00"),
      mandatory_expense_coverage_pct: "20.0",
      actual_mandatory_expense_coverage_pct: "17.1",
      mortgage_balance: rub("400000.00"),
      mortgage_coverage_pct: "12.0",
    },
    assets_and_cash: {
      available: true,
      reason_code: null,
      liquid_capital: null,
      current_cash: rub("80000.00"),
      cash_row_count: 2,
    },
    debts_and_property: {
      available: true,
      reason_code: null,
      debt_total: rub("400000.00"),
      property_value: rub("1200000.00"),
      mortgage_balance: rub("400000.00"),
      debt_row_count: 1,
      property_row_count: 1,
    },
    investments: {
      available: false,
      reason_code: "no_position_snapshots",
      position_count: 0,
      market_value: rub("0.00"),
      manual_price_count: 0,
      actual_flow_count: 0,
      future_flow_count: 0,
      by_instrument_class: [],
    },
    actual_passive_income: rub("12000.00"),
    important_future_events: {
      available: true,
      reason_code: null,
      upcoming_14_days: null,
      upcoming_30_days: null,
      next_month: {
        year: 2025,
        month: 5,
        known_event_count: 1,
        has_known_events: true,
        passive_income: rub("5000.00"),
        redemption_principal: rub("20000.00"),
        total_cash_flow: rub("25000.00"),
        deposit_interest_estimate: null,
        items: [],
      },
      known_event_count: 1,
    },
    provider_summary: [],
    reconciliation_availability: { available: false, reason_code: "reconciliation_not_run" },
    freshness_summary: {
      available: true,
      evaluated_on: "2025-05-01",
      quote_valuation_target_date: "2025-04-30",
      families: [],
      reason_codes: [],
    },
    close_readiness: {
      year: 2025,
      month: 4,
      status: "draft",
      snapshot_date: "2025-04-30",
      source: "manual",
      can_close: true,
      items: [],
    },
    manual_review_cards: [
      {
        id: "cash",
        title: "Деньги сейчас",
        available: true,
        reason_code: null,
        summary: { cash_total: rub("80000.00"), row_count: 2 },
      },
      {
        id: "deposits_savings",
        title: "Вклады и накопления",
        available: true,
        reason_code: null,
        summary: {
          balance: rub("100000.00"),
          actual_interest_received: rub("1000.00"),
          savings_allocations: rub("500.00"),
          deposit_row_count: 1,
        },
      },
      {
        id: "debts_property",
        title: "Долги и недвижимость",
        available: true,
        reason_code: null,
        summary: {
          debt_total: rub("400000.00"),
          property_value: rub("1200000.00"),
          mortgage_balance: rub("400000.00"),
          property_row_count: 1,
        },
      },
      {
        id: "income_budget",
        title: "Доходы и бюджет",
        available: true,
        reason_code: null,
        summary: {
          cash_balance: rub("80000.00"),
          passive_income_actual: rub("12000.00"),
          salary_actual_net: rub("200000.00"),
          mandatory_expenses: rub("70000.00"),
        },
      },
      {
        id: "investments_outside_integrations",
        title: "Инвестиции вне интеграций",
        available: false,
        reason_code: "no_position_snapshots",
        summary: {
          market_value: rub("0.00"),
          position_count: 0,
          manual_price_count: 0,
          actual_flow_count: 0,
        },
      },
      {
        id: "note",
        title: "Заметка",
        available: false,
        reason_code: "optional_empty",
        summary: { comment_count: 0 },
      },
    ],
    manual_attention: [],
    evidence_version: "test",
  };
}

describe("FinalMonthReview", () => {
  it("renders backend KPIs, all manual cards, unavailable data and separated future cash flows", () => {
    render(
      <MemoryRouter>
        <FinalMonthReviewView review={review()} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Итоги Апрель 2025" })).toBeInTheDocument();
    expect(screen.getByText(/900\s000\s₽/)).toBeInTheDocument();
    expect(screen.getAllByTestId(/final-review-card-/)).toHaveLength(6);
    expect(screen.getByText("Инвестиции").parentElement).toHaveTextContent("Недоступно");
    expect(screen.getByText("Следующий месяц · доход").parentElement).toHaveTextContent(
      /5\s000\s₽/,
    );
    expect(screen.getByText("Следующий месяц · погашение").parentElement).toHaveTextContent(
      /20\s000\s₽/,
    );
    expect(screen.getAllByText("Не заполнено · не блокирует закрытие").length).toBeGreaterThan(0);
  });

  it("labels available sections with no rows as optional and non-blocking", () => {
    const empty = review();
    empty.manual_review_cards = empty.manual_review_cards.map((card) => {
      if (card.id === "cash") {
        return { ...card, summary: { cash_total: rub("0.00"), row_count: 0 } };
      }
      if (card.id === "deposits_savings") {
        return {
          ...card,
          summary: {
            balance: rub("0.00"),
            actual_interest_received: rub("0.00"),
            savings_allocations: rub("0.00"),
            deposit_row_count: 0,
          },
        };
      }
      if (card.id === "debts_property") {
        return {
          ...card,
          summary: {
            debt_total: rub("0.00"),
            property_value: rub("0.00"),
            mortgage_balance: rub("0.00"),
            debt_row_count: 0,
            property_row_count: 0,
          },
        };
      }
      if (card.id === "income_budget") {
        return {
          ...card,
          summary: {
            cash_balance: rub("0.00"),
            passive_income_actual: rub("0.00"),
            salary_actual_net: rub("0.00"),
            mandatory_expenses: rub("0.00"),
            income_row_count: 0,
            expense_row_count: 0,
            saving_allocation_count: 0,
          },
        };
      }
      return card;
    });

    render(
      <MemoryRouter>
        <FinalMonthReviewView review={empty} />
      </MemoryRouter>,
    );

    expect(
      screen.getAllByText("Не заполнено · не блокирует закрытие").length,
    ).toBeGreaterThanOrEqual(5);
  });

  it("links manual corrections back to the same wizard month without a close mutation", () => {
    render(
      <MemoryRouter>
        <FinalMonthReviewView review={review()} />
      </MemoryRouter>,
    );

    expect(screen.getAllByRole("link", { name: "Изменить" })[0]).toHaveAttribute(
      "href",
      "/months/17?section=assets&from=monthly-close&step=final_review_close&monthId=17",
    );
    expect(screen.queryByRole("button", { name: /Закрыть/ })).toBeNull();
  });
});
