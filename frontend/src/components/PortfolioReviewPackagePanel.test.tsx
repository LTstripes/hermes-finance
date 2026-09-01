import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PortfolioReviewPackage } from "../api/portfolioReviewPackage";
import { PortfolioReviewPackagePanel } from "./PortfolioReviewPackagePanel";

const sectionIds = [
  "capital",
  "positions",
  "dynamics",
  "passive_income",
  "future_cash_flows",
  "freshness",
  "allocation",
  "context",
  "deterministic_insights",
] as const;

const packageFixture: PortfolioReviewPackage = {
  schema_name: "hermes.finance.portfolio_review_package",
  schema_version: "1.0.0",
  metadata: {
    generated_at: "2026-04-30T12:00:00+00:00",
    as_of_date: "2026-04-30",
    base_currency: "RUB",
    application: { name: "Hermes Finance", version: "0.7.0" },
    generation_mode: "read_only",
    source_contract_name: "hermes.finance.ai_analysis_bundle",
    source_contract_version: "1.0.0",
    calculation_versions: {},
    ordering_contract: "sections_and_arrays_are_sorted_as_defined_by_contract",
  },
  profile: "concise",
  scope: {
    reporting_period: { year: 2026, month: 4 },
    reporting_status: "closed",
    selection_reason: "latest_closed",
    history_start_period: { year: 2026, month: 1 },
    history_end_period: { year: 2026, month: 4 },
    missing_calendar_periods: [],
    requested_sections: sectionIds.slice(0, 6),
  },
  sections: Object.fromEntries(
    sectionIds.map((id, index) => [
      id,
      {
        status: index < 6 ? "included" : "omitted",
        reason_codes: index < 6 ? [] : ["profile_concise"],
        data: index < 6 ? (id === "positions" ? { items: [{ ref: "synthetic" }] } : {}) : null,
      },
    ]),
  ) as PortfolioReviewPackage["sections"],
  field_states: [],
  warnings: [],
};

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PortfolioReviewPackagePanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("prepares an explicit preview and shows included and omitted sections", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(packageFixture));
    vi.stubGlobal("fetch", fetchMock);

    render(<PortfolioReviewPackagePanel />);

    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Подготовить пакет для анализа" }));

    expect(await screen.findByLabelText("Предпросмотр пакета для анализа")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/export/portfolio-review-package?profile=concise",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getByText("Капитал")).toBeInTheDocument();
    expect(screen.getAllByText("Опущен профилем")).toHaveLength(3);
    expect(screen.getByText("1 позиций")).toBeInTheDocument();
  });

  it("downloads the selected profile as JSON after preview", async () => {
    const user = userEvent.setup();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:portfolio-review");
    const revokeObjectURL = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(packageFixture))
      .mockResolvedValueOnce(
        new Response('{"schema_name":"hermes.finance.portfolio_review_package"}\n', {
          status: 200,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="hermes-portfolio-review-2026-04-concise.json"',
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    render(<PortfolioReviewPackagePanel />);
    await user.click(screen.getByRole("button", { name: "Подготовить пакет для анализа" }));
    await user.click(await screen.findByRole("button", { name: "Скачать пакет JSON" }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/export/portfolio-review-package/json?profile=concise",
      expect.objectContaining({ method: "GET" }),
    );
    expect(anchorClick.mock.instances[0]).toHaveProperty(
      "download",
      "hermes-portfolio-review-2026-04-concise.json",
    );
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:portfolio-review");
  });
});
