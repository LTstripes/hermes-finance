import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError } from "../api/client";
import { getHealth } from "../api/health";
import { getSettings, updateSettings } from "../api/settings";
import { getTaxBrackets, type TaxBracketYearConfig, updateTaxBrackets } from "../api/taxBrackets";
import UiV2DataAppPage from "../ui-v2/UiV2DataAppPage";

vi.mock("../api/health", () => ({ getHealth: vi.fn() }));
vi.mock("../api/settings", () => ({ getSettings: vi.fn(), updateSettings: vi.fn() }));
vi.mock("../api/taxBrackets", () => ({
  getTaxBrackets: vi.fn(),
  updateTaxBrackets: vi.fn(),
}));

const getHealthMock = vi.mocked(getHealth);
const getSettingsMock = vi.mocked(getSettings);
const updateSettingsMock = vi.mocked(updateSettings);
const getTaxBracketsMock = vi.mocked(getTaxBrackets);
const updateTaxBracketsMock = vi.mocked(updateTaxBrackets);

const settings = {
  base_currency: "RUB",
  locale: "ru-RU",
  timezone: "Europe/Moscow",
  passive_income_goal: { amount: "100000.00", currency: "RUB" },
  formula_version: "v1",
  passive_income_history_start_month: null,
};

function taxConfig(overrides: Partial<TaxBracketYearConfig> = {}): TaxBracketYearConfig {
  const year = new Date().getFullYear();
  return {
    year,
    effective_from: `${year}-01-01`,
    effective_to: `${year}-12-31`,
    source: "official_default",
    contract_version: "tax_brackets_year_v1",
    mutable: true,
    closed_months: [],
    brackets: [
      {
        threshold_from: { amount: "0.00", currency: "RUB" },
        threshold_to: { amount: "100000.00", currency: "RUB" },
        rate_bps: 1300,
      },
      {
        threshold_from: { amount: "100000.00", currency: "RUB" },
        threshold_to: null,
        rate_bps: 1500,
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/v2/data/app"]}>
      <Routes>
        <Route path="v2/data/app" element={<UiV2DataAppPage />} />
        <Route path="v2/income" element={<h1>Доход и планы</h1>} />
        <Route path="goals" element={<h1>Цели</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("UI v2 Data/App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getHealthMock.mockResolvedValue({ status: "ok", version: "0.9.0-dev" });
    getSettingsMock.mockResolvedValue(settings);
    updateSettingsMock.mockResolvedValue(settings);
    getTaxBracketsMock.mockResolvedValue(taxConfig());
    updateTaxBracketsMock.mockImplementation(async (_year, payload) =>
      taxConfig({
        source: "manual_configuration",
        brackets: payload.brackets,
      }),
    );
  });

  afterEach(() => {
    cleanup();
  });

  it("loads settings, tax metadata and local runtime diagnostics without a competing goal editor", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Приложение" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("ru-RU")).toBeInTheDocument();
    expect(await screen.findByText("Официальная шкала")).toBeInTheDocument();
    expect(await screen.findByText("0.9.0-dev")).toBeInTheDocument();
    expect(screen.getByText(/Цель пассивного дохода:.*100\s*000/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть «Доход и планы» →" })).toHaveAttribute(
      "href",
      "/v2/income",
    );
    expect(screen.getByRole("link", { name: "Цели в предыдущем интерфейсе ↗" })).toHaveAttribute(
      "href",
      "/goals",
    );
    expect(
      screen.getByText(/не редактируется в разделе «Данные и приложение»/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Российский рубль")).toBeInTheDocument();
    expect(screen.getAllByText("Только локально").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Только чтение").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Изменяет данные").length).toBeGreaterThanOrEqual(2);
  });

  it("sends only changed settings and can clear the history boundary", async () => {
    const user = userEvent.setup();
    updateSettingsMock.mockImplementation(async (payload) => ({
      ...settings,
      passive_income_history_start_month: payload.passive_income_history_start_month ?? null,
    }));
    renderPage();

    const boundary = await screen.findByLabelText("Учитывать пассивный доход начиная с");
    await user.type(boundary, "2031-05");
    await user.click(screen.getByRole("button", { name: "Сохранить настройки" }));

    await waitFor(() =>
      expect(updateSettingsMock).toHaveBeenCalledWith({
        passive_income_history_start_month: "2031-05",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    await user.click(screen.getByRole("button", { name: "Сохранить настройки" }));
    await waitFor(() =>
      expect(updateSettingsMock).toHaveBeenLastCalledWith({
        passive_income_history_start_month: null,
      }),
    );
  });

  it("blocks invalid settings before PUT", async () => {
    const user = userEvent.setup();
    renderPage();

    const locale = await screen.findByLabelText("Локаль");
    await user.clear(locale);
    await user.type(locale, "x");
    await user.click(screen.getByRole("button", { name: "Сохранить настройки" }));

    expect(screen.getByText(/от 2 до 32 символов/i)).toBeInTheDocument();
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("retries a failed settings read while leaving the other app sections available", async () => {
    const user = userEvent.setup();
    getSettingsMock.mockRejectedValueOnce(new Error("settings unavailable"));
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Не удалось загрузить настройки" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Официальная шкала")).toBeInTheDocument();
    getSettingsMock.mockResolvedValueOnce(settings);
    await user.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByDisplayValue("ru-RU")).toBeInTheDocument();
    expect(getSettingsMock).toHaveBeenCalledTimes(2);
  });

  it("keeps server field failures localized and does not claim a save", async () => {
    const user = userEvent.setup();
    updateSettingsMock.mockRejectedValue(
      new ApiClientError(422, {
        code: "unprocessable",
        message: "Request validation failed",
        details: [{ field: "timezone", message: "invalid timezone" }],
      }),
    );
    renderPage();

    const timezone = await screen.findByLabelText("Часовой пояс");
    await user.clear(timezone);
    await user.type(timezone, "UTC+3");
    await user.click(screen.getByRole("button", { name: "Сохранить настройки" }));

    expect(await screen.findByText("Некорректный часовой пояс.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Проверь введённые данные");
    expect(screen.queryByText("Настройки сохранены.")).toBeNull();
  });

  it("rejects a non-contiguous tax edit before the whole-set PUT", async () => {
    const user = userEvent.setup();
    renderPage();

    const upper = await screen.findByLabelText("Верхняя граница ступени 1");
    await user.clear(upper);
    await user.type(upper, "0");
    await user.click(screen.getByRole("button", { name: "Сохранить налоговые ступени" }));

    expect(screen.getByRole("alert")).toHaveTextContent("верхняя граница должна быть больше");
    expect(updateTaxBracketsMock).not.toHaveBeenCalled();
  });

  it("shows locked tax years as read-only and preserves runtime retry", async () => {
    const user = userEvent.setup();
    getTaxBracketsMock.mockResolvedValue(
      taxConfig({ mutable: false, closed_months: [`${new Date().getFullYear()}-01`] }),
    );
    getHealthMock.mockRejectedValueOnce(new Error("runtime unavailable"));
    renderPage();

    expect(await screen.findByText("Год зафиксирован")).toBeInTheDocument();
    expect(screen.getByLabelText("Ставка ступени 1")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Сохранить налоговые ступени" })).toBeNull();
    expect(await screen.findByText("Недоступно")).toBeInTheDocument();

    getHealthMock.mockResolvedValueOnce({ status: "ok", version: "0.9.0-retry" });
    await user.click(screen.getByRole("button", { name: "Проверить снова" }));
    expect(await screen.findByText("0.9.0-retry")).toBeInTheDocument();
  });

  it("retries a failed tax read without inventing a bracket state", async () => {
    const user = userEvent.setup();
    getTaxBracketsMock.mockRejectedValueOnce(new Error("tax service unavailable"));
    renderPage();

    expect(await screen.findByText("tax service unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Официальная шкала")).toBeNull();
    getTaxBracketsMock.mockResolvedValueOnce(taxConfig());
    await user.click(screen.getByRole("button", { name: "Открыть год" }));
    expect(await screen.findByText("Официальная шкала")).toBeInTheDocument();
  });

  it("keeps the Data/App subnav unambiguous without a fake report-month context", async () => {
    renderPage();

    const nav = await screen.findByRole("navigation", { name: /Разделы данных/ });
    expect(within(nav).getByRole("link", { name: "Приложение" })).toHaveAttribute(
      "href",
      "/v2/data/app",
    );
    expect(screen.queryByTestId("data-month-context")).toBeNull();
  });
});
