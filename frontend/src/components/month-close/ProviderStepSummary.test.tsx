import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GuidedCloseStep } from "../../api/monthCloseWorkflow";
import { MonthlyCloseStepSummary } from "./ProviderStepSummary";

function actualPayoutsStep(overrides: Partial<GuidedCloseStep> = {}): GuidedCloseStep {
  return {
    id: "actual_payouts",
    order: 4,
    title: "Фактические выплаты",
    state: "completed",
    applicability: "conditional",
    gate: "owner_decision",
    affects_close: false,
    why: "Сохранены активные выплаты Alfa.",
    reason_codes: ["statement_active_rows_present"],
    primary_action: null,
    secondary_actions: [],
    completion_basis: "domain_fact",
    evidence_scope: "selected_rows_only",
    evidence_version: "test",
    evidence_summary: {
      available: true,
      selected_count: 3,
      matching_count: 2,
      stale_count: 1,
      retracted_count: 0,
    },
    stale: { is_stale: true, reason_codes: ["statement_linked_flow_changed"] },
    diagnostics: {},
    ...overrides,
  };
}

describe("MonthlyCloseStepSummary actual payouts", () => {
  it("renders persisted selected-row evidence without claiming full PDF coverage", () => {
    render(<MonthlyCloseStepSummary step={actualPayoutsStep()} />);

    expect(screen.getByText("Нужно обновить")).toBeInTheDocument();
    expect(
      screen.getByText(/Выплат сохранено: 3 · совпадают: 2 · требуют внимания: 1 · отменены: 0/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/выборочные данные PDF, не полный охват провайдера/),
    ).toBeInTheDocument();
  });

  it("keeps an unavailable statement step actionable", () => {
    render(
      <MonthlyCloseStepSummary
        step={actualPayoutsStep({
          state: "ready",
          evidence_summary: { available: false, reason_code: "statement_not_imported" },
        })}
      />,
    );

    expect(screen.getByText("Нужно действие")).toBeInTheDocument();
    expect(screen.getByText("Сохранены активные выплаты Alfa.")).toBeInTheDocument();
  });
});
