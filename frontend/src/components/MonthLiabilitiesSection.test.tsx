import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getDashboard } from "../api/dashboard";
import { listDebts, updateDebt } from "../api/debts";
import { listProperties, updateProperty } from "../api/properties";
import { getMonthSummary } from "../api/summary";
import { MonthLiabilitiesSection } from "./MonthLiabilitiesSection";

vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/debts", () => ({
  createDebt: vi.fn(),
  deleteDebt: vi.fn(),
  listDebts: vi.fn(),
  updateDebt: vi.fn(),
}));
vi.mock("../api/properties", () => ({
  createProperty: vi.fn(),
  deleteProperty: vi.fn(),
  listProperties: vi.fn(),
  updateProperty: vi.fn(),
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
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toHaveClass(
      "overflow-menu__item--danger",
    );
  });

  it("loads current debt values and patches on save", async () => {
    vi.mocked(updateDebt).mockResolvedValue({
      ...debt,
      current_balance: { amount: "100000.00", currency: "RUB" },
    });
    const user = userEvent.setup();
    render(<MonthLiabilitiesSection monthId={7} readOnly={false} />);
    const [debtTable] = await screen.findAllByRole("table");
    await user.click(
      within(debtTable).getByRole("button", { name: "Действия для долга «Основная карта»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    expect(screen.getByDisplayValue("Основная карта")).toBeInTheDocument();
    const balance = screen.getByDisplayValue("123456.00");
    await user.clear(balance);
    await user.type(balance, "100000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => {
      expect(updateDebt).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          name: "Основная карта",
          current_balance: { amount: "100000.00", currency: "RUB" },
          include_in_liquid_capital: true,
        }),
      );
    });
  });

  it("loads current property values and patches on save", async () => {
    vi.mocked(updateProperty).mockResolvedValue({
      ...property,
      mortgage_balance: { amount: "2900000.00", currency: "RUB" },
    });
    const user = userEvent.setup();
    render(<MonthLiabilitiesSection monthId={7} readOnly={false} />);
    const tables = await screen.findAllByRole("table");
    await user.click(
      within(tables[1]).getByRole("button", {
        name: "Действия для объекта «Синтетическая квартира»",
      }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
    expect(screen.getByDisplayValue("Синтетическая квартира")).toBeInTheDocument();
    const mortgage = screen.getByDisplayValue("3000000.00");
    await user.clear(mortgage);
    await user.type(mortgage, "2900000.00");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => {
      expect(updateProperty).toHaveBeenCalledWith(
        2,
        expect.objectContaining({
          name: "Синтетическая квартира",
          mortgage_balance: { amount: "2900000.00", currency: "RUB" },
          monthly_payment: { amount: "50000.00", currency: "RUB" },
        }),
      );
    });
  });

  it("disables liability mutations in a closed month", async () => {
    const user = userEvent.setup();
    render(<MonthLiabilitiesSection monthId={7} readOnly />);
    const [debtTable, propertyTable] = await screen.findAllByRole("table");
    await user.click(
      within(debtTable).getByRole("button", { name: "Действия для долга «Основная карта»" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    await user.keyboard("{Escape}");
    await user.click(
      within(propertyTable).getByRole("button", {
        name: "Действия для объекта «Синтетическая квартира»",
      }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
  });
});
