import type { EquityEvaluation, ScenarioLabEvaluation } from "../api/scenarioLab";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  MONTH_MAY,
  equityEnvelope,
  fxEnvelope,
  fxEmptyScopeEnvelope,
  fxUnknownEnvelope,
  depositEnvelope,
  inflationEnvelope,
} from "../test/scenarioLabFixtures";
import { ScenarioLabResult } from "./ScenarioLabResult";

describe("ScenarioLabResult", () => {
  it("shows the server forecast pair for deposit rates and the dated flow pair for inflation", () => {
    const deposits = render(
      <ScenarioLabResult
        evaluation={depositEnvelope() as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );
    const answer = deposits.container.querySelector(".scenario-lab__answer") as HTMLElement;
    expect(within(answer).getByText(/600\s*₽/)).toBeVisible();
    expect(within(answer).getByText(/800\s*₽/)).toBeVisible();
    deposits.unmount();
    const inflation = inflationEnvelope();
    const view = render(
      <ScenarioLabResult
        evaluation={inflation as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );
    expect(view.container.querySelector(".scenario-lab__answer")).toHaveTextContent(
      "Будущие потоки",
    );
    expect(view.container.querySelector(".scenario-lab__more")).not.toHaveAttribute("open");
  });

  it("orders by the server change and expands all rows without deriving a change from valuations", async () => {
    const user = userEvent.setup();
    const evaluation = equityEnvelope() as unknown as EquityEvaluation;
    for (let id = 10; id < 16; id += 1) {
      evaluation.base.per_position[String(id)] = {
        ...evaluation.base.per_position["1"],
        market_value: "999999.99",
      };
      evaluation.stressed.per_position[String(id)] = {
        ...evaluation.stressed.per_position["1"],
        market_value: "1.01",
      };
      evaluation.impact.per_position[String(id)] = {
        applicability: "applied",
        delta: `-${id}.25`,
        delta_kopecks: -id * 100 - 25,
      };
    }
    render(
      <ScenarioLabResult
        evaluation={evaluation as unknown as ScenarioLabEvaluation}
        selectedMonth={MONTH_MAY}
        onRetry={vi.fn()}
      />,
    );
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    const count = Object.keys(evaluation.impact.per_position).length;
    await user.click(screen.getByRole("button", { name: `Показать все ${count}` }));
    expect(within(table).getAllByRole("row")).toHaveLength(count + 1);
    expect(within(table).getAllByText(/−15,25/)).toHaveLength(1);
    expect(within(table).queryByText(/998\s*999/)).not.toBeInTheDocument();
  });
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
    expect(screen.queryByText(/Изменение по известным позициям/)).not.toBeInTheDocument();
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
    expect(screen.getByText(/Изменение по известным позициям/)).toBeInTheDocument();
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
