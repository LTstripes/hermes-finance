import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, notifyApiWrite } from "../api/client";
import type { MonthWorkingStatus } from "../api/types";
import { createQueryClient, queryKeys } from "../queryClient";
import { UiV2DataSubnav } from "./UiV2DataShell";
import { UiV2Shell } from "./UiV2Shell";

vi.unmock("./UiV2MonthPlate");

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>
  );
}

const draftStatus: MonthWorkingStatus = {
  month: {
    id: 7,
    year: 2031,
    month: 11,
    status: "draft",
    snapshot_date: "2031-11-30",
    source: "manual",
  },
  completed_steps: 4,
  total_steps: 10,
};

function closedStatus(): MonthWorkingStatus {
  if (!draftStatus.month) throw new Error("synthetic month is missing");
  return { ...draftStatus, month: { ...draftStatus.month, status: "closed" } };
}

function respondWith(body: unknown, status = 200) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function withClient(children: ReactNode, client = new QueryClient()) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderShell(path = "/v2") {
  return render(
    withClient(
      <MemoryRouter initialEntries={[path]}>
        <UiV2Shell active="home" header={<h1>Мои финансы</h1>}>
          <p>Контент</p>
        </UiV2Shell>
        <LocationProbe />
      </MemoryRouter>,
    ),
  );
}

beforeEach(() => {
  respondWith({ month: null, completed_steps: 0, total_steps: 10 });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UiV2Shell native navigation", () => {
  it.each([
    "/api/broker-months/apply",
    "/api/broker-months/intakes",
    "/api/broker-months/intakes/1/decisions",
    "/api/broker-months/intakes/1/finance-link",
    "/api/months/7/broker-sources",
  ])("leaves source dependencies to the command's ACK and GET at %s", async (path) => {
    const client = createQueryClient();
    const dependencies = [["accounts"], ["instruments"], ["broker-identity-mappings"]];
    for (const key of dependencies) client.setQueryData(key, ["saved"], { updatedAt: 1 });
    let finishOldRead: (value: string[]) => void = () => {};
    const oldRead = client
      .fetchQuery({
        queryKey: dependencies[0],
        queryFn: () =>
          new Promise<string[]>((resolve) => {
            finishOldRead = resolve;
          }),
      })
      .catch(() => undefined);
    const projection = ["returns", "synthetic"];
    client.setQueryData(projection, "before-write");
    const view = render(
      withClient(
        <MemoryRouter>
          <UiV2Shell header={<h1>Месяц</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
        client,
      ),
    );
    const dependencyEvents: string[] = [];
    const stop = client.getQueryCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        event.action.type === "invalidate" &&
        dependencies.some((key) => key[0] === event.query.queryKey[0])
      )
        dependencyEvents.push(String(event.query.queryKey[0]));
    });
    try {
      await act(() => notifyApiWrite(path, "POST"));
      finishOldRead(["obsolete"]);
      await oldRead;
      expect(client.getQueryData(dependencies[0])).toEqual(["saved"]);
      expect(dependencyEvents).toEqual([]);
      for (const key of dependencies) expect(client.getQueryState(key)?.isInvalidated).toBe(false);
      expect(client.getQueryState(projection)?.isInvalidated).toBe(true);
      const queryFn = vi.fn().mockResolvedValue("after-write");
      const observer = new QueryObserver(client, { queryKey: projection, queryFn });
      const stopObserver = observer.subscribe(() => {});
      await vi.waitFor(() => expect(client.getQueryData(projection)).toBe("after-write"));
      stopObserver();
    } finally {
      stop();
      view.unmount();
      client.clear();
    }
  });

  it("invalidates active writer reads without restarting them before the writer readback", async () => {
    const client = createQueryClient();
    const key = queryKeys.months;
    const queryFn = vi.fn().mockResolvedValueOnce("before-write").mockResolvedValue("after-write");
    const observer = new QueryObserver(client, { queryKey: key, queryFn });
    const stop = observer.subscribe(() => {});
    await vi.waitFor(() => expect(client.getQueryData(key)).toBe("before-write"));
    const view = render(
      withClient(
        <MemoryRouter>
          <UiV2Shell header={<h1>Капитал</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
        client,
      ),
    );
    try {
      await act(() => apiRequest("/api/positions/1", { method: "PATCH", body: {} }));
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
      expect(client.getQueryData(key)).toBe("before-write");
      expect(queryFn).toHaveBeenCalledTimes(1);
      // Only the writer's independent readback starts the next request.
      await act(() => observer.refetch());
      await vi.waitFor(() => expect(client.getQueryData(key)).toBe("after-write"));
      expect(queryFn).toHaveBeenCalledTimes(2);
    } finally {
      stop();
      view.unmount();
      client.clear();
    }
  });

  it("invalidates inactive projections after a write and rejects late pre-write responses", async () => {
    const client = createQueryClient();
    const key = ["synthetic-capital"];
    client.setQueryData(key, "saved", { updatedAt: 1 });
    let finishOldRead: (value: string) => void = () => {};
    const oldRead = client
      .fetchQuery({
        queryKey: key,
        queryFn: () =>
          new Promise<string>((resolve) => {
            finishOldRead = resolve;
          }),
      })
      .catch(() => undefined);
    const view = render(
      withClient(
        <MemoryRouter>
          <UiV2Shell header={<h1>Капитал</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
        client,
      ),
    );
    await act(() => apiRequest("/api/positions/1", { method: "PATCH", body: {} }));
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    finishOldRead("obsolete");
    await oldRead;
    expect(client.getQueryData(key)).toBe("saved");
    const queryFn = vi.fn().mockResolvedValue("after-write");
    const observer = new QueryObserver(client, { queryKey: key, queryFn });
    const stop = observer.subscribe(() => {});
    await vi.waitFor(() => expect(client.getQueryData(key)).toBe("after-write"));
    expect(queryFn).toHaveBeenCalledTimes(1);
    stop();
    view.unmount();
    client.clear();
  });

  it("keeps an active read in flight and lets its writer own the next readback", async () => {
    const client = createQueryClient();
    const key = queryKeys.instruments;
    client.setQueryData(key, "saved");
    let finishRead: (value: string) => void = () => {};
    let signal: AbortSignal | undefined;
    const observer = new QueryObserver(client, {
      queryKey: key,
      queryFn: (context) => {
        signal = context.signal;
        return new Promise<string>((resolve) => {
          finishRead = resolve;
        });
      },
    });
    const stop = observer.subscribe(() => {});
    const view = render(
      withClient(
        <MemoryRouter>
          <UiV2Shell header={<h1>Справочники</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
        client,
      ),
    );
    const pending = observer.refetch();
    try {
      await act(() => notifyApiWrite("/api/instruments/1", "PATCH"));
      expect(signal?.aborted).toBe(false);
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
      finishRead("readback");
      await act(() => pending);
      expect(client.getQueryData(key)).toBe("readback");
    } finally {
      stop();
      view.unmount();
      client.clear();
    }
  });

  it("refreshes only the working plate after a write and leaves restore to its own refresh", async () => {
    const client = createQueryClient();
    const fetchMock = respondWith(draftStatus);
    const view = render(
      withClient(
        <MemoryRouter>
          <UiV2Shell header={<h1>Месяц</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
        client,
      ),
    );
    try {
      await screen.findByRole("link", { name: /Рабочий месяц/ });
      await act(() => notifyApiWrite("/api/positions/1", "PATCH"));
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      await act(() => notifyApiWrite("/api/backups/synthetic/restore", "POST"));
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(client.getQueryState(queryKeys.monthWorkingStatus)?.isInvalidated).toBe(true);
    } finally {
      view.unmount();
      client.clear();
    }
  });
  it.each([
    "/v2/returns",
    "/v2/returns/account?scope=portfolio",
    "/v2/returns/instrument/RU000A000001",
  ])("marks the Returns parent current at %s", (path) => {
    render(
      withClient(
        <MemoryRouter initialEntries={[path]}>
          <UiV2Shell header={<h1>Синтетическая страница</h1>}>Контент</UiV2Shell>
        </MemoryRouter>,
      ),
    );
    const navigation = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(within(navigation).getByRole("link", { name: "Доходность" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(navigation.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  });

  it.each(["/v2/data/months?month=7", "/v2/reports"])(
    "marks the month plate at %s without selecting Settings",
    async (path) => {
      respondWith(draftStatus);
      render(
        withClient(
          <MemoryRouter initialEntries={[path]}>
            <UiV2Shell header={<h1>Все месяцы</h1>}>Контент</UiV2Shell>
          </MemoryRouter>,
        ),
      );
      expect(await screen.findByRole("link", { name: /Рабочий месяц/ })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(screen.getByRole("link", { name: "Настройки" })).not.toHaveAttribute("aria-current");
    },
  );

  it("keeps Close keyboard-operable and every shell link in v2", async () => {
    const user = userEvent.setup();
    renderShell();
    expect(screen.queryByText("Основной интерфейс")).not.toBeInTheDocument();
    expect(screen.queryByText("Рабочие разделы")).not.toBeInTheDocument();
    const close = screen.getByRole("link", { name: "Месяц" });
    expect(close).toHaveAttribute("href", "/v2/close");
    close.focus();
    expect(close).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("location")).toHaveTextContent("/v2/close");
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^(\/v2(?:\/|$)|#)/);
    }
    expect(screen.queryByRole("link", { name: "История и результаты" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Доход и цели" })).not.toBeInTheDocument();
    expect(screen.queryByText(/предыдущем интерфейсе/i)).not.toBeInTheDocument();
  });

  it.each([["Настройки", "/v2/data/overview"]])(
    "links %s to its native workspace",
    (label, href) => {
      renderShell();
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
      expect(screen.queryByRole("link", { name: /UI v1/ })).not.toBeInTheDocument();
    },
  );

  it("groups data tools under one Settings navigation entry while preserving their native deep links", () => {
    render(
      withClient(
        <MemoryRouter>
          <UiV2Shell active="data" header={<h1>Настройки</h1>}>
            <UiV2DataSubnav active="app" />
          </UiV2Shell>
        </MemoryRouter>,
      ),
    );
    const primary = screen.getByRole("navigation", { name: "Основная навигация" });
    expect(within(primary).getByRole("link", { name: "Настройки" })).toHaveAttribute(
      "href",
      "/v2/data/overview",
    );
    expect(within(primary).queryByRole("link", { name: "Данные" })).toBeNull();
    for (const [name, href] of [
      ["Обзор", "/v2/data/overview"],
      ["Источники данных", "/v2/data"],
      ["Приложение", "/v2/data/app"],
      ["Экспорт и копии", "/v2/data/files"],
      ["Счета и инструменты", "/v2/data/catalogs"],
    ])
      expect(
        within(screen.getByRole("navigation", { name: "Разделы настроек" })).getByRole("link", {
          name,
        }),
      ).toHaveAttribute("href", href);
    const settings = screen.getByRole("navigation", { name: "Разделы настроек" });
    expect(within(settings).getAllByRole("link")).toHaveLength(5);
    for (const name of ["Отчётные месяцы", "Выплаты", "Разбор источника"])
      expect(within(settings).queryByRole("link", { name })).toBeNull();
  });

  it.each(["?month=0", "?month=12&month=91"])(
    "preserves invalid month parameters in settings tabs: %s",
    (query) => {
      render(
        <MemoryRouter initialEntries={[`/v2/data${query}#diagnostics`]}>
          <UiV2DataSubnav active="sources" monthId={12} />
        </MemoryRouter>,
      );
      expect(screen.getByRole("link", { name: "Приложение" })).toHaveAttribute(
        "href",
        `/v2/data/app${query}#diagnostics`,
      );
    },
  );
});

describe("UiV2MonthPlate", () => {
  it("shows the draft month with its step progress and opens that month", async () => {
    respondWith(draftStatus);
    renderShell();
    const plate = await screen.findByRole("link", { name: /Рабочий месяц/ });
    expect(plate).toHaveAccessibleName(/^Рабочий месяц: Ноябрь.2031, 4 из 10 шагов$/);
    expect(plate).toHaveTextContent("4 из 10 шагов");
    expect(plate).toHaveAttribute("href", "/v2/close?month=7");
  });

  it("shows a closed month with its snapshot date, not as progress", async () => {
    respondWith(closedStatus());
    renderShell();
    const plate = await screen.findByRole("link", { name: /Рабочий месяц/ });
    expect(plate).toHaveTextContent("Закрыт · снимок 30.11.2031");
    expect(plate).not.toHaveTextContent("из 10");
  });

  it("marks the month workspace as the current page", async () => {
    respondWith(draftStatus);
    renderShell("/v2/close?month=7");
    expect(await screen.findByRole("link", { name: /Рабочий месяц/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("stays a plain month link when the status read fails", async () => {
    const fetchMock = respondWith({ error: { code: "synthetic", message: "x", details: [] } }, 500);
    renderShell();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: "Месяц" })).toHaveAttribute("href", "/v2/close");
  });

  it("reads only the narrow status endpoint, never the close workflow", async () => {
    const fetchMock = respondWith(draftStatus);
    renderShell();
    await screen.findByRole("link", { name: /Рабочий месяц/ });
    const urls = fetchMock.mock.calls.map(([url]: unknown[]) => String(url));
    expect(urls).toEqual([expect.stringContaining("/api/months/working-status")]);
  });

  it("is refreshed by month invalidation and by any saved mutation", async () => {
    const client = createQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await client
      .getMutationCache()
      .build(client, { mutationFn: async () => "saved" })
      .execute(undefined);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.monthWorkingStatus });
    expect(queryKeys.monthWorkingStatus.slice(0, 1)).toEqual([...queryKeys.months]);
  });
});
