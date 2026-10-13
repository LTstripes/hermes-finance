import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getDashboard } from "../api/dashboard";
import { listGoalSummary } from "../api/goals";
import { closeMonth, getCloseReadiness, reopenMonth } from "../api/months";
import type { CloseReadiness, DashboardKpis } from "../api/types";
import { MonthReviewSection } from "./MonthReviewSection";

vi.mock("../api/dashboard", () => ({ getDashboard: vi.fn() }));
vi.mock("../api/goals", () => ({ listGoalSummary: vi.fn() }));
vi.mock("../api/months", () => ({
  closeMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
  reopenMonth: vi.fn(),
}));

const kpis: DashboardKpis = {
  liquid_capital_net: { amount: "1000000.00", currency: "RUB" },
  liquid_capital_delta: null,
  passive_income_actual: { amount: "12000.00", currency: "RUB" },
  passive_income_delta: null,
  forecast_monthly_passive_income: { amount: "15000.00", currency: "RUB" },
  forecast_annual_passive_income: { amount: "180000.00", currency: "RUB" },
  passive_income_average: { amount: "12000.00", currency: "RUB" },
  passive_income_average_months: 6,
  passive_income_average_complete: false,
  goal_progress_pct: "42.5",
  goal_target: { amount: "100000.00", currency: "RUB" },
  mandatory_expenses: { amount: "50000.00", currency: "RUB" },
  mandatory_expense_coverage_pct: "40.0",
  actual_mandatory_expense_coverage_pct: "24.0",
  mortgage_balance: { amount: "0.00", currency: "RUB" },
  mortgage_coverage_pct: null,
};

const dashboard = {
  month: {
    id: 7,
    year: 2026,
    month: 7,
    status: "draft" as const,
    snapshot_date: "2026-07-31",
    source: "manual",
  },
  kpis,
  mortgage: {
    mortgage_balance: { amount: "0.00", currency: "RUB" },
    coverage_pct: null,
    gap: { amount: "0.00", currency: "RUB" },
  },
  warnings: ["Среднее доступно по части истории"],
  calculation_version: "1.0",
};

const ready: CloseReadiness = {
  year: 2026,
  month: 7,
  status: "draft",
  snapshot_date: "2026-07-31",
  source: "manual",
  can_close: true,
  items: [
    {
      severity: "info",
      code: "backup_none",
      message: "Резервных копий пока нет.",
      context: {},
    },
  ],
};

const getDashboardMock = vi.mocked(getDashboard);
const listGoalSummaryMock = vi.mocked(listGoalSummary);
const closeMonthMock = vi.mocked(closeMonth);
const getCloseReadinessMock = vi.mocked(getCloseReadiness);
const reopenMonthMock = vi.mocked(reopenMonth);

beforeEach(() => {
  vi.clearAllMocks();
  getDashboardMock.mockResolvedValue(dashboard);
  listGoalSummaryMock.mockResolvedValue([]);
  getCloseReadinessMock.mockResolvedValue(ready);
  closeMonthMock.mockResolvedValue({ ...dashboard.month, status: "closed" });
  reopenMonthMock.mockResolvedValue({ ...dashboard.month, status: "draft" });
});

describe("MonthReviewSection", () => {
  it("shows distinct broker source headings and preserves all expanded evidence", async () => {
    const reasons = [
      ["4_Transfers_unsupported", "Переводы требуют сверки"],
      ["5_UFSR_unsupported", "Данные UFSR не поддерживаются"],
      ["commission_basis_unresolved", "Учёт комиссии не подтверждён"],
      ["money_semantics_unsupported", "Денежные операции не разобраны"],
      ["settlement_principal_unresolved", "Основная сумма расчётов не подтверждена"],
      ["unparsed_source_rows", "Есть неразобранные строки отчёта"],
    ];
    const items = reasons.map(([code], index) => ({
      severity: "hard_blocker" as const,
      code,
      message: `MyBroker счёт #${index + 1}: исходные доказательства требуют сверки.`,
      context: { count: index + 1, coverage_state: "unknown", bookkeeping_ready: false },
    }));
    getCloseReadinessMock.mockResolvedValue({ ...ready, can_close: false, items });
    const onReadinessSummaryChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          onReadinessSummaryChange={onReadinessSummaryChange}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    const blockers = await screen.findByRole("region", { name: "Блокирует закрытие" });
    expect(within(blockers).getAllByRole("listitem")).toHaveLength(6);
    for (const [index, [, title]] of reasons.entries()) {
      const row = within(blockers).getByText(title).closest("li");
      expect(row).not.toBeNull();
      if (!row) throw new Error("Missing blocker row");
      const details = row.querySelector("details");
      expect(details).not.toHaveAttribute("open");
      await user.click(within(row).getByText("Подробности"));
      expect(details).toHaveAttribute("open");
      expect(row.querySelector("pre")?.textContent).toBe(
        `Код: ${items[index].code}\nСерверное сообщение: ${items[index].message}\nКонтекст: ${JSON.stringify(items[index].context, null, 2)}`,
      );
    }
    expect(onReadinessSummaryChange).toHaveBeenLastCalledWith({
      blockerCount: 6,
      warningCount: 0,
      infoCount: 0,
    });
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("keeps mixed, repeated and unknown source reasons in their server severity groups", async () => {
    const items = [
      {
        severity: "hard_blocker" as const,
        code: "money_semantics_unsupported",
        message: "Источник A",
        context: { count: 2 },
      },
      {
        severity: "hard_blocker" as const,
        code: "money_semantics_unsupported",
        message: "Источник B",
        context: { count: 3 },
      },
      {
        severity: "hard_blocker" as const,
        code: "new_source_reason",
        message: "Новый источник C",
        context: { count: null },
      },
      {
        severity: "hard_blocker" as const,
        code: "constructor",
        message: "Неизвестный код D",
        context: { coverage_state: "unknown" },
      },
      {
        severity: "warning" as const,
        code: "new_source_warning",
        message: "Предупреждение E",
        context: {},
      },
      { severity: "info" as const, code: "new_source_context", message: "Контекст F", context: {} },
    ];
    getCloseReadinessMock.mockResolvedValue({ ...ready, can_close: false, items });
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    const blockers = await screen.findByRole("region", { name: "Блокирует закрытие" });
    expect(within(blockers).getAllByRole("listitem")).toHaveLength(4);
    expect(within(blockers).getAllByText("Денежные операции не разобраны")).toHaveLength(2);
    expect(within(blockers).getAllByText("Нужно исправить перед закрытием")).toHaveLength(2);
    for (const item of items) {
      const diagnostic = screen.getByText(
        (_, element) =>
          element?.tagName === "PRE" && element.textContent?.includes(item.message) === true,
      );
      expect(diagnostic.textContent).toBe(
        `Код: ${item.code}\nСерверное сообщение: ${item.message}\nКонтекст: ${Object.keys(item.context).length ? JSON.stringify(item.context, null, 2) : "нет"}`,
      );
    }
    expect(
      within(screen.getByRole("region", { name: "Стоит проверить" })).getAllByRole("listitem"),
    ).toHaveLength(1);
    expect(
      within(screen.getByRole("region", { name: "Контекст" })).getAllByRole("listitem"),
    ).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("shows portfolio coverage beside the known preview subtotal", async () => {
    getDashboardMock.mockResolvedValue({
      ...dashboard,
      kpis: {
        ...kpis,
        portfolio_source_coverage: {
          status: "partial",
          reason_codes: ["active_account_snapshot_missing"],
          missing_account_ids: [2],
        },
      },
    });
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Частично: нет снимка счёта")).toBeVisible();
    expect(screen.getByText("1 000 000 ₽")).toBeVisible();
  });

  it("renders three readiness groups and closes a draft after confirmation", async () => {
    const user = userEvent.setup();
    const onStatusChanged = vi.fn();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={onStatusChanged}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Проверка месяца" })).toBeInTheDocument();
    expect(screen.getByTestId("close-cockpit")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Блокирует закрытие" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Стоит проверить" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Контекст" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть цели →" })).toHaveAttribute("href", "/goals");
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Закрыть месяц" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Закрыть" }));

    expect(closeMonthMock).toHaveBeenCalledWith(7);
    expect(onStatusChanged).toHaveBeenCalledOnce();
  });

  it("keeps close enabled when backend only returns warnings", async () => {
    getCloseReadinessMock.mockResolvedValue({
      ...ready,
      items: [
        {
          severity: "warning",
          code: "salary_tax_history_incomplete",
          message: "История зарплатного НДФЛ неполная. Это не блокирует закрытие.",
          context: { tax_year: 2026 },
        },
        {
          severity: "warning",
          code: "quote_stale",
          message: "Есть применённые котировки старше окна актуальности.",
          context: { family_id: "market_quotes" },
        },
      ],
    });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    expect(await screen.findByText("История зарплатного НДФЛ неполная")).toBeInTheDocument();
    expect(screen.getByText("Есть устаревшие котировки")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Закрыть месяц" }));
    expect(screen.getByText(/предупреждения, но они не блокируют закрытие/i)).toBeInTheDocument();
    expect(closeMonthMock).not.toHaveBeenCalled();
  });

  it("disables close only when backend can_close is false", async () => {
    getCloseReadinessMock.mockResolvedValue({
      ...ready,
      can_close: false,
      items: [
        {
          severity: "hard_blocker",
          code: "snapshot_date_required",
          message: "snapshot_date is required before closing a reporting month",
          context: {},
        },
      ],
    });
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Дата снимка не задана")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
  });

  it("hides close for a closed month and keeps reopen enabled", async () => {
    getCloseReadinessMock.mockResolvedValue({
      ...ready,
      status: "closed",
      can_close: true,
      items: [
        {
          severity: "info",
          code: "month_already_closed",
          message: "Месяц уже закрыт. Повторное закрытие не предлагается.",
          context: { status: "closed" },
        },
      ],
    });
    const user = userEvent.setup();
    const onStatusChanged = vi.fn();
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={onStatusChanged}
          readOnly
          status="closed"
        />
      </MemoryRouter>,
    );

    const reopen = await screen.findByRole("button", { name: "Открыть заново" });
    expect(screen.queryByRole("button", { name: "Закрыть месяц" })).toBeNull();
    expect(screen.getByText("Месяц уже закрыт")).toBeInTheDocument();
    expect(reopen).toBeEnabled();
    await user.click(reopen);
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Открыть заново" }));

    expect(reopenMonthMock).toHaveBeenCalledWith(7);
    expect(onStatusChanged).toHaveBeenCalledOnce();
  });

  it("shows existing dashboard warnings without blocking close", async () => {
    render(
      <MemoryRouter>
        <MonthReviewSection
          dirty={false}
          monthId={7}
          onStatusChanged={vi.fn()}
          readOnly={false}
          status="draft"
        />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Расчётные уведомления" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Среднее доступно по части истории")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-calculation-notices")).toHaveTextContent(
      "Среднее доступно по части истории",
    );
    expect(
      within(screen.getByTestId("close-cockpit")).queryByText("Среднее доступно по части истории"),
    ).toBeNull();
    expect(screen.getByRole("heading", { name: "Блокирует закрытие" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Стоит проверить" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Контекст" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть месяц" })).toBeEnabled();
  });
});
