import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "../api/client";
import { getSettings, updateSettings } from "../api/settings";
import { SettingsPage } from "./SettingsPage";

vi.mock("../api/settings", () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));

vi.mock("../components/TaxBracketsPanel", () => ({
  TaxBracketsPanel: () => <div>Налоговые ступени</div>,
}));

const settings = {
  base_currency: "RUB",
  locale: "ru-RU",
  timezone: "Europe/Moscow",
  passive_income_goal: { amount: "100000.00", currency: "RUB" },
  formula_version: "v1",
  passive_income_history_start_month: null,
};

const getSettingsMock = vi.mocked(getSettings);
const updateSettingsMock = vi.mocked(updateSettings);

function renderSettings() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSettingsMock.mockResolvedValue(settings);
    updateSettingsMock.mockResolvedValue(settings);
  });

  it("loads settings and keeps financial goal read-only", async () => {
    renderSettings();

    expect(screen.getByText("Настройки")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("ru-RU")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Europe/Moscow")).toBeInTheDocument();
    expect(screen.getByText("100000.00")).toBeInTheDocument();
    expect(screen.getByText(/основной целью и её параметрами/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть цели →" })).toHaveAttribute("href", "/goals");
    expect(screen.queryByDisplayValue("100000.00")).toBeNull();
    expect(screen.queryByText("v1")).toBeNull();
    expect(screen.getByText("Налоговые ступени")).toBeInTheDocument();
  });

  it("retries after a settings load error", async () => {
    const user = userEvent.setup();
    getSettingsMock.mockRejectedValueOnce(new Error("settings unavailable"));
    renderSettings();

    expect(await screen.findByText("settings unavailable")).toBeInTheDocument();
    getSettingsMock.mockResolvedValueOnce(settings);
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByDisplayValue("ru-RU")).toBeInTheDocument();
    expect(getSettingsMock).toHaveBeenCalledTimes(2);
  });

  it("sends only changed safe fields", async () => {
    const user = userEvent.setup();
    updateSettingsMock.mockResolvedValue({ ...settings, locale: "en-US" });
    renderSettings();

    const locale = await screen.findByLabelText("Локаль");
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();

    await user.clear(locale);
    await user.type(locale, "en-US");
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledWith({ locale: "en-US" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Настройки сохранены");
  });

  it("blocks invalid locale before PUT", async () => {
    const user = userEvent.setup();
    renderSettings();

    const locale = await screen.findByLabelText("Локаль");
    await user.clear(locale);
    await user.type(locale, "x");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(screen.getByText(/от 2 до 32 символов/i)).toBeInTheDocument();
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("saves and clears the passive-income history boundary explicitly", async () => {
    const user = userEvent.setup();
    updateSettingsMock.mockImplementation(async (payload) => ({
      ...settings,
      passive_income_history_start_month: payload.passive_income_history_start_month ?? null,
    }));
    renderSettings();

    const boundary = await screen.findByLabelText("Учитывать пассивный доход начиная с");
    await user.type(boundary, "2031-05");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(updateSettingsMock).toHaveBeenCalledWith({
        passive_income_history_start_month: "2031-05",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(boundary).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(updateSettingsMock).toHaveBeenLastCalledWith({
        passive_income_history_start_month: null,
      }),
    );
  });

  it("localizes D08 field validation errors from the server", async () => {
    const user = userEvent.setup();
    updateSettingsMock.mockRejectedValue(
      new ApiClientError(422, {
        code: "unprocessable",
        message: "Request validation failed",
        details: [{ field: "timezone", message: "invalid timezone" }],
      }),
    );
    renderSettings();

    const timezone = await screen.findByLabelText("Часовой пояс");
    await user.clear(timezone);
    await user.type(timezone, "UTC+3");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Некорректный часовой пояс.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Проверь введённые данные");
    expect(screen.getByRole("alert")).not.toHaveTextContent("invalid timezone");
  });
});
