import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listMonths } from "../api/months";
import { downloadScenarioLabExport, evaluateScenarioLab } from "../api/scenarioLab";
import UiV2ScenarioLabPage from "./UiV2ScenarioLabPage";

vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/scenarioLab", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/scenarioLab")>();
  return {
    ...original,
    evaluateScenarioLab: vi.fn(),
    downloadScenarioLabExport: vi.fn(),
  };
});
vi.mock("../pages/ScenarioLabPage", async (importOriginal) => {
  const original = await importOriginal<typeof import("../pages/ScenarioLabPage")>();
  return {
    ...original,
    ScenarioLabResult: ({ evaluation }: { evaluation: unknown }) => (
      <output data-testid="evaluation">{JSON.stringify(evaluation)}</output>
    ),
  };
});

const may = {
  id: 1,
  year: 2030,
  month: 5,
  status: "closed" as const,
  snapshot_date: "2030-05-12",
  source: "manual",
};
const june = {
  id: 2,
  year: 2030,
  month: 6,
  status: "draft" as const,
  snapshot_date: "2030-06-12",
  source: "manual",
};

function evaluation(
  shockType: string,
  month: typeof may | typeof june = may,
  extra: Record<string, unknown> = {},
) {
  return {
    reporting_month: month,
    normalized_shock_input: { shock_type: shockType },
    base: { liquid_assets: "0.00" },
    stressed: { liquid_assets: null },
    impact: { liquid_assets_delta: null },
    metric_support: { liquid_assets: { status: "unknown", reason_codes: ["missing_currency"] } },
    coverage: { applied: 0, unknown: 1 },
    assumptions: ["no_provider_network"],
    ...extra,
  };
}

function BackControl() {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate(-1)} type="button">
      Назад в истории
    </button>
  );
}

function renderPage(initial = "/v2/income/scenario-lab") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <BackControl />
      <Routes>
        <Route path="/v2/income/scenario-lab" element={<UiV2ScenarioLabPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function ready() {
  return screen.findByRole("combobox", { name: "Отчётный месяц" });
}

describe("native Scenario Lab", () => {
  beforeEach(() => {
    vi.mocked(listMonths).mockResolvedValue([june, may]);
    vi.mocked(evaluateScenarioLab).mockReset();
    vi.mocked(downloadScenarioLabExport).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("runs only on explicit action, for each of the four exact scenario inputs", async () => {
    const user = userEvent.setup();
    vi.mocked(evaluateScenarioLab).mockImplementation(
      async (month, shock) => evaluation(Object.keys(shock)[0], month === 2 ? june : may) as never,
    );
    renderPage("/v2/income/scenario-lab?month=2");
    expect(await ready()).toHaveValue("2");
    expect(evaluateScenarioLab).not.toHaveBeenCalled();

    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "0");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await screen.findByTestId("evaluation");
    expect(evaluateScenarioLab).toHaveBeenLastCalledWith(
      2,
      { equity_drawdown: { drawdown_pct: "0" } },
      expect.any(AbortSignal),
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Сценарий" }),
      "deposit_rate_assumption",
    );
    expect(screen.queryByTestId("evaluation")).not.toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: "Гипотетическая годовая ставка по вкладам, %" }),
      "8,5",
    );
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await screen.findByTestId("evaluation");
    expect(evaluateScenarioLab).toHaveBeenLastCalledWith(
      2,
      { deposit_rate_assumption: { assumed_annual_rate_pct: "8.5", all_eligible_deposits: true } },
      expect.any(AbortSignal),
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Сценарий" }),
      "inflation_real_value",
    );
    await user.type(screen.getByRole("textbox", { name: "Годовая инфляция, %" }), "12");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await screen.findByTestId("evaluation");
    expect(evaluateScenarioLab).toHaveBeenLastCalledWith(
      2,
      { inflation_real_value: { annual_inflation_pct: "12" } },
      expect.any(AbortSignal),
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Сценарий" }),
      "fx_translation_shock",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Изменение стоимости в отчёте, %" }),
      "-10",
    );
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await screen.findByTestId("evaluation");
    expect(evaluateScenarioLab).toHaveBeenLastCalledWith(
      2,
      { fx_translation_shock: { target_currency: "USD", reporting_value_change_pct: "-10" } },
      expect.any(AbortSignal),
    );
    expect(evaluateScenarioLab).toHaveBeenCalledTimes(4);
  });

  it("keeps an invalid explicit month invalid and rejects invalid inputs", async () => {
    const user = userEvent.setup();
    renderPage("/v2/income/scenario-lab?month=bogus");
    expect(await ready()).toHaveValue("");
    expect(screen.getByRole("alert")).toHaveTextContent("недействителен");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "Отчётный месяц" }), "1");
    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "101");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeDisabled();
    await user.clear(screen.getByRole("textbox", { name: "Размер просадки акций, %" }));
    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "10");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Назад в истории" }));
    expect(await ready()).toHaveValue("");
    expect(evaluateScenarioLab).not.toHaveBeenCalled();
  });

  it("preserves server zero, null, support and partial coverage without recalculation", async () => {
    const user = userEvent.setup();
    const response = evaluation("equity_drawdown", may, {
      warnings: ["partial coverage"],
      metric_support: {
        liquid_assets: {
          status: "unavailable",
          reason_codes: ["fx_translation_basis_unavailable"],
        },
      },
    });
    vi.mocked(evaluateScenarioLab).mockResolvedValue(response as never);
    renderPage("/v2/income/scenario-lab?month=1");
    await ready();
    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "0");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    const shown = await screen.findByTestId("evaluation");
    expect(JSON.parse(shown.textContent ?? "")).toEqual(response);
  });

  it("invalidates on input and month changes and ignores a late response", async () => {
    const user = userEvent.setup();
    let resolveOld!: (value: never) => void;
    vi.mocked(evaluateScenarioLab).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
    );
    renderPage("/v2/income/scenario-lab?month=1");
    await ready();
    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Отчётный месяц" }), "2");
    resolveOld(evaluation("equity_drawdown") as never);
    await waitFor(() => expect(screen.queryByTestId("evaluation")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });

  it("exports exactly the calculated month/input and suppresses a late export after invalidation", async () => {
    const user = userEvent.setup();
    vi.mocked(evaluateScenarioLab).mockResolvedValue(evaluation("equity_drawdown") as never);
    let resolveExport!: (value: never) => void;
    vi.mocked(downloadScenarioLabExport).mockReturnValue(
      new Promise((resolve) => {
        resolveExport = resolve;
      }),
    );
    const createObjectURL = vi.fn(() => "blob:scenario");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    renderPage("/v2/income/scenario-lab?month=1");
    await ready();
    await user.type(screen.getByRole("textbox", { name: "Размер просадки акций, %" }), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    await screen.findByTestId("evaluation");
    await user.click(screen.getByRole("button", { name: "Скачать JSON" }));
    expect(downloadScenarioLabExport).toHaveBeenCalledWith(1, {
      equity_drawdown: { drawdown_pct: "10" },
    });
    await user.clear(screen.getByRole("textbox", { name: "Размер просадки акций, %" }));
    resolveExport({ blob: new Blob(["{}"]), filename: "scenario.json" } as never);
    await waitFor(() => expect(createObjectURL).not.toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });
});
