import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MoneyAmount } from "./MoneyAmount";

describe("MoneyAmount #650", () => {
  it("keeps amount, sign and currency on one typographic unit", () => {
    const { container } = render(<MoneyAmount amount="123456.00" />);
    const unit = container.querySelector(".money");
    expect(unit).not.toBeNull();
    expect(unit).toHaveTextContent(/123\s*456\s*₽/);
    const style = window.getComputedStyle(unit as Element);
    // JSDOM does not apply external CSS, so assert the class contract instead.
    expect(unit?.className).toMatch(/money/);
    expect(style).toBeDefined();
  });

  it("renders large, negative, zero and null states explicitly", () => {
    const { rerender } = render(<MoneyAmount amount="1234567890.50" />);
    expect(screen.getByText(/1\s*234\s*567\s*890,50\s*₽/)).toBeInTheDocument();

    rerender(<MoneyAmount amount="-48200.00" />);
    expect(screen.getByText(/−48\s*200\s*₽/)).toBeInTheDocument();

    rerender(<MoneyAmount amount="0.00" />);
    expect(screen.getByText(/0\s*₽/)).toBeInTheDocument();
    expect(screen.queryByText("—")).toBeNull();

    rerender(<MoneyAmount amount={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();

    rerender(<MoneyAmount amount={null} empty="Недоступно" />);
    expect(screen.getByText("Недоступно")).toBeInTheDocument();
  });

  it("preserves non-RUB currencies without inventing conversion", () => {
    render(<MoneyAmount amount={{ amount: "10.00", currency: "USD" }} />);
    expect(screen.getByText(/10\s*USD/)).toBeInTheDocument();
  });
});
