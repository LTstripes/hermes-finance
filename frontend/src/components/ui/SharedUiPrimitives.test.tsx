import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataValue } from "./DataValue";
import { HelpTip } from "./HelpTip";
import { OverflowMenu, OverflowMenuItem } from "./OverflowMenu";
import { StickySubheader } from "./StickySubheader";

describe("shared UI primitives", () => {
  it("opens compact help from keyboard-capable button and closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <HelpTip label="Как считается показатель">
        Берём только закрытые месяцы.
      </HelpTip>,
    );

    const trigger = screen.getByRole("button", { name: "Как считается показатель" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    await user.click(trigger);

    expect(screen.getByRole("tooltip")).toHaveTextContent("Берём только закрытые месяцы.");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("supports keyboard navigation and a visually secondary destructive overflow action", async () => {
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

  it("renders read-only financial data and sticky workspace structure without editable controls", () => {
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
