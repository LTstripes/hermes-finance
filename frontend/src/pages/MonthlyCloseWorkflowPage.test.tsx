import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";

import type { MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { formatMoney } from "../lib/format";
import { MonthlyCloseWorkflowPage } from "./MonthlyCloseWorkflowPage";

function money(amount: string) {
  return { amount, currency: "RUB" };
}

function workflow(
  monthId: number,
  status: "draft" | "closed" = "draft",
  outlookMode: "known" | "none" = "known",
): MonthCloseWorkflow {
  const month = {
    id: monthId,
    year: 2025,
    month: 4,
    status,
    snapshot_date: "2025-04-30",
    source: "manual",
  } as const;
  return {
    contract_version: "monthly_close_workflow_v1",
    generated_at: "2026-09-01T08:00:00Z",
    month,
    recommended_step_id: status === "closed" ? "next_month_outlook" : "readiness",
    progress: { completed_or_skipped: 2, total_applicable: 8 },
    steps: [
      {
        id: status === "closed" ? "next_month_outlook" : "readiness",
        order: 7,
        title: status === "closed" ? "Что известно о следующем месяце" : "Проверить готовность",
        state: "ready",
        applicability: "mandatory",
        gate: "advisory",
        affects_close: false,
        why: "Состояние рассчитано системой.",
        reason_codes: [],
        primary_action: {
          id: status === "closed" ? "open_cash_flow_ladder" : "open_freshness",
          label: status === "closed" ? "Открыть денежную лестницу" : "Открыть актуальность",
          target: "internal_route",
        },
        secondary_actions:
          status === "closed"
            ? [
                {
                  id: "clone_next_month",
                  label: "Создать следующий месяц",
                  target: "internal_route",
                },
              ]
            : [],
        completion_basis: null,
        evidence_scope: "none",
        evidence_version: null,
        evidence_summary: {},
        stale: { is_stale: false, reason_codes: [] },
        diagnostics: {},
      },
    ],
    readiness: { can_close: true, hard_blocker_count: 0, warning_count: 0, reason_codes: [] },
    freshness: {
      available: true,
      evaluated_on: "2026-09-01",
      quote_valuation_target_date: "2025-04-30",
      families: [],
      reason_codes: [],
    },
    final_review: { available: false, reason_code: "final_review_not_in_core" },
    outlook:
      status === "closed"
        ? {
            available: true,
            reason_code: null,
            source_month: month,
            next_month: {
              year: 2025,
              month: 5,
              known_event_count: outlookMode === "known" ? 1 : 0,
              has_known_events: outlookMode === "known",
              passive_income: outlookMode === "known" ? money("1234.56") : null,
              redemption_principal: outlookMode === "known" ? money("5000.00") : null,
              total_cash_flow: outlookMode === "known" ? money("6234.56") : null,
              deposit_interest_estimate: null,
              items: [],
            },
            upcoming_14_days: {
              days: 14,
              from_date: "2025-05-01",
              to_date: "2025-05-14",
              passive_income: money("0.00"),
              redemption_principal: money("0.00"),
              total_cash_flow: money("0.00"),
              items: [],
            },
            upcoming_30_days: null,
            known_event_count: outlookMode === "known" ? 1 : 0,
            evidence_version: "outlook-test-v1",
          }
        : null,
    links: { month: `/months/${monthId}`, close_readiness: "", freshness: "" },
  };
}

function providerWorkflow(): MonthCloseWorkflow {
  const base = workflow(17);
  const alfaStep = {
    ...base.steps[0],
    id: "alfa_baseline" as const,
    order: 2,
    title: "Сверить состав портфеля Alfa",
    primary_action: {
      id: "open_alfa_preview" as const,
      label: "Получить данные Alfa PRO",
      target: "open_panel" as const,
    },
    evidence_summary: { available: false, reason_code: "baseline_not_applied" },
  };
  const reconciliationStep = {
    ...base.steps[0],
    id: "broker_reconciliation" as const,
    order: 6,
    title: "Проверить портфель после обновлений",
    primary_action: {
      id: "open_reconciliation_preview" as const,
      label: "Проверить снимок Alfa",
      target: "open_panel" as const,
    },
    evidence_summary: { available: false, reason_code: "reconciliation_not_run" },
  };
  return {
    ...base,
    recommended_step_id: "alfa_baseline",
    steps: [alfaStep, reconciliationStep],
  };
}

function readyForCloseWorkflow(monthId: number): MonthCloseWorkflow {
  const base = workflow(monthId);
  return {
    ...base,
    recommended_step_id: "final_review_close",
    steps: [
      {
        ...base.steps[0],
        id: "final_review_close",
        order: 8,
        title: "Подтвердить закрытие",
        primary_action: {
          id: "confirm_close",
          label: "Закрыть месяц",
          target: "confirm_close",
        },
      },
    ],
  };
}

function wizardWorkflowWithFinalReview(monthId: number): MonthCloseWorkflow {
  const base = workflow(monthId);
  return {
    ...base,
    steps: [
      base.steps[0],
      {
        ...base.steps[0],
        id: "final_review_close",
        order: 8,
        title: "Проверить итог и закрыть месяц",
        primary_action: {
          id: "confirm_close",
          label: "Закрыть месяц",
          target: "confirm_close",
        },
      },
    ],
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function renderRoute(entry: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/months/:monthId/close" element={<MonthlyCloseWorkflowPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("MonthlyCloseWorkflowPage", () => {
  it("keeps an old requested month and exposes exactly one primary CTA", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(workflow(17)))));
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/months/17/close");

    expect(await screen.findByRole("heading", { name: /Апрель.*2025/ })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/17/close-workflow",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getAllByRole("link", { name: "Открыть актуальность" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Открыть актуальность" })).toHaveAttribute(
      "href",
      "/freshness?from=monthly-close&step=readiness&monthId=17",
    );
  });

  it("keeps provider checks explicit and explains their transient wizard evidence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(providerWorkflow())))),
    );
    renderRoute("/months/17/close");

    expect(await screen.findByRole("heading", { name: /Апрель.*2025/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Получить данные Alfa PRO" })).toHaveAttribute(
      "href",
      "/accounts?from=monthly-close&step=alfa_baseline&monthId=17",
    );
    expect(screen.getAllByText("Только по запросу").length).toBeGreaterThan(0);
    expect(screen.getByText(/После перезапуска.*нужно запросить снова/)).toBeInTheDocument();
    expect(screen.getAllByText("Состояние рассчитано системой.").length).toBeGreaterThan(0);
  });

  it("honours the final-review hash and exposes the close CTA", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(wizardWorkflowWithFinalReview(17))))),
    );
    renderRoute("/months/17/close#final_review_close");

    expect(await screen.findByRole("button", { name: "Закрыть месяц" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Проверить итог и закрыть месяц" })).toBeInTheDocument();
  });

  it("renders a closed month from the same month-scoped route", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(workflow(8, "closed"))))),
    );
    renderRoute("/months/8/close");
    expect(await screen.findByText("Утверждён")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть денежную лестницу" })).toHaveAttribute(
      "href",
      "/payouts?from=monthly-close&step=next_month_outlook&monthId=8",
    );
    expect(screen.getByRole("link", { name: "Создать следующий месяц" })).toHaveAttribute(
      "href",
      "/months?from=monthly-close&step=next_month_outlook&monthId=8",
    );
    expect(screen.getByText("Пассивный доход").parentElement).toHaveTextContent(/1.234,56/);
    expect(screen.getByText("Погашение · возврат капитала").parentElement).toHaveTextContent(
      /5.000/,
    );
    expect(screen.getByText("outlook-test-v1")).toBeInTheDocument();
  });

  it("does not turn an outlook with no known events into measured zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(workflow(9, "closed", "none"))))),
    );
    renderRoute("/months/9/close");

    expect(await screen.findByText("Утверждён")).toBeInTheDocument();
    expect(screen.getAllByText("Нет известных событий").length).toBeGreaterThan(0);
    expect(screen.queryByText(formatMoney("0.00"))).not.toBeInTheDocument();
  });

  it("refetches before confirmation, closes explicitly, and renders persisted outlook state", async () => {
    const draft = readyForCloseWorkflow(17);
    const closed = workflow(17, "closed");
    let closedPersisted = false;
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        closedPersisted = true;
        return Promise.resolve(jsonResponse(closed.month));
      }
      return Promise.resolve(jsonResponse(closedPersisted ? closed : draft));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/months/17/close");

    const closeButton = await screen.findByRole("button", { name: "Закрыть месяц" });
    fireEvent.click(closeButton);
    expect(await screen.findByRole("alertdialog", { name: "Закрыть месяц?" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/months/17/close",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(screen.getByText("Утверждён")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/17/close",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("refetches before reopening and derives the draft workflow again", async () => {
    const closed = workflow(18, "closed");
    const draft = workflow(18);
    let reopened = false;
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        reopened = true;
        return Promise.resolve(jsonResponse(draft.month));
      }
      return Promise.resolve(jsonResponse(reopened ? draft : closed));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/months/18/close");

    fireEvent.click(await screen.findByRole("button", { name: "Открыть месяц заново" }));
    expect(
      await screen.findByRole("alertdialog", { name: "Открыть месяц заново?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть заново" }));

    await waitFor(() => expect(screen.getByText("Черновик")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/months/18/reopen",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("fails deterministically for a missing month", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ error: { code: "not_found", message: "missing" } }), {
            status: 404,
          }),
        ),
      ),
    );
    renderRoute("/months/999/close");
    expect(await screen.findByRole("alert")).toHaveTextContent("Месяц не найден");
  });

  it("refetches workflow when the window regains focus", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(workflow(4)))));
    vi.stubGlobal("fetch", fetchMock);
    renderRoute("/months/4/close");
    await screen.findByRole("heading", { name: /Апрель.*2025/ });
    fireEvent.focus(window);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
