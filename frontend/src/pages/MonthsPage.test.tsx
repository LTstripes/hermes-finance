import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { MonthsPage } from "./MonthsPage";

vi.mock("../api/months", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/months")>();
  return {
    ...actual,
    createMonth: vi.fn(),
    deleteMonth: vi.fn(),
    listMonths: vi.fn(),
  };
});

const draftMonth: ReportingMonth = {
  id: 1,
  year: 2026,
  month: 7,
  status: "draft",
  snapshot_date: "2026-07-31",
  source: "manual",
};
const closedMonth: ReportingMonth = { ...draftMonth, id: 2, month: 6, status: "closed" };

const listMonthsMock = vi.mocked(listMonths);
const createMonthMock = vi.mocked(createMonth);
const deleteMonthMock = vi.mocked(deleteMonth);

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/months"]}>
      <Routes>
        <Route element={<MonthsPage />} path="/months" />
      </Routes>
    </MemoryRouter>,
  );
}

describe("MonthsPage R03-05", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMonthsMock.mockResolvedValue([draftMonth, closedMonth]);
    createMonthMock.mockResolvedValue({ ...draftMonth, id: 3, month: 8 });
    deleteMonthMock.mockResolvedValue(undefined);
  });

  it("keeps the list primary and moves secondary actions into overflow", async () => {
    const user = userEvent.setup();
    renderPage();

    const table = await screen.findByRole("table");
    expect(screen.queryByRole("heading", { name: "Новый черновик" })).toBeNull();
    expect(within(table).queryByText("Вручную")).toBeNull();

    const draftRow = within(table).getByText(/Июль/).closest("tr");
    if (!draftRow) throw new Error("draft row not found");
    expect(within(draftRow).getByRole("link", { name: "Открыть" })).toHaveClass("btn--primary");

    await user.click(within(draftRow).getByRole("button", { name: /Действия для Июль/ }));
    expect(within(draftRow).getByRole("menuitem", { name: "Копировать данные" })).toBeVisible();
    expect(within(draftRow).getByRole("menuitem", { name: "Удалить черновик" })).toBeVisible();

    const closedRow = within(table).getByText(/Июнь/).closest("tr");
    if (!closedRow) throw new Error("closed row not found");
    await user.keyboard("{Escape}");
    await user.click(within(closedRow).getByRole("button", { name: /Действия для Июнь/ }));
    expect(within(closedRow).queryByRole("menuitem", { name: "Удалить черновик" })).toBeNull();
  });

  it("opens manual create in a keyboard-dismissible dialog", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Создать другой период" }));
    const dialog = screen.getByRole("dialog", { name: "Создать месяц" });
    expect(within(dialog).getByLabelText("Год")).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Создать месяц" })).toBeNull();
    expect(createMonthMock).not.toHaveBeenCalled();
  });

  it("explains the first-period empty state without internal action names", async () => {
    listMonthsMock.mockResolvedValueOnce([]);
    renderPage();

    expect(
      await screen.findByText(
        "Пока нет периодов. Создай первый период кнопкой «Создать другой период».",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/secondary-действие/i)).toBeNull();
  });
});
