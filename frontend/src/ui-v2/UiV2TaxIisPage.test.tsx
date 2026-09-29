import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listMonths } from "../api/months";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { ReportingMonth, TaxIisPlanner } from "../api/types";
import UiV2TaxIisPage from "./UiV2TaxIisPage";
import { uiV2TaxIisPath } from "./taxIisRoute";

vi.mock("../api/months", () => ({
  listMonths: vi.fn(),
}));

vi.mock("../api/taxIisPlanner", () => ({
  getTaxIisPlanner: vi.fn(),
}));

const month: ReportingMonth = {
  id: 2,
  year: 2031,
  month: 2,
  status: "closed",
  snapshot_date: "2031-02-28",
  source: "manual",
};

const nextMonth: ReportingMonth = {
  id: 3,
  year: 2031,
  month: 3,
  status: "closed",
  snapshot_date: "2031-03-31",
  source: "manual",
};

const draftMonth: ReportingMonth = {
  id: 4,
  year: 2031,
  month: 4,
  status: "draft",
  snapshot_date: "2031-04-30",
  source: "manual",
};

const money = (amount: string) => ({ amount, currency: "RUB" });

function completePlanner(reportingMonth: ReportingMonth = month): TaxIisPlanner {
  return {
    contract_version: "tax_iis_planner_v1",
    tax_year: 2031,
    as_of: {
      reporting_month: reportingMonth,
      selection_reason: "requested",
    },
    salary_tax: {
      tax_year: 2031,
      history_complete: true,
      history_coverage: "complete",
      available: true,
      opening_context_available: false,
      taxable_gross_ytd: money("2500000.00"),
      current_marginal_bracket: {
        threshold_from: money("2400000.00"),
        threshold_to: money("5000000.00"),
        rate_bps: 1500,
      },
      current_marginal_rate_bps: 1500,
      next_threshold: money("5000000.00"),
      distance_to_next_threshold: money("1111111.00"),
      tax_bracket_source: "official_default",
      warning_codes: [],
    },
    iis_accounts: [
      {
        account_id: 7,
        account_name: "Synthetic IIS",
        iis_type: "type_a",
        opened_at: "2031-01-01",
        eligible_close_at: "2036-01-01",
        contributions_by_tax_year: [
          { tax_year: 2031, amount: money("400000.00"), is_target_reached: true },
        ],
        tax_benefits: {
          planned: money("60000.00"),
          submitted: money("50000.00"),
          received: money("40000.00"),
          rejected: money("10000.00"),
        },
      },
    ],
    warnings: [],
  };
}

function unavailablePlanner(): TaxIisPlanner {
  const planner = completePlanner();
  return {
    ...planner,
    salary_tax: {
      ...planner.salary_tax,
      history_complete: false,
      history_coverage: "unavailable",
      available: false,
      taxable_gross_ytd: null,
      current_marginal_bracket: null,
      current_marginal_rate_bps: null,
      next_threshold: null,
      distance_to_next_threshold: null,
      tax_bracket_source: null,
      warning_codes: ["salary_tax_history_incomplete", "tax_brackets_unavailable"],
    },
    warnings: ["salary_tax_history_incomplete", "tax_brackets_unavailable", "future_warning_code"],
  };
}

function LocationProbe() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <output data-testid="test-location">
      {location.pathname}
      {location.search}
      {`|${navigationType}`}
    </output>
  );
}

function renderTaxIisPage(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <Routes>
        <Route path="/v2/income/tax-iis" element={<UiV2TaxIisPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("UiV2TaxIisPage", () => {
  beforeEach(() => {
    vi.mocked(listMonths).mockClear();
    vi.mocked(getTaxIisPlanner).mockClear();
    vi.mocked(listMonths).mockResolvedValue([month, nextMonth, draftMonth]);
    vi.mocked(getTaxIisPlanner).mockResolvedValue(completePlanner());
  });

  it("renders backend tax thresholds, source, as-of, IIS contributions and separate benefit statuses", async () => {
    renderTaxIisPage("/v2/income/tax-iis?month=2");

    expect(await screen.findByRole("heading", { level: 1, name: "Налоги и ИИС" })).toBeVisible();
    expect(await screen.findByTestId("tax-iis-as-of")).toHaveTextContent(
      /Налоговый год 2031\s*Срез Февраль 2031 · Утверждён · снимок 28\.02\.2031/,
    );
    expect(screen.getByTestId("tax-iis-taxable-gross-ytd")).toHaveTextContent(/2\s500\s000/);
    expect(screen.getByTestId("tax-iis-marginal-rate")).toHaveTextContent("15%");
    expect(screen.getByTestId("tax-iis-marginal-bracket")).toHaveTextContent(
      /2\s400\s000.*5\s000\s000/,
    );
    expect(screen.getByTestId("tax-iis-next-threshold")).toHaveTextContent(/5\s000\s000/);
    expect(screen.getByTestId("tax-iis-threshold-distance")).toHaveTextContent(/1\s111\s111/);
    expect(screen.getByText("Источник шкалы: Официальная шкала")).toBeVisible();

    const account = screen.getByRole("article");
    expect(within(account).getByRole("heading", { name: "Synthetic IIS" })).toBeVisible();
    expect(within(account).getByRole("link", { name: /Изменить данные ИИС/ })).toHaveAttribute(
      "href",
      "/v2/data/catalogs?month=2&account=7",
    );
    expect(
      within(account).getByText(/Открыт 01\.01\.2031 · Закрытие доступно с 01\.01\.2036/),
    ).toBeVisible();
    expect(
      within(account).getByRole("row", { name: /2031.*400\s000.*Цель достигнута/ }),
    ).toBeVisible();
    for (const label of ["Запланировано", "Подано", "Получено", "Отклонено"]) {
      expect(within(account).getByText(label, { exact: true })).toBeVisible();
    }
    expect(within(account).getByText(/эти статусы не складываются/)).toBeVisible();
    expect(screen.getByRole("link", { name: "← Доход и планы" })).toHaveAttribute(
      "href",
      "/v2/income?month=2",
    );
    expect(getTaxIisPlanner).toHaveBeenCalledWith({ reportingMonthId: 2 }, expect.any(AbortSignal));
  });

  it("keeps unavailable tax values unavailable and explains known and unknown warning codes", async () => {
    vi.mocked(getTaxIisPlanner).mockResolvedValue(unavailablePlanner());
    renderTaxIisPage("/v2/income/tax-iis?month=2");

    expect(await screen.findAllByText(/История зарплатного НДФЛ неполна/)).toHaveLength(2);
    expect(screen.getByTestId("tax-iis-taxable-gross-ytd")).toHaveTextContent("Недоступно");
    expect(screen.getByTestId("tax-iis-marginal-rate")).toHaveTextContent("Недоступно");
    expect(screen.getByTestId("tax-iis-marginal-bracket")).toHaveTextContent("Недоступно");
    expect(screen.getByTestId("tax-iis-next-threshold")).toHaveTextContent("Недоступно");
    expect(screen.getByTestId("tax-iis-threshold-distance")).toHaveTextContent("Недоступно");
    expect(screen.getByText("Источник шкалы: Источник шкалы не указан")).toBeVisible();
    expect(screen.getByText(/История НДФЛ: Недоступна/)).toBeVisible();
    expect(screen.getByText("future_warning_code", { exact: true })).toBeVisible();
    expect(screen.queryAllByText(/1\s111\s111|2\s500\s000/)).toHaveLength(0);
    expect(screen.queryByText("0 ₽", { exact: true })).toBeNull();
    expect(screen.queryByText("0%", { exact: true })).toBeNull();
  });

  it("does not replace an invalid explicit month with the default or request a different context", async () => {
    renderTaxIisPage("/v2/income/tax-iis?month=not-a-month");

    expect(
      await screen.findByRole("heading", { name: "Некорректный отчётный месяц" }),
    ).toBeVisible();
    expect(await screen.findByLabelText("Отчётный месяц")).toHaveValue("");
    expect(screen.getByTestId("test-location")).toHaveTextContent(
      "/v2/income/tax-iis?month=not-a-month|POP",
    );
    expect(getTaxIisPlanner).not.toHaveBeenCalled();
  });

  it("defaults a missing month to the latest closed report with replace navigation", async () => {
    renderTaxIisPage("/v2/income/tax-iis");

    await screen.findByRole("heading", { name: "Synthetic IIS" });
    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent(
        "/v2/income/tax-iis?month=3|REPLACE",
      ),
    );
    expect(getTaxIisPlanner).toHaveBeenCalledTimes(1);
    expect(getTaxIisPlanner).toHaveBeenCalledWith({ reportingMonthId: 3 }, expect.any(AbortSignal));
  });

  it("updates the month query and request when the user selects another report", async () => {
    const user = userEvent.setup();
    renderTaxIisPage("/v2/income/tax-iis?month=2&origin=income");

    await screen.findByRole("heading", { name: "Synthetic IIS" });
    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "3");

    await waitFor(() =>
      expect(screen.getByTestId("test-location")).toHaveTextContent(
        "/v2/income/tax-iis?month=3&origin=income|PUSH",
      ),
    );
    await waitFor(() =>
      expect(getTaxIisPlanner).toHaveBeenLastCalledWith(
        { reportingMonthId: 3 },
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByRole("link", { name: "← Доход и планы" })).toHaveAttribute(
      "href",
      "/v2/income?month=3&origin=income",
    );
  });

  it("shows the backend as-of month when it differs from the requested month", async () => {
    vi.mocked(getTaxIisPlanner).mockResolvedValue(completePlanner(nextMonth));
    renderTaxIisPage("/v2/income/tax-iis?month=2");

    expect(
      await screen.findByRole("heading", { name: "Получен другой отчётный срез" }),
    ).toBeVisible();
    expect(screen.getByTestId("tax-iis-as-of")).toHaveTextContent("Срез Март 2031");
    expect(screen.getByTestId("tax-iis-as-of")).not.toHaveTextContent("Срез Февраль 2031");
  });

  it("preserves an explicit month in the income handoff and adds its default only when absent", () => {
    expect(uiV2TaxIisPath(new URLSearchParams("source=income"), 91)).toBe(
      "/v2/income/tax-iis?source=income&month=91",
    );
    expect(uiV2TaxIisPath(new URLSearchParams("month=not-a-month&step=tax"), 91)).toBe(
      "/v2/income/tax-iis?month=not-a-month&step=tax",
    );
  });
});
