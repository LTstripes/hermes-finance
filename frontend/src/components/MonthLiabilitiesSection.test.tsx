import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getDashboard } from "../api/dashboard";
import { listDebts } from "../api/debts";
import { listProperties } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import { MonthLiabilitiesSection } from "./MonthLiabilitiesSection";

vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/debts", () => ({ createDebt: vi.fn(), deleteDebt: vi.fn(), listDebts: vi.fn() }));
vi.mock("../api/properties", () => ({
  createProperty: vi.fn(),
  deleteProperty: vi.fn(),
  listProperties: vi.fn(),
}));
vi.mock("../api/summary", () => ({ getMonthSummary: vi.fn() }));

const debt = {
  id: 1,
  reporting_month_id: 7,
  debt_type: "credit_card",
  name: "Основная карта",
  current_balance: { amount: "123456.00", currency: "RUB" },
  include_in_liquid_capital: true,
  notes: null,
};

const property = {
  id: 2,
  reporting_month_id: 7,
  name: "Синтетическая квартира",
  estimated_value: { amount: "7000000.00", currency: "RUB" },
  mortgage_balance: { amount: "3000000.00", currency: "RUB" },
  monthly_payment: { amount: "50000.00", currency: "RUB" },
  notes: null,
};

describe("MonthLiabilitiesSection R03-14 presentation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listDebts).mockResolvedValue([debt]);
    vi.mocked(listProperties).mockResolvedValue([property]);
    vi.mocked(getDashboard).mockResolvedValue({ mortgage: null } as never);
    vi.mocked(getMonthSummary).mockResolvedValue({ coverage: { coverage_pct: null } } as never);
  });

  it("uses grouped amounts, compact inclusion state, and overflow delete actions", async () => {
    const user = userEvent.setup();
    render(<MonthLiabilitiesSection monthId={7} readOnly={false} />);

    const [debtTable] = await screen.findAllByRole("table");
    expect(debtTable).toHaveTextContent(/123\s*456\s*₽/);
    expect(debtTable).toHaveTextContent("В капитале");
    expect(debtTable).not.toHaveTextContent("В ликвидном капитале");

    await user.click(
      within(debtTable).getByRole("button", { name: "Действия для долга «Основная карта»" }),
    );
    expect(within(debtTable).getByRole("menuitem", { name: "Удалить" })).toBeInTheDocument();
  });
});
