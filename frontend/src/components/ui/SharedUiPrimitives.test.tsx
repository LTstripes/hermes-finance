import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataValue } from "./DataValue";
import { MoneyInput } from "./Field";
import { HelpTip } from "./HelpTip";
import { OverflowMenu, OverflowMenuItem } from "./OverflowMenu";
import { StickySubheader } from "./StickySubheader";

describe("shared UI primitives", () => {
  it("groups money on blur without changing the value while typing", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MoneyInput aria-label="Сумма" onChange={onChange} value="450000.00" />);

    const input = screen.getByRole("textbox", { name: "Сумма" });
    expect(input).toHaveValue("450\u00a0000,00");

    await user.click(input);
    expect(input).toHaveValue("450000.00");
    await user.tab();

    expect(input).toHaveValue("450\u00a0000,00");
    expect(onChange).toHaveBeenLastCalledWith("450\u00a0000,00");
  });

  it("opens compact help from keyboard-capable button and closes on Escape", async () => {
    const user = userEvent.setup();
    render(<HelpTip label="Как считается показатель">Берём только закрытые месяцы.</HelpTip>);

    const trigger = screen.getByRole("button", { name: "Как считается показатель" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    await user.click(trigger);

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Берём только закрытые месяцы.");
    expect(tooltip.parentElement).toBe(document.body);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("supports keyboard navigation and a secondary destructive overflow action", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    render(
      <OverflowMenu label="Действия месяца">
        <OverflowMenuItem onClick={onEdit}>Клонировать</OverflowMenuItem>
        <OverflowMenuItem danger>Удалить черновик</OverflowMenuItem>
      </OverflowMenu>,
    );

    const trigger = screen.getByRole("button", { name: "Действия месяца" });
    await user.click(trigger);

    const menu = screen.getByRole("menu");
    const clone = within(menu).getByRole("menuitem", { name: "Клонировать" });
    const remove = within(menu).getByRole("menuitem", { name: "Удалить черновик" });

    expect(clone).toHaveFocus();
    expect(remove).toHaveClass("overflow-menu__item--danger");

    await user.keyboard("{ArrowDown}");
    expect(remove).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(screen.getByRole("menuitem", { name: "Клонировать" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("keeps a portaled overflow menu connected to its trigger", async () => {
    const user = userEvent.setup();
    render(
      <OverflowMenu label="Действия строки">
        <OverflowMenuItem>Изменить</OverflowMenuItem>
      </OverflowMenu>,
    );

    const trigger = screen.getByRole("button", { name: "Действия строки" });
    await user.click(trigger);

    const menu = screen.getByRole("menu");
    expect(menu.parentElement).toBe(document.body);
    expect(within(menu).getByRole("menuitem", { name: "Изменить" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("places a bottom-edge help bubble above its trigger", async () => {
    const user = userEvent.setup();
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        if (this.getAttribute("role") === "tooltip") {
          return { bottom: 120, height: 120, left: 0, right: 200, top: 0, width: 200 } as DOMRect;
        }
        return { bottom: 724, height: 24, left: 700, right: 724, top: 700, width: 24 } as DOMRect;
      });

    try {
      render(<HelpTip label="Оценка">Подсказка</HelpTip>);
      await user.click(screen.getByRole("button", { name: "Оценка" }));

      const tooltip = screen.getByRole("tooltip");
      expect(tooltip).toHaveStyle({ position: "fixed", visibility: "visible" });
      expect(Number.parseFloat(tooltip.style.top)).toBeLessThan(700);
    } finally {
      rectSpy.mockRestore();
    }
  });

  it("renders read-only data and sticky workspace structure without editable controls", () => {
    render(
      <StickySubheader
        actions={<button type="button">Сохранить</button>}
        meta="Черновик"
        summary={<DataValue label="Капитал" value="4 900 000 ₽" />}
        title="Июль 2026"
      />,
    );

    expect(screen.getByText("Июль 2026")).toBeInTheDocument();
    expect(screen.getByText("4 900 000 ₽")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
