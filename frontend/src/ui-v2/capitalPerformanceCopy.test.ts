import { describe, expect, it } from "vitest";

import { capabilityCopy, diagnosticCopy, hasWorkingAction } from "./capitalPerformanceCopy";

describe("diagnosticCopy", () => {
  it.each([
    ["historical_endpoint", "Историческая оценка"],
    ["historical_account_flow", "денежный поток счёта"],
    ["historical_portfolio_flow", "потока в портфеле"],
  ])("explains %s without inventing an action or target", (key, label) => {
    const copy = diagnosticCopy(key);
    expect(copy.title).toContain(label);
    expect(copy.detail).not.toContain("не умеет подробнее");
    expect(copy.detail).not.toMatch(/нажмите|автоматически|счёт \d+|\d{4}-\d{2}-\d{2}/i);
    expect(hasWorkingAction("source_required")).toBe(false);
  });
  it("maps exact keys without substring heuristics", () => {
    expect(diagnosticCopy("cash_history").title).toContain("денежной истории");
    expect(diagnosticCopy("in_kind_history").title).toContain("неденежных");
    expect(diagnosticCopy("xirr_ambiguous").title).toContain("XIRR");
    expect(diagnosticCopy("unknown_reason").title).toBe("Результат не получен");
  });

  it("falls back to a neutral message for unknown codes", () => {
    const copy = diagnosticCopy("not_computable_future_flow_problem");
    expect(copy.title).toBe("Результат не получен");
    expect(copy.detail).toContain("не умеет подробнее");
  });

  it("never invents account or date references", () => {
    for (const key of ["external_flows", "membership_history", "valuation_boundary"]) {
      const copy = diagnosticCopy(key);
      expect(copy.title).not.toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(copy.detail).not.toMatch(/счёт \d+/);
    }
  });
});

describe("capabilityCopy", () => {
  it("keeps actionable, missing-source and limitation states distinct", () => {
    expect(capabilityCopy("available")).toBe("Доступно к проверке");
    expect(capabilityCopy("requires_reopen")).toContain("reopen");
    expect(capabilityCopy("not_implemented")).toContain("не реализована");
    expect(capabilityCopy("source_required")).toContain("фактический источник");
    expect(capabilityCopy("unsupported")).toContain("Ограничение расчёта");
  });

  it("enables a working action only for available capabilities", () => {
    expect(hasWorkingAction("available")).toBe(true);
    expect(hasWorkingAction("requires_reopen")).toBe(false);
    expect(hasWorkingAction("not_implemented")).toBe(false);
    expect(hasWorkingAction("source_required")).toBe(false);
    expect(hasWorkingAction("unsupported")).toBe(false);
  });
});
