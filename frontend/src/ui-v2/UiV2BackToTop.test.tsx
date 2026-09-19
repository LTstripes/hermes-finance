import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UiV2BackToTop } from "./UiV2BackToTop";

const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;

function setScrollTop(value: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value });
  act(() => window.dispatchEvent(new Event("scroll")));
}

describe("UiV2BackToTop", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: true, addListener: vi.fn(), removeListener: vi.fn() })),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: originalScrollIntoView,
    });
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  });

  it("stays quiet until the page has moved by a meaningful distance", () => {
    render(<UiV2BackToTop targetId="v2-main" />);

    expect(screen.queryByRole("button", { name: "Наверх" })).toBeNull();
    setScrollTop(319);
    expect(screen.queryByRole("button", { name: "Наверх" })).toBeNull();
    setScrollTop(320);
    expect(screen.getByRole("button", { name: "Наверх" })).toBeVisible();
  });

  it("can be activated from the keyboard and returns focus to v2 main content", async () => {
    const user = userEvent.setup();
    const main = document.createElement("main");
    main.id = "v2-main";
    main.tabIndex = -1;
    document.body.append(main);
    render(<UiV2BackToTop targetId="v2-main" />);
    setScrollTop(480);

    const button = screen.getByRole("button", { name: "Наверх" });
    await user.tab();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(main).toHaveFocus();
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({
      behavior: "auto",
      block: "start",
    });
  });

  it("stays out of the tab order while a modal is open", async () => {
    render(<UiV2BackToTop targetId="v2-main" />);
    setScrollTop(480);
    expect(screen.getByRole("button", { name: "Наверх" })).toBeVisible();

    const modal = document.createElement("div");
    modal.setAttribute("aria-modal", "true");
    document.body.append(modal);

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Наверх" })).toBeNull();
    });
  });
});
