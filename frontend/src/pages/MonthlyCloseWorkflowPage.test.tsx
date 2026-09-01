import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";

import type { MonthCloseWorkflow } from "../api/monthCloseWorkflow";
import { MonthlyCloseWorkflowPage } from "./MonthlyCloseWorkflowPage";

function workflow(monthId: number, status: "draft" | "closed" = "draft"): MonthCloseWorkflow {
  return {
    contract_version: "monthly_close_workflow_v1",
    generated_at: "2026-09-01T08:00:00Z",
    month: {
      id: monthId,
      year: 2025,
      month: 4,
      status,
      snapshot_date: "2025-04-30",
      source: "manual",
    },
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
        why: "Состояние рассчитано backend.",
        reason_codes: [],
        primary_action: {
          id: status === "closed" ? "open_cash_flow_ladder" : "open_freshness",
          label: status === "closed" ? "Открыть денежную лестницу" : "Открыть актуальность",
          target: "internal_route",
        },
        secondary_actions: [],
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
    outlook: status === "closed" ? { available: false, reason_code: "unavailable" } : null,
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
    expect(screen.getAllByText("Состояние рассчитано backend.").length).toBeGreaterThan(0);
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
