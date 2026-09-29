import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listMonths } from "../api/months";
import {
  getRiskAllocation,
  type RiskAllocationResponse,
  type RiskConcentrationMetric,
} from "../api/riskAllocation";
import type { ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import UiV2CapitalAllocationPage from "./UiV2CapitalAllocationPage";

vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/riskAllocation", () => ({ getRiskAllocation: vi.fn() }));

const cash = (amount: string) => ({ amount, currency: "RUB" });
const supported = { status: "supported" as const, reason_codes: [] };
const months: ReportingMonth[] = [
  { id: 2, year: 2031, month: 2, status: "draft", snapshot_date: "2031-02-28", source: "manual" },
  { id: 1, year: 2031, month: 1, status: "closed", snapshot_date: "2031-01-31", source: "manual" },
];

function concentration(overrides: Partial<RiskConcentrationMetric> = {}): RiskConcentrationMetric {
  return {
    support: supported,
    denominator: cash("100000.00"),
    top_n: 5,
    top_amount: cash("80000.00"),
    top_share_pct: "80.00",
    items: [
      {
        key: "position:1",
        label: "Счёт А / Облигация",
        amount: cash("80000.00"),
        share_pct: "80.00",
        account_id: 1,
        account_name: "Счёт А",
        instrument_id: 1,
        instrument_name: "Облигация",
        instrument_type: "bond",
        position_id: 1,
        event_count: null,
        is_approximate: false,
      },
    ],
    excluded: [],
    is_approximate: false,
    ...overrides,
  };
}

function response(monthId = 2): RiskAllocationResponse {
  return {
    reporting_month_id: monthId,
    as_of_date: months.find((month) => month.id === monthId)?.snapshot_date ?? "2031-02-28",
    base_currency: "RUB",
    liquid_assets_total: cash("100000.00"),
    allocation_by_asset_class: {
      support: { status: "unknown", reason_codes: ["instrument_type_not_authoritative"] },
      denominator: cash("100000.00"),
      covered_amount: cash("80000.00"),
      unallocated_amount: cash("20000.00"),
      coverage_pct: "80.00",
      items: [
        {
          key: "bond",
          label: "bond",
          amount: cash("80000.00"),
          share_pct: "80.00",
          account_id: null,
          instrument_id: null,
          instrument_type: "bond",
        },
        {
          key: "unknown_asset_class",
          label: "Unknown asset class",
          amount: cash("20000.00"),
          share_pct: "20.00",
          account_id: null,
          instrument_id: null,
          instrument_type: null,
        },
      ],
      excluded: [
        {
          source_kind: "position",
          source_id: 2,
          status: "unknown",
          reason_codes: ["instrument_type_not_authoritative"],
        },
      ],
    },
    allocation_by_account: {
      support: supported,
      denominator: cash("100000.00"),
      covered_amount: cash("100000.00"),
      unallocated_amount: cash("0.00"),
      coverage_pct: "100.00",
      items: [
        {
          key: "account:1",
          label: "Счёт А",
          amount: cash("80000.00"),
          share_pct: "80.00",
          account_id: 1,
          instrument_id: null,
          instrument_type: null,
        },
        {
          key: "account:2",
          label: "Счёт Б",
          amount: cash("20000.00"),
          share_pct: "20.00",
          account_id: 2,
          instrument_id: null,
          instrument_type: null,
        },
      ],
      excluded: [],
    },
    top_positions: concentration(),
    payout_concentration: concentration({
      denominator: cash("1200.00"),
      top_amount: cash("900.00"),
      top_share_pct: "75.00",
      items: [
        {
          ...concentration().items[0],
          key: "payout:1",
          label: "Купон",
          amount: cash("900.00"),
          share_pct: "75.00",
          event_count: 2,
          is_approximate: true,
        },
      ],
      is_approximate: true,
    }),
    redemption_concentration: concentration({
      denominator: cash("5000.00"),
      top_amount: cash("5000.00"),
      top_share_pct: "100.00",
      items: [
        {
          ...concentration().items[0],
          key: "redemption:1",
          label: "Погашение облигации",
          amount: cash("5000.00"),
          share_pct: "100.00",
          event_count: 1,
        },
      ],
    }),
    support: {
      asset_class: supported,
      account: supported,
      top_positions: supported,
      payout: supported,
      redemption: supported,
      issuer: { status: "unavailable", reason_codes: ["issuer_not_persisted"] },
      currency: { status: "unknown", reason_codes: ["currency_not_persisted"] },
      maturity: { status: "unavailable", reason_codes: ["maturity_not_persisted"] },
      broker: { status: "unavailable", reason_codes: ["broker_identity_not_persisted"] },
      bank: { status: "unavailable", reason_codes: ["bank_identity_not_persisted"] },
    },
  };
}

function Navigation() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <output data-testid="location">{`${location.pathname}${location.search}`}</output>
      <button onClick={() => navigate(-1)} type="button">
        Back
      </button>
    </>
  );
}

function setup(path = "/v2/capital/allocation") {
  const client = createQueryClient();
  const mounted = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Navigation />
        <Routes>
          <Route path="v2/capital/allocation" element={<UiV2CapitalAllocationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...mounted };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listMonths).mockResolvedValue(months);
  vi.mocked(getRiskAllocation).mockImplementation(async (id) => response(id));
});

afterEach(() => cleanup());

describe("UiV2CapitalAllocationPage", () => {
  it("uses canonical amounts and separate denominators, with partial and top-N limits", async () => {
    const user = userEvent.setup();
    setup();
    expect(await screen.findByText(/Ликвидные активы/)).toBeInTheDocument();
    expect(getRiskAllocation).toHaveBeenCalledWith(2, 5, "v1", expect.any(AbortSignal));
    await user.click(screen.getByText("По классам активов", { selector: "span" }));
    const classes = screen.getByRole("table", { name: "По классам активов" });
    expect(within(classes).getByText("Облигации")).toBeInTheDocument();
    expect(within(classes).getByText("Неизвестный класс активов")).toBeInTheDocument();
    const classDetails = classes.closest("details") as HTMLElement;
    expect(
      within(classDetails).getByText(/Покрытие известных групп ниже 100%/),
    ).toBeInTheDocument();
    expect(within(classDetails).getByText(/Доступность данных: неизвестно/)).toBeInTheDocument();
    expect(
      within(classDetails).getByText(/уже показана строкой «Неизвестный класс активов»/),
    ).toBeInTheDocument();
    expect(within(classDetails).getByText(/Распределено по известным группам/)).toBeInTheDocument();
    expect(within(classes).getByText(/20\s*000\s*₽/)).toBeInTheDocument();
    expect(
      within(classDetails).getByText(/Не отнесено к известным группам · в составе основы/),
    ).toBeInTheDocument();
    await user.click(screen.getByText("По счетам", { selector: "span" }));
    const accounts = screen.getByRole("table", { name: "По счетам" });
    expect(within(accounts).getByText("Счёт А")).toBeInTheDocument();
    expect(within(accounts).getByText("Счёт Б")).toBeInTheDocument();
    await user.click(screen.getByText("Выплаты", { selector: "span" }));
    expect(screen.getByText("Основа долей · включённые выплаты")).toBeInTheDocument();
    expect(screen.getAllByText(/1\s*200\s*₽/).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Погашение основного долга не является пассивным доходом/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Топ не означает полный охват/).length).toBeGreaterThan(0);
    await user.click(screen.getByText("Крупнейшие позиции", { selector: "span" }));
    expect(screen.getByRole("table", { name: "Крупнейшие позиции" })).toBeInTheDocument();
    await user.click(screen.getByText("Погашения", { selector: "span" }));
    expect(
      within(screen.getByRole("table", { name: "Погашения" })).getByText("Погашение облигации"),
    ).toBeInTheDocument();
    await user.click(screen.getByText("Остальные измерения и ограничения"));
    expect(screen.getByText(/API сообщает доступность этих измерений/)).toBeInTheDocument();
    expect(screen.getByText("эмитент не указан")).toBeInTheDocument();
  });

  it("keeps explicit zero separate from null and unavailable event data", async () => {
    const user = userEvent.setup();
    const empty = response();
    empty.payout_concentration = concentration({
      denominator: cash("0.00"),
      top_amount: cash("0.00"),
      top_share_pct: null,
      items: [],
    });
    empty.redemption_concentration = concentration({
      support: { status: "unavailable", reason_codes: ["deposit_forecast_not_concentratable"] },
      denominator: cash("0.00"),
      top_amount: cash("0.00"),
      top_share_pct: null,
      items: [],
    });
    vi.mocked(getRiskAllocation).mockResolvedValue(empty);
    setup();
    await screen.findByText("Выплаты", { selector: "span" });
    await user.click(screen.getByText("Выплаты", { selector: "span" }));
    const payouts = screen.getByText("Выплаты", { selector: "span" }).closest("details");
    expect(payouts).not.toBeNull();
    expect(
      within(payouts as HTMLElement).getByText("Нет датированных событий в окне."),
    ).toBeInTheDocument();
    expect(within(payouts as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(within(payouts as HTMLElement).getAllByText(/0\s*₽/).length).toBeGreaterThan(0);
    await user.click(screen.getByText("Погашения", { selector: "span" }));
    expect(screen.getByText("Срез недоступен или покрытие не подтверждено.")).toBeInTheDocument();
  });

  it("calls the portfolio empty only for confirmed explicit zero, and marks a missing slice", async () => {
    const user = userEvent.setup();
    const empty = response();
    empty.liquid_assets_total = cash("0.00");
    empty.allocation_by_asset_class = {
      ...empty.allocation_by_asset_class,
      support: supported,
      denominator: cash("0.00"),
      covered_amount: cash("0.00"),
      unallocated_amount: cash("0.00"),
      coverage_pct: null,
      items: [],
      excluded: [],
    };
    empty.allocation_by_account = { ...empty.allocation_by_asset_class };
    empty.top_positions = concentration({
      denominator: cash("0.00"),
      top_amount: cash("0.00"),
      top_share_pct: null,
      items: [],
    });
    vi.mocked(getRiskAllocation).mockResolvedValue(empty);
    const mounted = setup();
    expect(await screen.findByText("Портфель пуст")).toBeInTheDocument();
    await user.click(screen.getByText("По классам активов", { selector: "span" }));
    const zeroDetails = screen
      .getByText("По классам активов", { selector: "span" })
      .closest("details") as HTMLElement;
    expect(
      within(zeroDetails).getByText(/нулевая основа, доля не определяется/),
    ).toBeInTheDocument();
    expect(
      within(zeroDetails).getByText("При нулевой основе процент покрытия не определяется."),
    ).toBeInTheDocument();
    expect(
      within(zeroDetails).queryByText(
        /Покрытие известных групп ниже 100%|API не определил долю покрытия|Доступность данных:/,
      ),
    ).toBeNull();
    mounted.unmount();
    vi.mocked(getRiskAllocation).mockResolvedValue({
      ...empty,
      allocation_by_asset_class: undefined,
    } as unknown as RiskAllocationResponse);
    setup();
    expect(await screen.findByText("По классам активов: нет ответа")).toBeInTheDocument();
    expect(screen.queryByText("Портфель пуст")).toBeNull();
  });

  it("shows unassigned cash within account rows and distinguishes unavailable support", async () => {
    const user = userEvent.setup();
    const data = response();
    data.allocation_by_account = {
      ...data.allocation_by_account,
      support: { status: "unavailable", reason_codes: ["cash_not_account_linked"] },
      covered_amount: cash("80000.00"),
      unallocated_amount: cash("20000.00"),
      coverage_pct: "80.00",
      items: [
        data.allocation_by_account.items[0],
        {
          key: "unassigned_cash",
          label: "Unassigned cash",
          amount: cash("20000.00"),
          share_pct: "20.00",
          account_id: null,
          instrument_id: null,
          instrument_type: null,
        },
      ],
    };
    vi.mocked(getRiskAllocation).mockResolvedValue(data);
    setup();
    await screen.findByText("По счетам", { selector: "span" });
    await user.click(screen.getByText("По счетам", { selector: "span" }));
    const accounts = screen.getByRole("table", { name: "По счетам" });
    const accountDetails = accounts.closest("details") as HTMLElement;
    expect(within(accounts).getByText("Наличные без привязки к счёту")).toBeInTheDocument();
    expect(within(accounts).getByText(/20\s*000\s*₽/)).toBeInTheDocument();
    expect(
      within(accountDetails).getByText(/уже показана строкой «Наличные без привязки к счёту»/),
    ).toBeInTheDocument();
    expect(
      within(accountDetails).getByText(/Покрытие известных групп ниже 100%/),
    ).toBeInTheDocument();
    expect(within(accountDetails).getByText(/Доступность данных: недоступно/)).toBeInTheDocument();
    expect(within(accountDetails).queryByText(/Строки не равны всему портфелю/)).toBeNull();
  });

  it.each(["month=bad", "month=999", "month=2&month=1", "month=0"])(
    "rejects invalid explicit %s without a risk request",
    async (search) => {
      setup(`/v2/capital/allocation?${search}`);
      expect(await screen.findByText("Месяц не найден")).toBeInTheDocument();
      expect(getRiskAllocation).not.toHaveBeenCalled();
    },
  );

  it("switches month in URL and Back without showing prior data as current", async () => {
    const user = userEvent.setup();
    let release: (() => void) | undefined;
    vi.mocked(getRiskAllocation).mockImplementation(async (id) => {
      if (id === 1)
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      return response(id);
    });
    setup();
    await screen.findByText("Крупнейшие позиции", { selector: "span" });
    await user.selectOptions(screen.getByLabelText("Отчётный месяц"), "1");
    expect(screen.getByTestId("location")).toHaveTextContent("month=1");
    expect(screen.getByText("Проверяем распределение выбранного месяца…")).toBeInTheDocument();
    release?.();
    await screen.findByText("По классам активов", { selector: "span" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/v2/capital/allocation"),
    );
    expect(await screen.findByLabelText("Отчётный месяц")).toHaveValue("2");
  });

  it("hides a mismatched response and distinguishes loading, error and empty months", async () => {
    vi.mocked(getRiskAllocation).mockResolvedValue({ ...response(), as_of_date: "2031-02-27" });
    const mounted = setup();
    expect(await screen.findByText("Ответ не совпал со снимком")).toBeInTheDocument();
    mounted.unmount();
    vi.mocked(listMonths).mockRejectedValue(new Error("Synthetic failure"));
    setup();
    expect(await screen.findByText("Не удалось загрузить месяцы")).toBeInTheDocument();
  });

  it("supports keyboard focus and opening of detail summaries", async () => {
    setup();
    await screen.findByText("По классам активов", { selector: "span" });
    const summary = screen.getByText("По классам активов", { selector: "span" }).closest("summary");
    expect(summary).not.toBeNull();
    (summary as HTMLElement).focus();
    expect(summary).toHaveFocus();
    fireEvent.keyDown(summary as HTMLElement, { key: "Enter" });
    fireEvent.click(summary as HTMLElement);
    expect(screen.getByRole("table", { name: "По классам активов" })).toBeInTheDocument();
  });
});
