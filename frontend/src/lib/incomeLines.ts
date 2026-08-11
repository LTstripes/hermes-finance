import type { IncomeCreate, IncomeEntry, IncomeType, MoneyValue } from "../api/types";
import { createIncome, deleteIncome, updateIncome } from "../api/incomes";
import { isBlankMoney, rub } from "../lib/money";

export function findIncome(entries: IncomeEntry[], type: IncomeType): IncomeEntry | undefined {
  return entries.find((entry) => entry.income_type === type);
}

type SimpleLine = {
  type: IncomeType;
  name: string;
  amount: string;
  existing?: IncomeEntry;
};

/** Upsert a simple income line where gross = net and tax = 0 (bonus/side/cashback). */
export async function upsertSimpleIncomeLine(monthId: number, line: SimpleLine): Promise<void> {
  const existing = line.existing;
  if (isBlankMoney(line.amount)) {
    if (existing) {
      await deleteIncome(existing.id);
    }
    return;
  }
  const money = rub(line.amount);
  const zero: MoneyValue = { amount: "0.00", currency: "RUB" };
  if (existing) {
    await updateIncome(existing.id, {
      name: line.name,
      income_type: line.type,
      gross_amount: money,
      tax_amount: zero,
      net_amount: money,
      include_in_passive_income: false,
    });
    return;
  }
  const payload: IncomeCreate = {
    reporting_month_id: monthId,
    income_type: line.type,
    name: line.name,
    gross_amount: money,
    tax_amount: zero,
    net_amount: money,
    is_recurring: false,
    include_in_cash_flow: true,
    include_in_passive_income: false,
  };
  await createIncome(payload);
}

type SalaryLine = {
  gross: string;
  actualNet: string;
  existing?: IncomeEntry;
  /** Last known calculated tax from summary — stored on entry for bookkeeping only. */
  calculatedTax?: string;
};

export async function upsertSalaryLine(monthId: number, line: SalaryLine): Promise<void> {
  const existing = line.existing;
  if (isBlankMoney(line.gross) && isBlankMoney(line.actualNet)) {
    if (existing) {
      await deleteIncome(existing.id);
    }
    return;
  }
  const gross = rub(isBlankMoney(line.gross) ? "0" : line.gross);
  const net = rub(isBlankMoney(line.actualNet) ? "0" : line.actualNet);
  const tax =
    line.calculatedTax && !isBlankMoney(line.calculatedTax)
      ? rub(line.calculatedTax)
      : (existing?.tax_amount ?? { amount: "0.00", currency: "RUB" });

  if (existing) {
    await updateIncome(existing.id, {
      income_type: "salary",
      name: "Зарплата",
      gross_amount: gross,
      tax_amount: tax,
      net_amount: net,
      is_recurring: true,
      include_in_cash_flow: true,
      include_in_passive_income: false,
    });
    return;
  }
  await createIncome({
    reporting_month_id: monthId,
    income_type: "salary",
    name: "Зарплата",
    gross_amount: gross,
    tax_amount: tax,
    net_amount: net,
    is_recurring: true,
    include_in_cash_flow: true,
    include_in_passive_income: false,
  });
}
