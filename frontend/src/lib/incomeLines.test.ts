import { beforeEach, describe, expect, it, vi } from "vitest";

import { createIncome, deleteIncome, updateIncome } from "../api/incomes";
import type { IncomeEntry } from "../api/types";
import { upsertSalaryLine } from "./incomeLines";

vi.mock("../api/incomes", () => ({
  createIncome: vi.fn(),
  deleteIncome: vi.fn(),
  updateIncome: vi.fn(),
}));

const createIncomeMock = vi.mocked(createIncome);
const deleteIncomeMock = vi.mocked(deleteIncome);
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

describe("upsertSalaryLine", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createIncomeMock.mockResolvedValue(existingSalary);
    deleteIncomeMock.mockResolvedValue(undefined);
    updateIncomeMock.mockResolvedValue(existingSalary);
  });

  it("preserves stored tax when the calculated tax is temporarily unavailable", async () => {
    await upsertSalaryLine(7, {
      gross: "210000.00",
      actualNet: "180000.00",
      existing: existingSalary,
      calculatedTax: "",
    });

    expect(updateIncomeMock).toHaveBeenCalledWith(
      existingSalary.id,
      expect.objectContaining({
        gross_amount: { amount: "210000.00", currency: "RUB" },
        tax_amount: existingSalary.tax_amount,
        net_amount: { amount: "180000.00", currency: "RUB" },
      }),
    );
  });

  it("uses zero tax for a new salary row until calculation becomes available", async () => {
    await upsertSalaryLine(7, {
      gross: "210000.00",
      actualNet: "180000.00",
      calculatedTax: "",
    });

    expect(createIncomeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        tax_amount: { amount: "0.00", currency: "RUB" },
      }),
    );
  });
});
