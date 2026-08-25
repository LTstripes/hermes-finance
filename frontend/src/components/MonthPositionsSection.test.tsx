import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonthPositionsSection } from "./MonthPositionsSection";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetchRouter(
  handlers: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const handler = handlers[`${method} ${url}`] ?? handlers[url];
    if (!handler) {
      return jsonResponse(
        { error: { code: "not_found", message: `no mock for ${method} ${url}`, details: [] } },
        404,
      );
    }
    return handler(init);
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
  instrument_type: "stock",
  isin: null,
  ticker: "SYNB",
  moex_secid: null,
  currency: "RUB",
  nominal_value: null,
  is_active: true,
  manual_price_allowed: true,
  notes: null,
};

const position = {
  id: 31,
  reporting_month_id: 7,
  account_id: 11,
  instrument_id: 21,
  quantity: "10",
  average_cost_per_unit: { amount: "1000.00", currency: "RUB" },
  market_price_per_unit: { amount: "1100.00", currency: "RUB" },
  market_value: { amount: "11000.00", currency: "RUB" },
  cost_basis: { amount: "10000.00", currency: "RUB" },
  unrealized_result: { amount: "1000.00", currency: "RUB" },
  accrued_interest: null,
  price_source: "manual",
  price_date: "2031-01-31",
  notes: null,
  updated_at: "2031-01-31T00:00:00",
};

function setup(
  overrides: Record<string, (init?: RequestInit) => Promise<Response> | Response> = {},
  positions: unknown[] = [],
  instruments: unknown[] = [instrument],
  readOnly = false,
) {
  const fetchMock = mockFetchRouter({
    "GET /api/accounts": () => jsonResponse([account]),
    "GET /api/instruments?active=true": () => jsonResponse(instruments),
    "GET /api/positions?month_id=7": () => jsonResponse(positions),
    ...overrides,
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MonthPositionsSection defaultPriceDate="2031-01-31" monthId={7} readOnly={readOnly} />);
  return fetchMock;
}

async function openPositionMenu(
  user: ReturnType<typeof userEvent.setup>,
  instrumentName = "Synthetic Bond",
) {
  await user.click(screen.getByRole("button", { name: `Действия для позиции ${instrumentName}` }));
}

async function startPositionEdit(
  user: ReturnType<typeof userEvent.setup>,
  instrumentName = "Synthetic Bond",
) {
  await openPositionMenu(user, instrumentName);
  await user.click(screen.getByRole("menuitem", { name: "Изменить" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MonthPositionsSection G03 component contract", () => {
  it("submits a position form with backend money objects and no blank accrued interest", async () => {
    const fetchMock = setup({ "POST /api/positions": () => jsonResponse({ id: 31 }, 201) });
    const user = userEvent.setup();

    await screen.findByText("Позиции");
    await user.type(screen.getByLabelText("Количество"), "10");
    await user.type(screen.getByLabelText("Средняя цена приобретения"), "1000.00");
    await user.type(screen.getByLabelText("Рыночная цена"), "1100.00");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));

    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/positions" && init?.method === "POST",
    );
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      reporting_month_id: 7,
      account_id: 11,
      instrument_id: 21,
      quantity: "10",
      average_cost_per_unit: { amount: "1000.00", currency: "RUB" },
      market_price_per_unit: { amount: "1100.00", currency: "RUB" },
      price_source: "manual",
      price_date: "2031-01-31",
    });
  });

  it("renders a readable error state when positions cannot be loaded", async () => {
    setup({
      "GET /api/positions?month_id=7": () =>
        jsonResponse(
          { error: { code: "internal_error", message: "Positions API failed", details: [] } },
          500,
        ),
    });

    expect(await screen.findByText("Не удалось загрузить позиции")).toBeInTheDocument();
    expect(
      screen.getByText("Внутренняя ошибка приложения. Попробуй обновить данные."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Positions API failed")).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить позицию" })).not.toBeInTheDocument();
  });

  it("formats backend money values in the position table", async () => {
    setup({}, [position]);

    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent(/1\s000\s₽/);
    expect(table).toHaveTextContent(/1\s100\s₽/);
  });

  it("keeps the snapshot date quiet", async () => {
    setup({}, [position]);
    const table = await screen.findByRole("table");

    expect(table).not.toHaveTextContent("Оценка на");
    expect(table).not.toHaveTextContent("Источник: Вручную");
    expect(
      screen.getByRole("button", { name: "Детали оценки для Synthetic Bond" }),
    ).toBeInTheDocument();
  });

  it("keeps same-date manual source available through HelpTip in read-only presentation", async () => {
    setup({}, [{ ...position, price_source: "manual" }], [instrument], true);
    const user = userEvent.setup();
    const table = await screen.findByRole("table");

    expect(table).not.toHaveTextContent("Оценка на");
    expect(table).not.toHaveTextContent("Источник: Вручную");
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Детали оценки для Synthetic Bond" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Источник: Вручную");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Дата оценки: 31.01.2031");
    await openPositionMenu(user);
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
  });

  it("does not keep t_invest when the owner manually changes price", async () => {
    const tInvestPosition = { ...position, price_source: "t_invest" };
    const fetchMock = setup(
      {
        "PATCH /api/positions/31": () =>
          jsonResponse({ ...tInvestPosition, price_source: "manual" }),
      },
      [tInvestPosition],
    );
    const user = userEvent.setup();
    await screen.findByRole("table");
    await startPositionEdit(user);
    const priceInput = screen.getByDisplayValue("1100.00");
    await user.clear(priceInput);
    await user.type(priceInput, "1200");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/positions/31" && init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        market_price_per_unit: { amount: "1200.00", currency: "RUB" },
        price_source: "manual",
      });
    });
  });

  it("exposes differing price metadata through HelpTip", async () => {
    setup({}, [{ ...position, price_date: "2031-02-01", price_source: "moex" }]);
    const user = userEvent.setup();
    const table = await screen.findByRole("table");
    expect(table).not.toHaveTextContent("Оценка на 01.02.2031");
    expect(table).not.toHaveTextContent("Мосбиржа");
    await user.click(screen.getByRole("button", { name: "Детали оценки для Synthetic Bond" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Источник: Мосбиржа");
    expect(screen.getByRole("tooltip")).toHaveTextContent("Дата оценки: 01.02.2031");
  });

  it("keeps destructive position actions behind a confirmed overflow path", async () => {
    setup({}, [position]);
    const user = userEvent.setup();

    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
    await openPositionMenu(user);
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Удал." })).toBeNull();
  });

  it("opens edit from the overflow menu for the chosen row", async () => {
    const otherInstrument = { ...instrument, id: 22, name: "Other Stock", ticker: "OTH" };
    const otherPosition = {
      ...position,
      id: 32,
      instrument_id: 22,
      quantity: "8.000000",
    };
    setup({}, [position, otherPosition], [instrument, otherInstrument]);
    const user = userEvent.setup();

    await screen.findByRole("table");
    await startPositionEdit(user, "Other Stock");

    expect(screen.getByDisplayValue("8")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("8.000000")).toBeNull();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Действия для позиции Synthetic Bond" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Действия для позиции Other Stock" })).toBeNull();
  });

  it("exposes a dedicated inline-edit grid with readable Save/Cancel actions", async () => {
    setup({}, [position]);
    const user = userEvent.setup();
    await screen.findByRole("table");
    await startPositionEdit(user);

    const edit = document.querySelector(".position-inline-edit");
    expect(edit).toBeInstanceOf(HTMLElement);
    const editRoot = edit as HTMLElement;
    expect(within(editRoot).getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
    expect(within(editRoot).getByRole("button", { name: "Отмена" })).toBeInTheDocument();
    expect(within(editRoot).getByLabelText("Количество")).toHaveValue("10");
    expect(within(editRoot).getByLabelText("Средняя цена приобретения")).toHaveValue("1000.00");
    expect(within(editRoot).getByLabelText("Рыночная цена")).toHaveValue("1100.00");
    expect(within(editRoot).getByLabelText("Дата оценки")).toHaveValue("2031-01-31");
    expect(within(editRoot).getByLabelText("Источник оценки")).toHaveValue("manual");
    expect(editRoot.closest("td")).toHaveAttribute("colspan", "8");
    expect(editRoot.closest("td")).not.toHaveClass("month-positions-table__actions");

    await user.click(within(editRoot).getByRole("button", { name: "Отмена" }));
    expect(document.querySelector(".position-inline-edit")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Действия для позиции Synthetic Bond" }),
    ).toBeInTheDocument();
  });

  it("keeps delete on the overflow menu and still confirms it", async () => {
    setup({}, [position]);
    const user = userEvent.setup();

    await screen.findByRole("table");
    await openPositionMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));

    expect(screen.getByRole("alertdialog", { name: "Удалить позицию?" })).toHaveTextContent(
      "Synthetic Bond",
    );
  });

  it("formats whole quantities without persistence precision noise", async () => {
    setup({}, [{ ...position, quantity: "64.000000" }]);

    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent("64");
    expect(table).not.toHaveTextContent("64.000000");
  });

  it("opens edit mode with an owner-facing quantity, not persistence scale", async () => {
    const fund = { ...instrument, id: 22, name: "Synthetic Fund", instrument_type: "fund" };
    setup({}, [{ ...position, instrument_id: 22, quantity: "62.000000" }], [fund]);
    const user = userEvent.setup();

    await screen.findByRole("table");
    await startPositionEdit(user, "Synthetic Fund");

    expect(screen.getByDisplayValue("62")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("62.000000")).toBeNull();
  });

  it("keeps meaningful fractional quantity in edit without trailing zeroes", async () => {
    const fund = { ...instrument, id: 22, name: "Synthetic Fund", instrument_type: "fund" };
    setup({}, [{ ...position, instrument_id: 22, quantity: "12.340000" }], [fund]);
    const user = userEvent.setup();

    await screen.findByRole("table");
    await startPositionEdit(user, "Synthetic Fund");

    expect(screen.getByDisplayValue("12,34")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("12.340000")).toBeNull();
  });

  it("rejects fractional stock quantities before posting", async () => {
    const fetchMock = setup();
    const user = userEvent.setup();

    await screen.findByText("Позиции");
    await user.type(screen.getByLabelText("Количество"), "0.5");
    await user.type(screen.getByLabelText("Средняя цена приобретения"), "1000.00");
    await user.type(screen.getByLabelText("Рыночная цена"), "1100.00");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));

    expect(screen.getByRole("alert")).toHaveTextContent("целым числом не меньше 1");
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input) === "/api/positions" && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("keeps fractional quantities for non-stock instruments", async () => {
    const fund = { ...instrument, id: 22, name: "Synthetic Fund", instrument_type: "fund" };
    const fetchMock = setup(
      { "POST /api/positions": () => jsonResponse({ id: 31 }, 201) },
      [],
      [fund],
    );
    const user = userEvent.setup();

    await screen.findByText("Позиции");
    await user.type(screen.getByLabelText("Количество"), "0.5");
    await user.type(screen.getByLabelText("Средняя цена приобретения"), "1000.00");
    await user.type(screen.getByLabelText("Рыночная цена"), "1100.00");
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));

    const post = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/positions" && init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body)).quantity).toBe("0.5");
  });

  it("does not request quote preview until the owner clicks refresh", async () => {
    const fetchMock = setup({}, [position]);
    await screen.findByText("Позиции");
    expect(screen.getByRole("button", { name: "Обновить котировки" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("quote-preview"))).toBe(
      false,
    );
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("market-mapping"))).toBe(
      false,
    );
  });

  it("requests preview only on the explicit action and never calls apply or snapshot write APIs", async () => {
    const previewBody = {
      reporting_month_id: 7,
      month_status: "draft",
      target_date: "2031-01-31",
      month_editable: true,
      batch_error: null,
      rows: [
        {
          position_snapshot_id: 31,
          account_id: 11,
          instrument_id: 21,
          instrument_name: "Synthetic Bond",
          instrument_type: "stock",
          mapping_state: "mapped",
          identity: {
            provider: "moex_iss",
            provider_instrument_id: "SYNB",
            provider_venue_id: "stock/shares/TQBR",
          },
          current_market_price_per_unit: { amount: "1100.00", currency: "RUB" },
          current_price_date: "2031-01-31",
          current_price_source: "manual",
          proposed_market_price_per_unit: { amount: "1110.00", currency: "RUB" },
          proposed_price_date: "2031-01-30",
          proposed_quote_kind: "last",
          proposed_raw_price: "1110.00",
          proposed_raw_price_basis: "R",
          fetched_at_utc: "2031-01-31T12:00:00Z",
          freshness_status: "ok",
          status: "ok",
          failure_reason: null,
          message: null,
          apply_allowed: true,
        },
      ],
    };
    const fetchMock = setup(
      {
        "POST /api/months/7/quote-preview": () => jsonResponse(previewBody),
      },
      [position],
    );
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(await screen.findByText("Котировка получена")).toBeInTheDocument();
    const previewCalls = fetchMock.mock.calls.filter(([input, init]) => {
      return String(input) === "/api/months/7/quote-preview" && init?.method === "POST";
    });
    expect(previewCalls).toHaveLength(1);
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input).includes("apply") || init?.method === "PATCH",
      ),
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/7/quote-preview"),
      ).toHaveLength(2),
    );
  });

  it("keeps the closed-month manual edit path disabled but still allows preview", async () => {
    setup(
      {
        "POST /api/months/7/quote-preview": () =>
          jsonResponse({
            reporting_month_id: 7,
            month_status: "closed",
            target_date: "2031-01-31",
            month_editable: false,
            batch_error: null,
            rows: [],
          }),
      },
      [position],
      [instrument],
      true,
    );
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
    await openPositionMenu(user);
    expect(screen.getByRole("menuitem", { name: "Изменить" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Удалить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Обновить котировки" })).toBeEnabled();
    expect(screen.getByText(/нельзя изменить/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(await screen.findByText("Предпросмотр пуст")).toBeInTheDocument();
  });

  it("blocks a second preview request while the first is in flight", async () => {
    let release: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetchMock = setup(
      {
        "POST /api/months/7/quote-preview": async () => {
          await pending;
          return jsonResponse({
            reporting_month_id: 7,
            month_status: "draft",
            target_date: "2031-01-31",
            month_editable: true,
            batch_error: null,
            rows: [],
          });
        },
      },
      [position],
    );
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(screen.getByRole("button", { name: "Обновляем…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Обновляем…" }));
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/7/quote-preview"),
    ).toHaveLength(1);
    release?.();
    expect(await screen.findByRole("button", { name: "Обновить котировки" })).toBeEnabled();
  });

  it("invalidates the old preview after preview_changed and requires a fresh refresh", async () => {
    const previewBody = {
      reporting_month_id: 7,
      month_status: "draft",
      target_date: "2031-01-31",
      month_editable: true,
      batch_error: null,
      batch_error_reason: null,
      rows: [
        {
          position_snapshot_id: 31,
          account_id: 11,
          instrument_id: 21,
          instrument_name: "T Stock",
          instrument_type: "stock",
          mapping_state: "mapped",
          identity: {
            provider: "t_invest",
            provider_instrument_id: "11111111-1111-1111-1111-111111111111",
            provider_venue_id: null,
          },
          current_market_price_per_unit: { amount: "1100.00", currency: "RUB" },
          current_price_date: "2031-01-31",
          current_price_source: "manual",
          proposed_market_price_per_unit: { amount: "1110.00", currency: "RUB" },
          proposed_price_date: "2031-01-30",
          proposed_quote_kind: "last",
          proposed_raw_price: "1110.00",
          proposed_raw_price_basis: "R",
          fetched_at_utc: "2031-01-31T12:00:00Z",
          freshness_status: "ok",
          status: "ok",
          failure_reason: null,
          message: null,
          apply_allowed: true,
        },
      ],
    };
    const fetchMock = setup(
      {
        "POST /api/months/7/quote-preview": () => jsonResponse(previewBody),
        "POST /api/months/7/quote-apply": () =>
          jsonResponse(
            {
              error: {
                code: "preview_changed",
                message: "quote changed since preview; request a new preview",
                details: [],
              },
            },
            409,
          ),
      },
      [position],
    );
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(await screen.findByText("Котировка получена")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Применить выбранные" }));
    expect(await screen.findByText(/Котировка изменилась после предпросмотра/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Предпросмотр котировок" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Применить выбранные" })).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input) === "/api/months/7/quote-apply"),
    ).toHaveLength(1);
  });

  it("shows local Hermes-down when the preview request cannot reach the app", async () => {
    setup({
      "POST /api/months/7/quote-preview": () => Promise.reject(new TypeError("Failed to fetch")),
    });
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect(await screen.findByText(/Проверь, что Hermes Finance запущен/)).toBeInTheDocument();
    expect(screen.queryByText(/Внешний источник котировок/)).not.toBeInTheDocument();
  });

  it("keeps manual edit available after a provider preview failure", async () => {
    const fetchMock = setup(
      {
        "POST /api/months/7/quote-preview": () =>
          jsonResponse({
            reporting_month_id: 7,
            month_status: "draft",
            target_date: "2031-01-31",
            month_editable: true,
            batch_error:
              "Automatic quote refresh is unavailable because the read-only token is not configured.",
            batch_error_reason: "token_unavailable",
            rows: [
              {
                position_snapshot_id: 31,
                account_id: 11,
                instrument_id: 21,
                instrument_name: "T Stock",
                instrument_type: "stock",
                mapping_state: "mapped",
                identity: {
                  provider: "t_invest",
                  provider_instrument_id: "11111111-1111-1111-1111-111111111111",
                  provider_venue_id: null,
                },
                current_market_price_per_unit: { amount: "1100.00", currency: "RUB" },
                current_price_date: "2031-01-31",
                current_price_source: "manual",
                proposed_market_price_per_unit: null,
                proposed_price_date: null,
                proposed_quote_kind: null,
                proposed_raw_price: null,
                proposed_raw_price_basis: null,
                fetched_at_utc: null,
                freshness_status: null,
                status: "unavailable",
                failure_reason: "token_unavailable",
                message:
                  "Automatic quote refresh is unavailable because the read-only token is not configured.",
                apply_allowed: false,
              },
            ],
          }),
        "PATCH /api/positions/31": () =>
          jsonResponse({
            ...position,
            market_price_per_unit: { amount: "1200.00", currency: "RUB" },
            price_source: "manual",
          }),
      },
      [position],
    );
    const user = userEvent.setup();
    await screen.findByText("Позиции");
    await user.click(screen.getByRole("button", { name: "Обновить котировки" }));
    expect((await screen.findAllByText(/read-only токен не настроен/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/вставь токен/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /примен/i })).not.toBeInTheDocument();
    await startPositionEdit(user);
    const priceInput = screen.getAllByDisplayValue("1100.00")[0];
    await user.clear(priceInput);
    await user.type(priceInput, "1200.00");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    const patch = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/api/positions/31" && init?.method === "PATCH",
    );
    expect(patch).toBeDefined();
    const body = JSON.parse(String(patch?.[1]?.body));
    expect(body.price_source).toBe("manual");
    expect(body.market_price_per_unit).toEqual({ amount: "1200.00", currency: "RUB" });
  });
});
