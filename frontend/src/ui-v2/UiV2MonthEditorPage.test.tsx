import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import { createComment, deleteComment, listComments, moveComment } from "../api/comments";
import { getMonth, reopenMonth, updateMonth } from "../api/months";
import type { MonthlyComment, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import UiV2MonthEditorPage from "./UiV2MonthEditorPage";

vi.mock("../api/months", () => ({ getMonth: vi.fn(), updateMonth: vi.fn(), reopenMonth: vi.fn() }));
vi.mock("../api/comments", () => ({
  listComments: vi.fn(),
  createComment: vi.fn(),
  deleteComment: vi.fn(),
  moveComment: vi.fn(),
}));

const draft: ReportingMonth = {
  id: 7,
  year: 2030,
  month: 4,
  status: "draft",
  snapshot_date: "2030-04-30",
  source: "manual",
};
const closed: ReportingMonth = { ...draft, status: "closed" };
let current: ReportingMonth;
let notes: MonthlyComment[];

function Location() {
  const location = useLocation();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
      <Link to="/v2/data/months/8">Другой месяц</Link>
    </>
  );
}

function renderPage(path = "/v2/data/months/7") {
  const client = createQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/v2/data/months/:monthId" element={<UiV2MonthEditorPage />} />
          <Route path="/v2/data/months" element={<p>Список месяцев</p>} />
          <Route path="/v2/close" element={<p>Закрытие месяца</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("native month editor frame", () => {
  beforeEach(() => {
    current = { ...draft };
    notes = [];
    vi.mocked(getMonth)
      .mockReset()
      .mockImplementation(async (id) => {
        if (id !== current.id)
          throw new ApiClientError(404, { code: "not_found", message: "missing", details: [] });
        return { ...current };
      });
    vi.mocked(updateMonth)
      .mockReset()
      .mockImplementation(async (_id, payload) => {
        current = { ...current, ...payload };
        return { ...current };
      });
    vi.mocked(reopenMonth)
      .mockReset()
      .mockImplementation(async () => {
        current = { ...current, status: "draft" };
        return { ...current };
      });
    vi.mocked(listComments)
      .mockReset()
      .mockImplementation(async () => [...notes]);
    vi.mocked(createComment)
      .mockReset()
      .mockImplementation(async (payload) => {
        const created: MonthlyComment = {
          id: 9,
          reporting_month_id: payload.reporting_month_id,
          text: payload.text,
          position: 1,
        };
        notes = [created];
        return created;
      });
    vi.mocked(deleteComment).mockReset();
    vi.mocked(moveComment).mockReset();
  });

  it("loads only the explicit month and preserves invalid or missing targets", async () => {
    const first = renderPage("/v2/data/months/0");
    expect(screen.getByText("Некорректный идентификатор месяца.")).toBeInTheDocument();
    expect(getMonth).not.toHaveBeenCalled();
    first.unmount();
    renderPage("/v2/data/months/8");
    expect(
      await screen.findByText("Запрошенный месяц не найден. Выбери месяц из списка явно."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/data/months/8");
  });

  it("saves general fields only after exact readback", async () => {
    const user = userEvent.setup();
    renderPage();
    const section = await screen.findByRole("region", { name: "Общие данные месяца" });
    fireEvent.change(within(section).getByLabelText("Дата снимка"), {
      target: { value: "2030-04-29" },
    });
    await user.click(within(section).getByRole("button", { name: "Сохранить общие данные" }));
    expect(
      await within(section).findByText("Общие данные сохранены и подтверждены."),
    ).toBeInTheDocument();
    expect(updateMonth).toHaveBeenCalledWith(7, { snapshot_date: "2030-04-29" });
    expect(getMonth).toHaveBeenCalledTimes(2);
  });

  it("keeps failed save visible and blocks navigation until cancelled", async () => {
    const user = userEvent.setup();
    vi.mocked(updateMonth).mockRejectedValue(new Error("save failed"));
    renderPage();
    await screen.findByRole("region", { name: "Общие данные месяца" });
    fireEvent.change(screen.getByLabelText("Дата снимка"), { target: { value: "2030-04-29" } });
    await user.click(screen.getByRole("button", { name: "Сохранить общие данные" }));
    expect(await screen.findByText("save failed")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "← Все месяцы" }));
    expect(
      screen.getByText("Есть несохранённые изменения. Перейти и потерять их?"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Остаться" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/data/months/7");
  });

  it("keeps CLOSED read-only and refreshes after explicit reopen", async () => {
    const user = userEvent.setup();
    current = { ...closed };
    renderPage("/v2/data/months/7?from=monthly-close-v2&monthId=7&step=month_setup");
    await screen.findByRole("region", { name: "Общие данные месяца" });
    expect(screen.getByLabelText("Дата снимка")).toBeDisabled();
    expect(screen.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
      "href",
      "/v2/close?month=7&step=month_setup",
    );
    await user.click(screen.getByRole("button", { name: "Открыть для редактирования" }));
    expect(reopenMonth).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Открыть месяц" }));
    expect(
      await screen.findByText("Месяц открыт для редактирования. Данные перечитаны."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Дата снимка")).toBeEnabled();
    expect(getMonth).toHaveBeenCalledTimes(2);
  });

  it("does not unlock a month on failed reopen", async () => {
    const user = userEvent.setup();
    current = { ...closed };
    vi.mocked(reopenMonth).mockRejectedValue(new Error("reopen failed"));
    renderPage();
    await screen.findByRole("region", { name: "Общие данные месяца" });
    await user.click(screen.getByRole("button", { name: "Открыть для редактирования" }));
    await user.click(screen.getByRole("button", { name: "Открыть месяц" }));
    expect(await screen.findByText("reopen failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Дата снимка")).toBeDisabled();
  });

  it("saves a note with readback and keeps a draft when save fails", async () => {
    const user = userEvent.setup();
    renderPage("/v2/data/months/7?section=note");
    await screen.findByRole("region", { name: "Заметки месяца" });
    const input = screen.getByLabelText("Новая заметка");
    await user.type(input, "Проверить месяц");
    await user.click(screen.getByRole("button", { name: "Добавить заметку" }));
    expect(await screen.findByText("Заметка сохранена и подтверждена.")).toBeInTheDocument();
    expect(createComment).toHaveBeenCalledWith({ reporting_month_id: 7, text: "Проверить месяц" });
    await waitFor(() => expect(input).toHaveValue(""));
    vi.mocked(createComment).mockRejectedValue(new Error("note failed"));
    await user.type(input, "Повторить");
    await user.click(screen.getByRole("button", { name: "Добавить заметку" }));
    expect(await screen.findByText("note failed")).toBeInTheDocument();
    expect(input).toHaveValue("Повторить");
  });

  it("does not apply an old month save response to a newly selected month", async () => {
    const user = userEvent.setup();
    let finishSave!: (value: ReportingMonth) => void;
    vi.mocked(updateMonth).mockImplementation(
      () =>
        new Promise((resolve) => {
          finishSave = resolve;
        }),
    );
    vi.mocked(getMonth).mockImplementation(async (id) =>
      id === 7
        ? { ...draft }
        : {
            ...draft,
            id: 8,
            month: 5,
            snapshot_date: "2030-05-31",
          },
    );
    renderPage();
    await screen.findByRole("region", { name: "Общие данные месяца" });
    fireEvent.change(screen.getByLabelText("Дата снимка"), { target: { value: "2030-04-29" } });
    await user.click(screen.getByRole("button", { name: "Сохранить общие данные" }));
    await user.click(screen.getByRole("link", { name: "Другой месяц" }));
    await user.click(screen.getByRole("button", { name: "Перейти без сохранения" }));
    expect(await screen.findByText("Май 2030")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/data/months/8");
    finishSave({ ...draft, snapshot_date: "2030-04-29" });
    await waitFor(() =>
      expect(screen.queryByText("Общие данные сохранены и подтверждены.")).not.toBeInTheDocument(),
    );
  });
});
