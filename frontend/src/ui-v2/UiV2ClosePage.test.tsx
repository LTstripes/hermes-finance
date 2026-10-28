import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { ReportingMonth, ReportingMonthStatus } from "../api/types";
import { queryKeys } from "../queryClient";
import { makeUiV2Workflow, uiV2Months } from "../test/uiV2Fixtures";
import { brokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import UiV2ClosePage from "./UiV2ClosePage";

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="test-location">{`${location.pathname}${location.search}`}</output>;
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function readyForClose(monthId = 12): MonthCloseWorkflow {
  const workflow = structuredClone(makeUiV2Workflow({ monthId }));
  workflow.recommended_step_id = "final_review_close";
  const finalStep = workflow.steps.find((step) => step.id === "final_review_close");
  if (!finalStep) throw new Error("Synthetic final step is missing");
  finalStep.state = "ready";
  finalStep.primary_action = {
    id: "confirm_close",
    label: "Закрыть месяц",
    target: "confirm_close",
  };
  workflow.readiness.can_close = true;
  workflow.readiness.hard_blocker_count = 0;
  return workflow;
}

function closedFrom(workflow: MonthCloseWorkflow): MonthCloseWorkflow {
  const closed = structuredClone(workflow);
  closed.month.status = "closed";
  closed.recommended_step_id = "next_month_outlook";
  if (closed.final_review.available) closed.final_review.month_header.status = "closed";
  for (const step of closed.steps) step.primary_action = null;
  closed.outlook = {
    available: false,
    reason_code: "no_known_dated_events",
    source_month: { ...closed.month },
    next_month: null,
    upcoming_14_days: null,
    upcoming_30_days: null,
    known_event_count: 0,
    evidence_version: "synthetic-closed-v1",
  };
  return closed;
}

function setup(path = "/v2/close") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const state = {
    months: structuredClone(uiV2Months),
    workflow: structuredClone(makeUiV2Workflow()),
    workflowReads: 0,
    writes: [] as string[],
    workflowResponse: null as null | ((read: number) => MonthCloseWorkflow),
    finalizeWrite: null as null | ((status: "closed" | "draft") => void),
    persistedResponse: null as null | ((status: ReportingMonthStatus) => ReportingMonth),
    lostAck: false,
    failedReads: false,
    failedStatus: 503,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    if (url.pathname === "/api/months" && method === "GET") return jsonResponse(state.months);
    if (url.pathname === "/api/months/12/draft-payouts" && method === "GET")
      return jsonResponse({
        reporting_month_id: 12,
        status: "draft",
        context_digest: "a".repeat(64),
        eligible_positions: 0,
        items: [],
      });
    if (url.pathname === "/api/payouts/calendar" && method === "GET") return jsonResponse([]);
    const workflowMatch = /^\/api\/months\/(\d+)\/close-workflow$/.exec(url.pathname);
    if (workflowMatch && method === "GET") {
      state.workflowReads += 1;
      if (state.failedReads)
        return jsonResponse({ detail: "synthetic GET failure" }, state.failedStatus);
      return jsonResponse(
        state.workflowResponse?.(state.workflowReads) ?? structuredClone(state.workflow),
      );
    }
    const lifecycleMatch = /^\/api\/months\/(\d+)\/(close|reopen)$/.exec(url.pathname);
    if (lifecycleMatch && method === "POST") {
      state.writes.push(lifecycleMatch[2]);
      const expectedStatus = lifecycleMatch[2] === "close" ? "closed" : "draft";
      state.workflow =
        expectedStatus === "closed"
          ? closedFrom(state.workflow)
          : {
              ...structuredClone(makeUiV2Workflow()),
              month: { ...state.workflow.month, status: "draft" },
            };
      if (state.finalizeWrite) state.finalizeWrite(expectedStatus);
      if (state.lostAck) throw new TypeError("synthetic lost ACK");
      return jsonResponse(
        state.persistedResponse?.(expectedStatus) ?? {
          ...state.workflow.month,
          status: expectedStatus,
        },
      );
    }
    if (
      method === "GET" &&
      ["/api/accounts", "/api/broker-months", "/api/broker-months/intakes"].includes(url.pathname)
    )
      return jsonResponse([]);
    throw new Error(`Unexpected API: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  function mount(entry = path) {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[entry]}>
          <LocationProbe />
          <Routes>
            <Route path="v2/close" element={<UiV2ClosePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { client, fetchMock, mount, state };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("native Monthly Close work mode", () => {
  it("payouts reuses saved DRAFT and calendar without loading a second XML review", async () => {
    const { mount, fetchMock } = setup("/v2/close?month=12&panel=payouts");
    mount();
    await screen.findByRole("button", { name: "Получить и сохранить прогнозы Т-Инвест" });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/draft-payouts"))).toBe(
        true,
      ),
    );
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/api/broker-months/intakes")),
    ).toBe(false);
    expect(screen.queryByText("Исправления и сохранение месяца")).toBeNull();
    expect(screen.queryByLabelText("XML-файлы")).toBeNull();
    expect(screen.getByRole("link", { name: "Ожидается · T-Invest" })).toHaveAttribute(
      "href",
      "#month-draft-payouts",
    );
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(
      true,
    );
  });
  it("retains the actual File when source discard leaves Month for a catalogue round-trip", async () => {
    const { mount, client } = setup("/v2/close?month=12&panel=brokers");
    mount();
    await screen.findByRole("navigation", { name: "Разделы месяца" });
    const session = brokerOriginalSession(client);
    const file = new File(["synthetic"], "synthetic.xml");
    await act(async () => session.select(file, 12, ""));
    fireEvent.click(screen.getByRole("link", { name: /^Данные$/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Перейти без сохранения" }));
    await waitFor(() => expect(screen.getByTestId("test-location")).toHaveTextContent("/v2/data"));
    expect(session.snapshot().file).toBe(file);
    expect(session.snapshot().confirmed).toBeNull();
  });
  it("keeps a selected original on Stay and clears it only on explicit source discard into payouts", async () => {
    const { mount, client } = setup("/v2/close?month=12&panel=brokers");
    const session = brokerOriginalSession(client);
    const file = new File(["synthetic"], "synthetic.xml");
    mount();
    const nav = await screen.findByRole("navigation", { name: "Разделы месяца" });
    await act(async () => session.select(file, 12, ""));
    fireEvent.click(within(nav).getByRole("link", { name: /^Выплаты/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Остаться" }));
    expect(session.snapshot().file).toBe(file);
    fireEvent.click(within(nav).getByRole("link", { name: /^Выплаты/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Перейти без сохранения" }));
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent("panel=payouts"),
    );
    expect(session.snapshot().file).toBeNull();
    fireEvent.click(within(nav).getByRole("link", { name: /Счета и позиции/ }));
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent("panel=positions"),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
  it.each(["failed", "draft", "ack404", "ack409"])(
    "holds unknown Close across %s GET, navigation and repeated clicks until GET proves status",
    async (readback) => {
      const { mount, state, client } = setup("/v2/close?month=12&panel=close");
      state.workflow = readyForClose();
      state.lostAck = !readback.startsWith("ack");
      state.failedStatus = readback === "ack404" ? 404 : readback === "ack409" ? 409 : 503;
      state.finalizeWrite = () => {
        if (readback !== "draft") state.failedReads = true;
        else state.workflow = readyForClose();
      };
      for (const key of [["dashboard", 12], ["capital-analysis"], ["monthly-returns"], ["charts"]])
        client.setQueryData(key, { synthetic: "old" });
      mount();
      fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
      fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));
      const recovery = await screen.findByRole("button", { name: "Проверить состояние месяца" });
      await waitFor(() => expect(recovery).toBeEnabled());
      expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
      fireEvent.click(screen.getAllByRole("link", { name: "← К месяцу" })[0]);
      expect(await screen.findByRole("alertdialog")).toHaveTextContent(
        "Сохранение ещё не подтверждено",
      );
      fireEvent.click(screen.getByRole("button", { name: "Вернуться к форме" }));
      expect(state.writes).toEqual(["close"]);
      state.failedReads = false;
      state.workflow = closedFrom(readyForClose());
      state.months = state.months.map((month) =>
        month.id === 12 ? { ...month, status: "closed" } : month,
      );
      fireEvent.click(recovery);
      await waitFor(() =>
        expect(screen.queryByRole("button", { name: "Проверить состояние месяца" })).toBeNull(),
      );
      expect((await screen.findAllByText("Месяц закрыт", { exact: true }))[0]).toBeVisible();
      for (const key of [["dashboard", 12], ["capital-analysis"], ["monthly-returns"], ["charts"]])
        expect(client.getQueryState(key)?.isInvalidated).toBe(true);
      expect(state.writes).toEqual(["close"]);
    },
  );
  it("enters on tiles only and keeps every section in the exact-month workspace", async () => {
    const { mount, state } = setup();
    mount();
    const nav = await screen.findByRole("navigation", { name: "Разделы месяца" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Месяц · Август 2031");
    expect(screen.getByText(/Снимок 30.08.2031/)).toBeVisible();
    expect(within(nav).getAllByRole("link")).toHaveLength(10);
    const panels = within(nav)
      .getAllByRole("link")
      .map((link) =>
        new URL(link.getAttribute("href") ?? "", "http://synthetic").searchParams.get("panel"),
      );
    expect(panels.indexOf("brokers")).toBeLessThan(panels.indexOf("positions"));
    expect(panels.indexOf("positions")).toBeLessThan(panels.indexOf("payouts"));
    expect(within(nav).getByRole("link", { name: /Выплаты/ })).toHaveTextContent("T-Invest");
    for (const link of within(nav).getAllByRole("link"))
      expect(
        new URL(link.getAttribute("href") ?? "", "http://synthetic").searchParams.get("month"),
      ).toBe("12");
    expect(document.getElementById("month-work-area")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent("/v2/close?month=12"),
    );
    expect(state.writes).toEqual([]);
    fireEvent.click(within(nav).getByRole("link", { name: /Закрыть месяц/ }));
    expect(
      await screen.findByRole("region", { name: "Рабочая область: Закрыть месяц" }),
    ).toBeVisible();
    expect(document.querySelectorAll("#month-work-area")).toHaveLength(1);
    expect(within(nav).getByRole("link", { name: /Закрыть месяц/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getAllByRole("link", { name: "← К месяцу" })[0]);
    expect(document.getElementById("month-work-area")).toBeNull();
  });

  it("keeps legacy step links in collapsed additional integrations without automatic provider calls", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=actual_payouts");
    mount();
    await screen.findByRole("region", { name: "Рабочая область: Закрыть месяц" });
    const details = screen.getByText("Дополнительные интеграции и проверки").closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Дополнительные интеграции и проверки"));
    expect(screen.getByRole("link", { name: "Выбрать выписку с выплатами" })).toHaveAttribute(
      "href",
      "/v2/data/payouts?month=12&from=monthly-close-v2&step=actual_payouts&monthId=12#statement-import",
    );
    expect(state.writes).toEqual([]);
  });

  it.each(["/v2/close?month=12&panel=bad", "/v2/close?month=12&panel=income&panel=assets"])(
    "rejects invalid panel without mounting forms: %s",
    async (path) => {
      const { mount, state } = setup(path);
      mount();
      expect(await screen.findByRole("heading", { name: "Неизвестный раздел" })).toBeVisible();
      expect(document.getElementById("month-work-area")).toBeNull();
      expect(state.writes).toEqual([]);
    },
  );

  it.each([
    ["/v2/close?month=012", "Некорректный месяц"],
    ["/v2/close?month=404", "Месяц не найден"],
  ])("fails closed for invalid or unknown explicit month: %s", async (path, title) => {
    const { mount, state } = setup(path);
    mount();
    expect(await screen.findByRole("heading", { name: title })).toBeVisible();
    expect(state.workflowReads).toBe(0);
  });

  it("renders the full final review only on the final step", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    mount();
    await screen.findByRole("group", { name: "Итоги месяца" });
    expect(
      screen.getByText("Подробнее об итогах и проверках").closest("details"),
    ).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Подробнее об итогах и проверках"));
    expect(await screen.findByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeVisible();
  });

  it("fails closed when final review belongs to another month", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    if (!state.workflow.final_review.available) throw new Error("Review fixture is missing");
    state.workflow.final_review.month_header.id = 91;
    mount();
    expect(
      await screen.findByRole("heading", { name: "Состояние месяца не подтверждено" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Закрыть месяц" })).toBeNull();
    expect(state.writes).toEqual([]);
  });

  it("double-refetches, verifies persisted status and stays on the calm CLOSED review", async () => {
    const { fetchMock, mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    expect(await screen.findByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
    expect(state.writes).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));

    expect((await screen.findAllByText("Месяц закрыт", { exact: true }))[0]).toBeVisible();
    expect(screen.getByRole("link", { name: "Открыть «Мои финансы»" })).toHaveAttribute(
      "href",
      "/v2",
    );
    expect(state.writes).toEqual(["close"]);
    const workflowGets = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/close-workflow") && (init?.method ?? "GET") === "GET",
    );
    expect(workflowGets.length).toBeGreaterThanOrEqual(4);
  });

  it("fails closed when a pre-close refetch returns another month", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const draft = readyForClose();
    const wrongMonth = readyForClose(91);
    state.workflow = draft;
    state.workflowResponse = (read) => (read >= 2 ? wrongMonth : draft);
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));

    await waitFor(() =>
      expect(
        screen
          .getAllByRole("alert")
          .some((node) => node.textContent?.includes("Получено состояние другого месяца")),
      ).toBe(true),
    );
    expect(screen.queryByRole("alertdialog", { name: "Закрыть месяц?" })).toBeNull();
    expect(state.writes).toEqual([]);
  });

  it("fails closed when a pre-close refetch returns another workflow contract", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const draft = readyForClose();
    const wrongContract = {
      ...structuredClone(draft),
      contract_version: "monthly_close_workflow_v2",
    } as unknown as MonthCloseWorkflow;
    state.workflow = draft;
    state.workflowResponse = (read) => (read >= 2 ? wrongContract : draft);
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));

    await waitFor(() =>
      expect(
        screen
          .getAllByRole("alert")
          .some((node) => node.textContent?.includes("неподдерживаемую версию")),
      ).toBe(true),
    );
    expect(screen.queryByRole("alertdialog", { name: "Закрыть месяц?" })).toBeNull();
    expect(state.writes).toEqual([]);
  });

  it("rejects a persisted close response for another month", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    const selectedMonth = state.months.find((month) => month.id === 12);
    if (!selectedMonth) throw new Error("Synthetic selected month is missing");
    state.persistedResponse = (status) => ({
      ...selectedMonth,
      id: 91,
      status,
    });
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("подтверждено для другого месяца");
    expect(state.writes).toEqual(["close"]);
  });

  it("rejects a post-close workflow refetch for another month", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const draft = readyForClose();
    const wrongMonth = closedFrom(readyForClose(91));
    state.workflow = draft;
    state.workflowResponse = (read) => (read === 4 ? wrongMonth : state.workflow);
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("состояние другого месяца");
    expect(state.writes).toEqual(["close"]);
  });

  it("stops a close race when another tab closes the month before confirmation", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const draft = readyForClose();
    const closed = closedFrom(draft);
    state.workflow = draft;
    state.workflowResponse = (read) => (read >= 3 ? closed : draft);
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    expect(await screen.findByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("закрыт в другой вкладке");
    expect(state.writes).toEqual([]);
  });

  it("rechecks before reopen and derives the draft workflow after the persisted command", async () => {
    const { mount, state } = setup("/v2/close?month=91&step=next_month_outlook");
    state.workflow = makeUiV2Workflow({ monthId: 91 });
    const originalPeriod = { ...state.workflow.month };
    state.finalizeWrite = () => {
      state.workflow = makeUiV2Workflow();
      state.workflow.month = { ...originalPeriod, status: "draft" };
      if (state.workflow.final_review.available) {
        state.workflow.final_review.month_header = { ...state.workflow.month };
      }
    };
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Открыть месяц заново" }));
    fireEvent.click(await screen.findByRole("button", { name: "Открыть заново" }));
    await waitFor(() => expect(state.writes).toEqual(["reopen"]));
    expect(await screen.findByText("Черновик")).toBeVisible();
  });

  it("refetches authoritative workflow on window focus", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=alfa_baseline");
    mount();
    await screen.findByRole("region", { name: "Рабочая область: Закрыть месяц" });
    const before = state.workflowReads;
    fireEvent.focus(window);
    await waitFor(() => expect(state.workflowReads).toBeGreaterThan(before));
  });

  it("keeps final review above collapsed progress with an accessible close and exact-month edit", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close&context=retained");
    state.workflow = readyForClose();
    mount();
    const close = await screen.findByRole("button", { name: "Закрыть месяц" });
    const progress = screen.getByText("Дополнительные интеграции и проверки").closest("details");
    expect(progress).not.toHaveAttribute("open");
    expect(screen.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
    expect(close).toBeVisible();
    expect(screen.getByTestId("test-location")).toHaveTextContent("context=retained");
    expect(state.writes).toEqual([]);
  });

  it("rejects a reused ID for a different reporting period before sending Close", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const original = readyForClose();
    const reused = structuredClone(original);
    reused.month.year += 1;
    if (reused.final_review.available) reused.final_review.month_header = { ...reused.month };
    state.workflow = original;
    state.workflowResponse = (read) => (read >= 3 ? reused : original);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(state.writes).toEqual([]);
  });

  it("rejects a foreign final review arriving after the confirmation dialog opens", async () => {
    const { mount, state } = setup("/v2/close?month=12&step=final_review_close");
    const original = readyForClose();
    const foreign = structuredClone(original);
    if (foreign.final_review.available) foreign.final_review.month_header.id = 91;
    state.workflow = original;
    state.workflowResponse = (read) => (read >= 3 ? foreign : original);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(state.writes).toEqual([]);
  });

  it("pins the original period when both months and workflow refresh to a reused ID", async () => {
    const { client, mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    const originalHeading = `Месяц · Август ${state.workflow.month.year}`;
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    await screen.findByRole("alertdialog");
    state.months = state.months.map((month) =>
      month.id === 12 ? { ...month, year: month.year + 1 } : month,
    );
    state.workflow.month.year += 1;
    if (state.workflow.final_review.available)
      state.workflow.final_review.month_header = { ...state.workflow.month };
    await act(async () => {
      await client.refetchQueries();
    });
    expect(
      await screen.findByRole("heading", { name: "Период выбранного месяца изменился" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(originalHeading);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByRole("button", { name: "Закрыть месяц" })).toBeNull();
    expect(state.writes).toEqual([]);
    // Explicitly leaving and selecting this period again establishes a new identity.
    view.unmount();
    mount();
    expect(await screen.findByRole("button", { name: "Закрыть месяц" })).toBeVisible();
    expect(state.writes).toEqual([]);
  });

  it("retains the selected identity while a deleted ID disappears and is recreated", async () => {
    const { client, mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    mount();
    await screen.findByRole("button", { name: "Закрыть месяц" });
    state.months = state.months.filter((month) => month.id !== 12);
    await act(async () => {
      await client.refetchQueries({ queryKey: queryKeys.months });
    });
    await screen.findByRole("heading", { name: "Месяц не найден" });
    state.months = structuredClone(uiV2Months).map((month) =>
      month.id === 12 ? { ...month, year: month.year + 1 } : month,
    );
    state.workflow.month.year += 1;
    if (state.workflow.final_review.available)
      state.workflow.final_review.month_header = { ...state.workflow.month };
    await act(async () => {
      await client.refetchQueries();
    });
    expect(
      await screen.findByRole("heading", { name: "Период выбранного месяца изменился" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Закрыть месяц" })).toBeNull();
    expect(state.writes).toEqual([]);
  });
});
