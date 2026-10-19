import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScenarioLabPage } from "./ScenarioLabPage";
import {
  MONTHS,
  equityEnvelope,
  depositEnvelope,
  inflationEnvelope,
} from "../test/scenarioLabFixtures";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(code: string, message: string, status = 422): Response {
  return jsonResponse({ error: { code, message, details: [] } }, status);
}

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  const calls: string[] = [];
  const bodies: { url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    calls.push(key);
    if (init?.body != null) {
      bodies.push({ url: key, body: JSON.parse(String(init.body)) });
    }
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return apiError("not_found", `no mock for ${key}`, 404);
    }
    return handler(init);
  });
  return { fetchMock, calls, bodies };
}

const CALCULATE = "Рассчитать сценарий";

async function selectScenario(user: ReturnType<typeof userEvent.setup>, value: string) {
  await user.selectOptions(screen.getByLabelText("Сценарий"), value);
}

async function runEquity(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
  await user.click(screen.getByRole("button", { name: CALCULATE }));
}

describe("ScenarioLabPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders month + scenario controls and never auto-runs a scenario", async () => {
    const { fetchMock, calls } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Сценарии" })).toBeInTheDocument();
    expect(screen.getByLabelText("Отчётный месяц")).toBeInTheDocument();
    expect(screen.getByLabelText("Сценарий")).toBeInTheDocument();
    // Defaults: latest closed month + equity scenario, but no evaluation yet.
    expect(screen.getByLabelText("Отчётный месяц")).toHaveValue("1");
    expect(screen.getByLabelText("Размер просадки акций, %")).toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.includes("scenario-lab"))).toBe(false);
  });

  it("calculates equity on an explicit action with the canonical payload and renders server values", async () => {
    const user = userEvent.setup();
    const envelope = equityEnvelope();
    const { fetchMock, calls, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();
    expect(calls).toContain("POST /api/months/1/scenario-lab");
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
    ]);

    // Server-stressed value is rendered verbatim: 140 000 ₽, never a client-side
    // recompute of 150 000 × 0.9 = 135 000.
    expect(screen.getAllByText(/140\s*000\s*₽/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/135\s*000/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/150\s*000\s*₽/).length).toBeGreaterThan(0);

    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Детали по позициям" })
      .closest("section");
    expect(detailPanel).not.toBeNull();
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Сбер"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("ОФЗ"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("Учтено"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("Не применимо"))).toBe(true);
    // Copyable fingerprints are present but secondary.
    expect(screen.getByText("fp-sem-equity")).toBeInTheDocument();
  });

  it("deposit-rate payload targets all eligible deposits and renders forecast impact without touching principal", async () => {
    const user = userEvent.setup();
    const envelope = depositEnvelope();
    const { fetchMock, calls, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "deposit_rate_assumption");
    await user.type(screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %"), "8");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Ставка по вкладам/ }),
    ).toBeInTheDocument();
    expect(calls).toContain("POST /api/months/1/scenario-lab");
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: {
          shock: {
            deposit_rate_assumption: {
              assumed_annual_rate_pct: "8",
              all_eligible_deposits: true,
            },
          },
        },
      },
    ]);

    // Principal/capital is unchanged: liquid capital delta is a plain 0 with an
    // explicit note, while forecast interest rises (600 → 800 ₽/мес).
    expect(screen.getByText("тело вкладов не меняется")).toBeInTheDocument();
    expect(screen.getAllByText(/800\s*₽/).length).toBeGreaterThan(0);
    const detailPanel = screen
      .getByRole("heading", { level: 2, name: "Пересчёт прогнозных процентов" })
      .closest("section");
    const rows = within(detailPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => row.textContent?.includes("Вклад Альфа"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("8,0%"))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("6,0%"))).toBe(true);
    expect(rows.some((row) => /120\s*000\s*₽/.test(row.textContent ?? ""))).toBe(true);
  });

  it("inflation renders nominal vs real rows from the stressed month grid", async () => {
    const user = userEvent.setup();
    const envelope = inflationEnvelope();
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "inflation_real_value");
    await user.type(screen.getByLabelText("Годовая инфляция, %"), "12");
    await user.click(screen.getByRole("button", { name: CALCULATE }));

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /Май\s*2030\s*·\s*Инфляция и реальная стоимость/,
      }),
    ).toBeInTheDocument();
    expect(bodies[0].body).toEqual({
      shock: { inflation_real_value: { annual_inflation_pct: "12" } },
    });

    const gridPanel = screen
      .getByRole("heading", { level: 2, name: "Номинал против реальной стоимости" })
      .closest("section");
    const rows = within(gridPanel as HTMLElement).getAllByRole("row");
    expect(rows.some((row) => /Май\s*2030/.test(row.textContent ?? ""))).toBe(true);
    expect(rows.some((row) => /Апрель\s*2031/.test(row.textContent ?? ""))).toBe(true);
    expect(rows.some((row) => row.textContent?.includes("11 мес."))).toBe(true);
    // Real purchasing-power value comes from the server row (537.79 ₽) — never recomputed.
    expect(screen.getAllByText(/537,79\s*₽/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/600\s*₽/).length).toBeGreaterThan(0);
  });

  it("shows deterministic machine-readable validation errors", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () =>
        apiError("invalid_drawdown_pct", "drawdown_pct must be between 0 and 100"),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось выполнить запрос");
    expect(alert).toHaveTextContent("drawdown_pct must be between 0 and 100");
    expect(alert).toHaveTextContent("код: invalid_drawdown_pct");
  });

  it("switching scenario resets the incompatible previous result", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(equityEnvelope()),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();

    await selectScenario(user, "deposit_rate_assumption");
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    // Export is not offered for a result that no longer matches the controls.
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });

  it("changing the reporting month invalidates the visible prior result", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(equityEnvelope()),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    expect(
      await screen.findByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "2");
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
  });

  it("export calls /export with the same scenario payload and triggers the owner download", async () => {
    const user = userEvent.setup();
    const envelope = equityEnvelope();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const createObjectURL = vi.fn(() => "blob:scenario-lab");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const { fetchMock, bodies } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => jsonResponse(envelope),
      "POST /api/months/1/scenario-lab/export": () =>
        new Response(JSON.stringify(envelope), {
          status: 200,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition":
              'attachment; filename="scenario_lab_2030-05_equity_drawdown.json"',
          },
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await runEquity(user);
    const exportButton = await screen.findByRole("button", { name: "Скачать JSON" });
    expect(exportButton).toBeEnabled();
    await user.click(exportButton);

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(bodies).toEqual([
      {
        url: "POST /api/months/1/scenario-lab",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
      {
        url: "POST /api/months/1/scenario-lab/export",
        body: { shock: { equity_drawdown: { drawdown_pct: "10" } } },
      },
    ]);
    expect(anchorClick.mock.instances[0]).toHaveProperty(
      "download",
      "scenario_lab_2030-05_equity_drawdown.json",
    );
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:scenario-lab");
    expect(
      await screen.findByText(/Файл scenario_lab_2030-05_equity_drawdown\.json скачан/),
    ).toBeInTheDocument();
  });

  it("keeps the export action disabled until a matching result exists", async () => {
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    expect(screen.getByRole("button", { name: "Скачать JSON" })).toBeDisabled();
  });

  it("FX signed validation allows -10 and 150 (no positive cap, lower bound -100)", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "fx_translation_shock");
    const pctInput = screen.getByLabelText("Изменение стоимости в отчёте, %");
    const calcButton = screen.getByRole("button", { name: "Рассчитать сценарий" });
    expect(calcButton).toBeDisabled();
    await user.clear(pctInput);
    await user.type(pctInput, "-10");
    expect(calcButton).toBeEnabled();
    await user.clear(pctInput);
    await user.type(pctInput, "150");
    expect(calcButton).toBeEnabled();
    await user.clear(pctInput);
    await user.type(pctInput, "-101");
    expect(calcButton).toBeDisabled();
  });

  it("deposit and inflation accept large values without artificial 100 cap", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await selectScenario(user, "deposit_rate_assumption");
    const depositInput = screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %");
    await user.type(depositInput, "250");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();

    await selectScenario(user, "inflation_real_value");
    const inflationInput = screen.getByLabelText("Годовая инфляция, %");
    await user.type(inflationInput, "250");
    expect(screen.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();
  });

  it("does not publish stale result when reporting month changes during pending calculation", async () => {
    const user = userEvent.setup();
    let resolvePending: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolvePending = resolve;
    });
    const envelope = equityEnvelope();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => pending,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    // While pending, switch month to June (id 2).
    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "2");
    // Resolve the stale request for month 1 — must be ignored.
    resolvePending(jsonResponse(envelope));
    await new Promise((r) => setTimeout(r, 50));
    expect(
      screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
  });

  it("does not publish stale result when scenario or parameters change during pending calculation", async () => {
    const user = userEvent.setup();
    let resolvePending: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolvePending = resolve;
    });
    const envelope = equityEnvelope();
    const { fetchMock } = mockFetchRouter({
      "GET /api/months": () => jsonResponse(MONTHS),
      "POST /api/months/1/scenario-lab": () => pending,
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScenarioLabPage />);
    await screen.findByLabelText("Размер просадки акций, %");
    await user.type(screen.getByLabelText("Размер просадки акций, %"), "10");
    await user.click(screen.getByRole("button", { name: "Рассчитать сценарий" }));
    // Change scenario while pending — invalidates stale equity result.
    await selectScenario(user, "deposit_rate_assumption");
    resolvePending(jsonResponse(envelope));
    await new Promise((r) => setTimeout(r, 50));
    expect(
      screen.queryByRole("heading", { level: 2, name: /Май\s*2030\s*·\s*Падение акций/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Результат появится после нажатия «Рассчитать сценарий»/),
    ).toBeInTheDocument();
    // Deposit controls are visible, equity stale result is gone.
    expect(
      screen.getByLabelText("Гипотетическая годовая ставка по вкладам, %"),
    ).toBeInTheDocument();
  });
});
