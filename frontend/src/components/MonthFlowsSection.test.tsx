import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthFlowsSection } from "./MonthFlowsSection";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = {
  id: 11,
  name: "Synthetic Broker",
  account_type: "brokerage",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

const instrument = {
  id: 21,
  name: "Synthetic Bond",
  instrument_type: "bond",
  isin: null,
  ticker: "SYNB",
  moex_secid: null,
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const mergedCalendar = [
  {
    year: 2031,
    month: 6,
    coupon: { amount: "0.00", currency: "RUB" },
    dividend: { amount: "0.00", currency: "RUB" },
    interest: { amount: "0.00", currency: "RUB" },
    redemption: { amount: "10000.00", currency: "RUB" },
    other: { amount: "0.00", currency: "RUB" },
    passive_net: { amount: "0.00", currency: "RUB" },
    total_net: { amount: "10000.00", currency: "RUB" },
    items: [
      {
        source_kind: "provider",
        source_id: 90,
        expected_date: "2031-06-15",
        flow_type: "redemption",
        account_id: 11,
        account_name: "Synthetic Broker",
        instrument_id: 21,
        instrument_name: "Synthetic Bond",
        expected_net_amount: { amount: "10000.00", currency: "RUB" },
        is_confirmed: null,
        is_approximate: false,
        manual_source: null,
        provider: "t_invest",
        provider_instrument_uid: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        provider_identity_key: "mty:1",
        provider_lifecycle: "active",
        reconciliation_id: null,
        counting_decision: null,
        linked_manual_id: null,
        linked_provider_payout_id: 90,
      },
    ],
  },
];

const manualFlow = {
  id: 41,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  flow_type: "coupon",
  event_date: "2031-01-15",
  gross_amount: { amount: "1000.00", currency: "RUB" },
  tax_amount: { amount: "130.00", currency: "RUB" },
  commission_amount: { amount: "10.00", currency: "RUB" },
  net_amount: { amount: "860.00", currency: "RUB" },
  currency: "RUB",
  source: "manual",
  notes: null,
};

const importedFlow = {
  ...manualFlow,
  id: 42,
  event_date: "2031-01-20",
  source: "alfa_depository_income_report",
  statement_link: {
    applied_statement_event_id: 9,
    link_mode: "statement_created",
    status: "active",
  },
};

const linkedExistingFlow = {
  ...manualFlow,
  id: 43,
  event_date: "2031-01-22",
  source: "manual",
  statement_link: {
    applied_statement_event_id: 10,
    link_mode: "linked_existing",
    status: "active",
  },
};

function setup({
  calendar = [] as unknown[] | null,
  flows = [] as unknown[],
  readOnly = false,
  retractStatus = 200,
  retractCode = "already_retracted",
}: {
  calendar?: unknown[] | null;
  flows?: unknown[];
  readOnly?: boolean;
  retractStatus?: number;
  retractCode?: string;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (method === "GET" && url === "/api/accounts") return jsonResponse([account]);
    if (method === "GET" && url === "/api/instruments?active=true")
      return jsonResponse([instrument]);
    if (method === "GET" && url === "/api/investment-flows?month_id=7") return jsonResponse(flows);
    if (method === "GET" && url === "/api/expected-flows?month_id=7&forecast_version=v1") {
      return jsonResponse([]);
    }
    if (method === "GET" && url === "/api/payouts/calendar?month_id=7&forecast_version=v1") {
      return calendar === null
        ? jsonResponse(
            { error: { code: "calendar_error", message: "calendar unavailable", details: [] } },
            503,
          )
        : jsonResponse(calendar);
    }
    if (method === "POST" && url === "/api/investment-flows") {
      return jsonResponse({ id: 31 }, 201);
    }
    if (method === "PATCH" && url === "/api/investment-flows/41") {
      return jsonResponse({ ...manualFlow, net_amount: { amount: "870.00", currency: "RUB" } });
    }
    if (method === "POST" && url === "/api/statement-import/applied-events/9/retract") {
      return retractStatus === 200
        ? jsonResponse({
            applied_statement_event_id: 9,
            link_mode: "statement_created",
            cash_flow_deleted: true,
            investment_cash_flow_id: null,
            revision_id: 12,
          })
        : jsonResponse(
            {
              error: {
                code: retractCode,
                message: "applied statement event is already retracted",
                details: [],
              },
            },
            retractStatus,
          );
    }
    if (method === "POST" && url === "/api/statement-import/applied-events/10/retract") {
      return jsonResponse({
        applied_statement_event_id: 10,
        link_mode: "linked_existing",
        cash_flow_deleted: false,
        investment_cash_flow_id: 43,
        revision_id: 13,
      });
    }

    return jsonResponse(
      { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
      404,
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  render(<MonthFlowsSection defaultDate="2031-01-31" monthId={7} readOnly={readOnly} />);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthFlowsSection actual-flow instrument", () => {
  it("starts empty and resets to empty after an actual flow is created", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();

    const instrumentSelect = await screen.findByLabelText("Инструмент (необязательно)");
    expect(instrumentSelect).toHaveValue("");

    await user.selectOptions(instrumentSelect, "21");
    await user.type(screen.getByLabelText("Брутто"), "1000");
    await user.type(screen.getByLabelText("Нетто"), "1000");
    await user.click(screen.getByRole("button", { name: "Добавить выплату" }));

    await waitFor(() => expect(instrumentSelect).toHaveValue(""));

    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/investment-flows" && init?.method === "POST",
    );
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      flow_type: "coupon",
    });
  });

  it("uses the merged payout calendar and exposes provider provenance", async () => {
    const fetchMock = setup({ calendar: mergedCalendar });

    expect(await screen.findByText("T-Invest")).toBeInTheDocument();
    expect(screen.getByText("возврат капитала, не доход")).toBeInTheDocument();
    expect(screen.getByText(/весь денежный поток/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([input]) => String(input) === "/api/payouts/calendar?month_id=7&forecast_version=v1",
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/api/expected-flows/calendar"),
      ),
    ).toBe(false);
  });

  it("keeps manual flow CRUD usable when only the merged calendar read fails", async () => {
    setup({ calendar: null });

    expect(await screen.findByText("Фактические потоки")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить выплату" })).toBeInTheDocument();
    expect(screen.getByText(/Календарь временно недоступен/)).toBeInTheDocument();
    expect(screen.getByText(/calendar unavailable/)).toBeInTheDocument();
  });

  it("keeps the actual payout date and income accent class on the row", async () => {
    setup({ flows: [manualFlow] });
    const table = await screen.findByRole("table");
    const incomeRow = table.querySelector("tr.row--income");
    expect(incomeRow).not.toBeNull();
    expect(incomeRow?.querySelector(".month-flows-table__date")).toHaveTextContent("15.01.2031");
    expect(table).toHaveTextContent("15.01.2031");
  });

  it("opens overflow edit for a manual payout and patches current values", async () => {
    const fetchMock = setup({ flows: [manualFlow] });
    const user = userEvent.setup();
    const table = await screen.findByRole("table");

    expect(within(table).queryByRole("button", { name: "Удал." })).toBeNull();
    await user.click(
      within(table).getByRole("button", {
        name: "Действия для выплаты «Купон» от 2031-01-15",
      }),
    );
    const editItem = screen.getByRole("menuitem", { name: "Изменить" });
    const deleteItem = screen.getByRole("menuitem", { name: "Удалить" });
    expect(editItem).toBeEnabled();
    expect(deleteItem).toHaveClass("overflow-menu__item--danger");
    await user.click(editItem);

    expect(screen.getByDisplayValue("1000.00")).toBeInTheDocument();
    expect(screen.getByDisplayValue("860.00")).toBeInTheDocument();
    const net = screen.getByDisplayValue("860.00");
    await user.clear(net);
    await user.type(net, "870.00");
    await user.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/investment-flows/41" && init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        flow_type: "coupon",
        event_date: "2031-01-15",
        net_amount: { amount: "870.00", currency: "RUB" },
      });
      expect(JSON.parse(String(patch?.[1]?.body))).not.toHaveProperty("source");
    });
  });

  it("keeps imported statement payouts protected from edit", async () => {
    setup({ flows: [importedFlow] });
    const user = userEvent.setup();
    const table = await screen.findByRole("table");

    expect(table).toHaveTextContent("Выписка Альфа-Банка");
    expect(table).toHaveTextContent("не редактируется");
    await user.click(
      within(table).getByRole("button", {
        name: "Действия для выплаты «Купон» от 2031-01-20",
      }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.queryByRole("menuitem", { name: "Удалить" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Отменить импорт" })).toBeEnabled();
  });

  it("confirms statement-created retract with row evidence and refreshes", async () => {
    const fetchMock = setup({ flows: [importedFlow] });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-20" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Отменить импорт" }));

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Отменить импорт?");
    expect(dialog).toHaveTextContent("Synthetic Broker");
    expect(dialog).toHaveTextContent("Synthetic Bond");
    expect(dialog).toHaveTextContent("Нетто: 860 ₽");
    expect(dialog).toHaveTextContent("2031-01-20");
    await user.click(within(dialog).getByRole("button", { name: "Отменить импорт" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input) === "/api/statement-import/applied-events/9/retract" &&
            init?.method === "POST",
        ),
      ).toBe(true);
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(
          ([input, init]) =>
            String(input) === "/api/investment-flows?month_id=7" &&
            (init?.method ?? "GET") === "GET",
        ).length,
      ).toBeGreaterThan(1);
    });
  });

  it("shows a typed backend retract error", async () => {
    setup({ flows: [importedFlow], retractStatus: 409, retractCode: "already_retracted" });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-20" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Отменить импорт" }));
    await user.click(screen.getByRole("button", { name: "Отменить импорт" }));
    expect(
      await screen.findByText("Эта строка выписки уже отменена. Обнови список выплат."),
    ).toBeInTheDocument();
  });

  it("offers unlink for a linked-existing statement row", async () => {
    setup({ flows: [linkedExistingFlow] });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-22" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.queryByRole("menuitem", { name: "Удалить" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Отвязать выписку" })).toBeEnabled();
    await user.click(screen.getByRole("menuitem", { name: "Отвязать выписку" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Отвязать выписку?");
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Сама выплата останется");
  });

  it("disables payout mutations in a closed month", async () => {
    setup({ flows: [manualFlow], readOnly: true });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-15" }),
    );
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Добавить выплату" })).not.toBeInTheDocument();
  });

  it("disables statement retract in a closed month", async () => {
    setup({ flows: [importedFlow], readOnly: true });
    const user = userEvent.setup();
    await screen.findByRole("table");
    await user.click(
      screen.getByRole("button", { name: "Действия для выплаты «Купон» от 2031-01-20" }),
    );
    expect(screen.getByRole("menuitem", { name: "Отменить импорт" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Добавить выплату" })).not.toBeInTheDocument();
  });
});
