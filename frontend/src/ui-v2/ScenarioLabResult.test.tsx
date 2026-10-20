import type { ScenarioLabEvaluation } from "../api/scenarioLab";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  MONTH_MAY,
  equityEnvelope,
  fxEnvelope,
  fxEmptyScopeEnvelope,
  fxUnknownEnvelope,
} from "../test/scenarioLabFixtures";
import { ScenarioLabResult } from "./ScenarioLabResult";

describe("ScenarioLabResult", () => {
  it("FX unavailable state is prominent and never rendered as an exact zero-impact success", async () => {
    const envelope = fxEnvelope();
    render(
      <ScenarioLabResult
        evaluation={envelope as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );

    // Explicit limitation callout, machine reason code survives into the UI.
    expect(screen.getByText("Недоступен точный пересчёт")).toBeInTheDocument();
    expect(screen.getAllByText("fx_translation_basis_unavailable").length).toBeGreaterThan(0);
    // The other two FX states must not leak into an unavailable result.
    expect(screen.queryByText("Нет данных для точного пересчёта")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет позиций в валюте шока")).not.toBeInTheDocument();
    // Candidate scope is explicit, not a success.
    expect(screen.getByText(/Кандидаты \(валюта совпадает\):/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Недоступно$/).length).toBeGreaterThan(0);
    // Numeric base is shown without an implied stressed revaluation.
    expect(screen.getByText("точный стресс-пересчёт недоступен")).toBeInTheDocument();
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);
    // No fabricated “impact” numbers for an unavailable aggregate.
    expect(screen.queryByText(/Известный скоуп · влияние/)).not.toBeInTheDocument();
    // Row-level candidate status explains the limitation.
    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Кандидаты и доступность пересчёта" })
      .closest("section");
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Кандидат · пересчёт недоступен"))).toBe(
      true,
    );
    expect(rows.some((row) => row.textContent?.includes("Акция США"))).toBe(true);
  });

  it("FX empty affected scope renders a supported zero no-op without the unavailable callout", async () => {
    const envelope = fxEmptyScopeEnvelope();
    render(
      <ScenarioLabResult
        evaluation={envelope as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );

    // No unavailable/unknown limitation: the affected scope is empty and supported.
    expect(screen.queryByText("Недоступен точный пересчёт")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет данных для точного пересчёта")).not.toBeInTheDocument();
    expect(screen.queryByText("fx_translation_basis_unavailable")).not.toBeInTheDocument();
    // Explicit no-matching-candidates no-op message naming the target currency.
    expect(screen.getByText("Нет позиций в валюте шока")).toBeInTheDocument();
    expect(screen.getByText(/выбранной валютой USD/)).toBeInTheDocument();
    // Supported zero result stays visible: calculated badges, base money, known-scope impact.
    expect(screen.getAllByText(/^Рассчитано$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Известный скоуп · влияние/)).toBeInTheDocument();
    expect(screen.queryByText("точный стресс-пересчёт недоступен")).not.toBeInTheDocument();
  });

  it("FX unknown currency metadata renders an unknown limitation, not zero certainty", async () => {
    const envelope = fxUnknownEnvelope();
    render(
      <ScenarioLabResult
        evaluation={envelope as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );

    // Unknown state is visible and distinct from both unavailable and empty-scope.
    expect(screen.queryByText("Недоступен точный пересчёт")).not.toBeInTheDocument();
    expect(screen.queryByText("Нет позиций в валюте шока")).not.toBeInTheDocument();
    expect(screen.getByText("Нет данных для точного пересчёта")).toBeInTheDocument();
    expect(screen.getAllByText("missing_currency").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^Неизвестно$/).length).toBeGreaterThan(0);
    // Empty-scope zero-certainty message must not appear for unknown data.
    expect(
      screen.queryByText(/точный эффект сценария для этого снимка — 0/),
    ).not.toBeInTheDocument();
  });

  it("renders server-stressed values and retries only on explicit action", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    render(
      <ScenarioLabResult
        evaluation={equityEnvelope() as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={retry}
      />,
    );
    expect(screen.getAllByText(/140\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/135\s*000/)).not.toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Пересчитать" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
