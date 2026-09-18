import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import type { ReportingMonth, ReportingMonthStatus } from "../api/types";
import { makeUiV2Workflow, uiV2Months } from "../test/uiV2Fixtures";
import UiV2ClosePage from "../ui-v2/UiV2ClosePage";

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
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    if (url.pathname === "/api/months" && method === "GET") return jsonResponse(state.months);
    const workflowMatch = /^\/api\/months\/(\d+)\/close-workflow$/.exec(url.pathname);
    if (workflowMatch && method === "GET") {
      state.workflowReads += 1;
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
      return jsonResponse(
        state.persistedResponse?.(expectedStatus) ?? {
          ...state.workflow.month,
          status: expectedStatus,
        },
      );
    }
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
  return { fetchMock, mount, state };
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
  it("resolves the bare route to the shared newest draft and server recommendation", async () => {
    const { mount, state } = setup();
    mount();

    expect(await screen.findByRole("heading", { name: "Сверить состав портфеля" })).toBeVisible();
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent(
        "/v2/close?month=12&step=alfa_baseline",
      ),
    );
    expect(screen.getByText("1 из 8 шагов подтверждены сохранёнными фактами")).toBeVisible();
    expect(state.writes).toEqual([]);
  });

  it("lets the URL choose only the viewed step and keeps the server recommendation visible", async () => {
    const { mount } = setup("/v2/close?month=12&step=actual_payouts");
    mount();

    const current = await screen.findByRole("heading", { name: "Проверить полученные выплаты" });
    const panel = current.closest("section");
    if (!panel) throw new Error("Current-step panel is missing");
    expect(within(panel).getByText(/Следующее действие:/)).toHaveTextContent(
      "Сверить состав портфеля",
    );
    expect(
      within(panel).getByRole("link", { name: "Выбрать выписку с выплатами" }),
    ).toHaveAttribute("href", "/payouts?from=monthly-close-v2&step=actual_payouts&monthId=12");
    expect(screen.queryByRole("heading", { name: /Итоги Август 2031/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть итоговую проверку" })).toHaveAttribute(
      "href",
      "/v2/close?month=12&step=final_review_close",
    );
  });

  it.each([
    "/v2/close?month=12&step=../../settings",
    "/v2/close?month=12&step=actual_payouts&step=readiness",
  ])("falls back from an invalid viewed step to the server recommendation: %s", async (path) => {
    const { mount } = setup(path);
    mount();
    expect(await screen.findByRole("heading", { name: "Сверить состав портфеля" })).toBeVisible();
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent(
        "/v2/close?month=12&step=alfa_baseline",
      ),
    );
  });

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
    expect(await screen.findByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeVisible();
  });

  it("double-refetches, verifies persisted status and stays on the calm CLOSED review", async () => {
    const { fetchMock, mount, state } = setup("/v2/close?month=12&step=final_review_close");
    state.workflow = readyForClose();
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Закрыть месяц" }));
    expect(await screen.findByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
    expect(state.writes).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Месяц зафиксирован" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Вернуться в «Мои финансы»" })).toHaveAttribute(
      "href",
      "/v2",
    );
    expect(screen.queryByText(/из 8 шагов/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Открыть будущие события" })).toBeNull();
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

    expect(await screen.findByRole("alert")).toHaveTextContent("Состояние месяца не подтверждено");
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

    expect(await screen.findByRole("alert")).toHaveTextContent("Состояние месяца не подтверждено");
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

    expect(await screen.findByRole("alert")).toHaveTextContent("изменение для другого месяца");
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
    state.finalizeWrite = () => {
      state.workflow = makeUiV2Workflow();
      state.workflow.month = { ...state.workflow.month, id: 91, status: "draft" };
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
    await screen.findByRole("heading", { name: "Сверить состав портфеля" });
    const before = state.workflowReads;
    fireEvent.focus(window);
    await waitFor(() => expect(state.workflowReads).toBeGreaterThan(before));
  });
});
