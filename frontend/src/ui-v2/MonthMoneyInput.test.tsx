import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MonthMoneyInput } from "./MonthMoneyInput";

describe("MonthMoneyInput", () => {
  it.each([
    ["540000.00", "540 000"],
    ["1234,50", "1 234,5"],
    ["-1234.56", "-1 234,56"],
    ["", ""],
    ["0", "0"],
    ["12 345,67", "12 345,67"],
    ["invalid", "invalid"],
    ["99999999999999999.01", "99 999 999 999 999 999,01"],
  ])("formats %s without changing the form string", (value, display) => {
    const change = vi.fn();
    render(<MonthMoneyInput aria-label="Сумма" value={value} onChange={change} />);
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue(display);
    fireEvent.focus(input);
    expect(input).toHaveValue(value);
    fireEvent.blur(input);
    expect(input).toHaveValue(display);
    expect(change).not.toHaveBeenCalled();
  });

  it.each(["1 234,50", "-1234.56", "", "0"])("emits the exact typed string %s", (value) => {
    const change = vi.fn();
    render(<MonthMoneyInput value="17" onChange={change} suffix="%" />);
    fireEvent.focus(screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value } });
    expect(change).toHaveBeenLastCalledWith(value);
  });
});
