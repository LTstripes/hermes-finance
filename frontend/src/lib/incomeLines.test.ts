import { beforeEach, describe, expect, it, vi } from "vitest";

import { createIncome, deleteIncome, replaceSalaryIncome, updateIncome } from "../api/incomes";
import type { IncomeEntry } from "../api/types";
import { findIncome, upsertSalaryLine } from "./incomeLines";

vi.mock("../api/incomes", () => ({
  createIncome: vi.fn(),
  deleteIncome: vi.fn(),
  replaceSalaryIncome: vi.fn(),
  updateIncome: vi.fn(),
}));

const createIncomeMock = vi.mocked(createIncome);
const deleteIncomeMock = vi.mocked(deleteIncome);
const replaceSalaryIncomeMock = vi.mocked(replaceSalaryIncome);
const updateIncomeMock = vi.mocked(updateIncome);

const existingSalary: IncomeEntry = {
  id: 11,
  reporting_month_id: 7,
  income_type: "salary",
  name: "Зарплата",
  gross_amount: { amount: "200000.00", currency: "RUB" },
  tax_amount: { amount: "26000.00", currency: "RUB" },
  net_amount: { amount: "174000.00", currency: "RUB" },
  received_at: null,
  is_recurring: true,
  include_in_cash_flow: true,
  include_in_passive_income: false,
  notes: null,
};

const duplicateSalary: IncomeEntry = {
  ...existingSalary,
  id: 12,
  gross_amount: { amount: "50000.00", currency: "RUB" },
  tax_amount: { amount: "6500.00", currency: "RUB" },
  net_amount: { amount: "43500.00", currency: "RUB" },
};

describe("salary income helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createIncomeMock.mockResolvedValue(existingSalary);
    deleteIncomeMock.mockResolvedValue(undefined);
    replaceSalaryIncomeMock.mockResolvedValue(existingSalary);
    updateIncomeMock.mockResolvedValue(existingSalary);
  });

  it("aggregates legacy duplicate salary rows exactly for the editor", () => {
    const salary = findIncome([existingSalary, duplicateSalary], "salary");

    expect(salary).toEqual(
      expect.objectContaining({
        id: existingSalary.id,
        gross_amount: { amount: "250000.00", currency: "RUB" },
        tax_amount: { amount: "32500.00", currency: "RUB" },
        net_amount: { amount: "217500.00", currency: "RUB" },
      }),
    );
  });

  it("preserves aggregated stored tax when calculated tax is temporarily unavailable", async () => {
    const aggregate = findIncome([existingSalary, duplicateSalary], "salary");
    await upsertSalaryLine(7, {
      gross: "260000.00",
      actualNet: "225000.00",
      existing: aggregate,
      calculatedTax: "",
    });

    expect(replaceSalaryIncomeMock).toHaveBeenCalledWith(7, {
      gross_amount: { amount: "260000.00", currency: "RUB" },
      tax_amount: { amount: "32500.00", currency: "RUB" },
      net_amount: { amount: "225000.00", currency: "RUB" },
    });
    expect(updateIncomeMock).not.toHaveBeenCalled();
    expect(createIncomeMock).not.toHaveBeenCalled();
  });

  it("uses zero tax for a new salary row until calculation becomes available", async () => {
    await upsertSalaryLine(7, {
      gross: "210000.00",
      actualNet: "180000.00",
      calculatedTax: "",
    });

    expect(replaceSalaryIncomeMock).toHaveBeenCalledWith(7, {
      gross_amount: { amount: "210000.00", currency: "RUB" },
      tax_amount: { amount: "0.00", currency: "RUB" },
      net_amount: { amount: "180000.00", currency: "RUB" },
    });
  });

  it("clears all salary rows through the atomic replace endpoint", async () => {
    replaceSalaryIncomeMock.mockResolvedValue(null);

    await upsertSalaryLine(7, {
      gross: "",
      actualNet: "",
      existing: existingSalary,
      calculatedTax: "26000.00",
    });

    expect(replaceSalaryIncomeMock).toHaveBeenCalledWith(7, {
      gross_amount: { amount: "0.00", currency: "RUB" },
      tax_amount: { amount: "0.00", currency: "RUB" },
      net_amount: { amount: "0.00", currency: "RUB" },
    });
    expect(deleteIncomeMock).not.toHaveBeenCalled();
  });
});
