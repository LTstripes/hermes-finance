import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { cloneMonth, createMonth, deleteMonth, listMonths } from "../api/months";
import type { ReportingMonth } from "../api/types";
import { createQueryClient, queryKeys } from "../queryClient";
import UiV2MonthsPage from "./UiV2MonthsPage";

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
  createMonth: vi.fn(),
  cloneMonth: vi.fn(),
  deleteMonth: vi.fn(),
}));

const closed: ReportingMonth = {
  id: 1,
  year: 2030,
  month: 5,
  snapshot_date: "2030-05-31",
  status: "closed",
  source: "manual",
};
const draft: ReportingMonth = {
  id: 2,
  year: 2030,
  month: 6,
  snapshot_date: "2030-06-30",
  status: "draft",
  source: "manual",
};
let rows: ReportingMonth[];

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderPage(path = "/v2/data/months") {
  const client = createQueryClient();
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Location />
          <Routes>
            <Route path="/v2/data/months" element={<UiV2MonthsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

async function ready() {
  return screen.findByRole("button", { name: "Удалить черновик" });
}

describe("native month management", () => {
  beforeEach(() => {
    rows = [draft, closed];
    vi.mocked(listMonths)
      .mockReset()
      .mockImplementation(async () => [...rows]);
    vi.mocked(createMonth).mockReset();
    vi.mocked(cloneMonth).mockReset();
    vi.mocked(deleteMonth).mockReset();
  });

  it("lists both statuses and preserves an invalid explicit selection", async () => {
    renderPage("/v2/data/months?month=999&from=close");
    await ready();
    expect(
      await screen.findByText("Запрошенный месяц не найден. Выбери другой период явно."),
    ).toBeInTheDocument();
    expect(screen.getByText("Закрыт")).toBeInTheDocument();
    expect(screen.getByText("Черновик")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("month=999");
    expect(screen.getAllByRole("link", { name: /Редактор в предыдущем интерфейсе/ })).toHaveLength(
      2,
    );
    expect(screen.getAllByRole("button", { name: "Удалить черновик" })).toHaveLength(1);
  });

  it("creates a period once and selects it only after list readback", async () => {
    const user = userEvent.setup();
    vi.mocked(createMonth).mockImplementation(async (payload) => {
      const created: ReportingMonth = { id: 3, status: "draft", source: "manual", ...payload };
      rows = [created, ...rows];
      return created;
    });
    renderPage();
    await ready();
    await user.click(screen.getByRole("button", { name: "Создать другой период" }));
    const form = screen.getByRole("region", { name: "Создание месяца" });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "Целевой год" }), {
      target: { value: "2030" },
    });
    await user.selectOptions(within(form).getByRole("combobox", { name: "Целевой месяц" }), "7");
    await user.click(within(form).getByRole("button", { name: "Создать месяц" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("month=3"));
    expect(createMonth).toHaveBeenCalledTimes(1);
    expect(createMonth).toHaveBeenCalledWith({
      year: 2030,
      month: 7,
      snapshot_date: "2030-07-31",
      source: "manual",
    });
    expect(listMonths).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Черновик Июль 2030 подтверждён/)).toBeInTheDocument();
  });

  it("clones from an exact source to a shown target and keeps failed conflict visible", async () => {
    const user = userEvent.setup();
    vi.mocked(cloneMonth).mockRejectedValue(new Error("Период уже существует"));
    renderPage();
    await ready();
    await user.click(screen.getByRole("button", { name: "Создать следующий месяц" }));
    const form = screen.getByRole("region", { name: "Копирование месяца" });
    expect(within(form).getByText(/Источник:/)).toHaveTextContent("Июнь 2030");
    expect(within(form).getByRole("spinbutton", { name: "Целевой год" })).toHaveValue(2030);
    expect(within(form).getByRole("combobox", { name: "Целевой месяц" })).toHaveValue("7");
    await user.click(within(form).getByRole("button", { name: "Копировать данные" }));
    await waitFor(() =>
      expect(cloneMonth).toHaveBeenCalledWith(2, {
        year: 2030,
        month: 7,
        snapshot_date: "2030-07-31",
      }),
    );
    expect(
      await screen.findByText(/Проверь обновлённый список перед повторной отправкой/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/data/months");
  });

  it("does not claim clone success until the new month appears in the API list", async () => {
    const user = userEvent.setup();
    vi.mocked(cloneMonth).mockResolvedValue({
      id: 3,
      year: 2030,
      month: 7,
      snapshot_date: "2030-07-31",
      status: "draft",
      source: "manual",
    });
    renderPage();
    await ready();
    await user.click(screen.getByRole("button", { name: "Создать следующий месяц" }));
    await user.click(screen.getByRole("button", { name: "Копировать данные" }));
    expect(
      await screen.findByText(/Созданный черновик не подтверждён обновлённым списком/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/data/months");
  });

  it("confirms a copied draft through list readback before selecting it", async () => {
    const user = userEvent.setup();
    const copied: ReportingMonth = {
      id: 3,
      year: 2030,
      month: 7,
      snapshot_date: "2030-07-31",
      status: "draft",
      source: "manual",
    };
    vi.mocked(cloneMonth).mockImplementation(async () => {
      rows = [copied, ...rows];
      return copied;
    });
    renderPage();
    await ready();
    await user.click(screen.getByRole("button", { name: "Создать следующий месяц" }));
    await user.click(screen.getByRole("button", { name: "Копировать данные" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("month=3"));
    expect(cloneMonth).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Черновик Июль 2030 подтверждён/)).toBeInTheDocument();
  });

  it("guards a second submit while the first create request is pending", async () => {
    const user = userEvent.setup();
    let finish: ((month: ReportingMonth) => void) | undefined;
    vi.mocked(createMonth).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    renderPage();
    await ready();
    await user.click(screen.getByRole("button", { name: "Создать другой период" }));
    const form = screen.getByRole("region", { name: "Создание месяца" });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "Целевой год" }), {
      target: { value: "2030" },
    });
    await user.selectOptions(within(form).getByRole("combobox", { name: "Целевой месяц" }), "7");
    const submit = within(form).getByRole("button", { name: "Создать месяц" });
    fireEvent.click(submit);
    fireEvent.submit(submit.closest("form") as HTMLFormElement);
    expect(createMonth).toHaveBeenCalledTimes(1);
    const created: ReportingMonth = {
      id: 3,
      year: 2030,
      month: 7,
      snapshot_date: "2030-07-31",
      status: "draft",
      source: "manual",
    };
    rows = [created, ...rows];
    finish?.(created);
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("month=3"));
  });

  it("cancels deletion, then clears a selected deleted month after confirmed readback", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteMonth).mockImplementation(async (id) => {
      rows = rows.filter((row) => row.id !== id);
    });
    renderPage("/v2/data/months?month=2&from=close");
    await ready();
    await user.click(screen.getByRole("button", { name: "Удалить черновик" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(deleteMonth).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Удалить черновик" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Удалить черновик" }),
    );
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("from=close"));
    expect(screen.getByTestId("location")).not.toHaveTextContent("month=2");
    expect(deleteMonth).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Удалить черновик" })).not.toBeInTheDocument();
  });

  it("does not turn a failed deletion into success", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteMonth).mockRejectedValue(new Error("request failed"));
    const { client } = renderPage("/v2/data/months?month=2");
    client.setQueryData(queryKeys.monthCloseWorkflow(2), { status: "stale-synthetic" });
    await ready();
    await user.click(screen.getByRole("button", { name: "Удалить черновик" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Удалить черновик" }),
    );
    expect(
      await screen.findByText(/Проверь обновлённый список перед повторной отправкой/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("month=2");
    expect(screen.queryByText(/Черновик Июнь 2030 удалён/)).not.toBeInTheDocument();
    expect(client.getQueryState(queryKeys.monthCloseWorkflow(2))?.isInvalidated).toBe(true);
  });
});
