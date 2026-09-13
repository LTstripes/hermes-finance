import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkedPairContext } from "./LinkedPairContext";

const account = {
  id: 11,
  name: "Синтетический депозит",
  account_type: "deposit",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const debt = {
  id: 1,
  reporting_month_id: 7,
  debt_type: "credit_card",
  name: "Основная карта",
  current_balance: { amount: "300000.00", currency: "RUB" },
  include_in_liquid_capital: true,
  linked_account_id: 11,
  annual_rate: null,
  next_due_date: null,
  contract_end_date: null,
  notes: null,
};

const pair = {
  debt_id: 1,
  debt_name: "Основная карта",
  debt_type: "credit_card",
  debt_balance: { amount: "300000.00", currency: "RUB" },
  account_id: 11,
  account_name: "Синтетический депозит",
  account_type: "deposit",
  account_balance: { amount: "1000000.00", currency: "RUB" },
  net_contribution: { amount: "700000.00", currency: "RUB" },
};

describe("LinkedPairContext", () => {
  it("keeps gross asset, linked debt, and net contribution distinct", () => {
    render(<LinkedPairContext accounts={[account]} debts={[debt]} pairs={[pair]} />);

    const card = screen.getByTestId("linked-pair-1");
    expect(card).toHaveTextContent("Синтетический депозит");
    expect(card).toHaveTextContent("Основная карта");
    expect(card).toHaveTextContent("Актив A · брутто");
    expect(card).toHaveTextContent("Связанный долг D");
    expect(card).toHaveTextContent("Чистый вклад A − D");
    expect(card).toHaveTextContent(/1\s*000\s*000\s*₽/);
    expect(card).toHaveTextContent(/300\s*000\s*₽/);
    expect(card).toHaveTextContent(/700\s*000\s*₽/);
    expect(card).toHaveTextContent("долг не вычитается повторно");
  });

  it("preserves the relation while showing unavailable account facts as unknown", () => {
    render(
      <LinkedPairContext
        accounts={[account]}
        debts={[debt]}
        error="Контекст связанной пары пока недоступен"
        pairs={null}
      />,
    );

    const card = screen.getByTestId("linked-pair-1");
    expect(within(card).getByText("Контекст неполный")).toBeInTheDocument();
    expect(card).toHaveTextContent("Связь сохранена");
    expect(card).toHaveTextContent("—");
    expect(card).not.toHaveTextContent("0,00 ₽");
  });
});
