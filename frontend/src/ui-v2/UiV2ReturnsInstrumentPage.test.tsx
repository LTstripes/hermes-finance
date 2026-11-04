import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { instrumentCardFixture } from "./returns/overallFixtures";
import UiV2ReturnsInstrumentPage from "./UiV2ReturnsInstrumentPage";

const response = (value: unknown) =>
  new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
      <button type="button" onClick={() => navigate("/v2/returns/instrument/RU000A000003")}>
        Другой инструмент
      </button>
    </>
  );
}
function setup(
  path: string,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/v2/returns/instrument/:isin" element={<UiV2ReturnsInstrumentPage />} />
          <Route path="*" element={<p>Вернулись к списку</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

test("background refresh keeps the card and signals that data is updating", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let finish: (value: Response) => void = () => {};
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(instrumentCardFixture()))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
  vi.stubGlobal("fetch", fetch);
  setup("/v2/returns/instrument/RU000A000002", client);
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  void client.invalidateQueries({ queryKey: ["returns", "instrument-card"] });
  expect(await screen.findByText("Обновляем данные…")).toBeVisible();
  expect(screen.getByRole("heading", { level: 1, name: "Учебная акция" })).toBeVisible();
  await act(async () => finish(response(instrumentCardFixture())));
  await waitFor(() => expect(screen.queryByText("Обновляем данные…")).toBeNull());
});

test("standalone entry fetches one card only, renders compact native trades and returns to filters", async () => {
  const card = instrumentCardFixture();
  for (const account of card.accounts) {
    const event = account.detail?.analysis.events[0];
    if (!event || !account.detail) throw new Error("synthetic fixture missing");
    event.native_identity = "synthetic-native-pair";
    event.quantity_delta = "-10.000000";
    account.detail.analysis.events.push({
      ...event,
      event_key: "cash-only-nkd",
      native_identity: null,
      quantity_delta: null,
      native_trade_amount_kopecks: null,
    });
  }
  card.summary.coupons.value = "0";
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      calls.push(path);
      return response(card);
    }),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?back=%2Fv2%2Freturns%3Fq%3Dsynthetic%26account%3Dboth",
  );
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(calls).toEqual(["/api/returns/instrument-card?isin=RU000A000002"]);
  expect(screen.queryByRole("heading", { name: "Полученные купоны" })).toBeNull();
  expect(screen.queryByText("source:SYNTH-A")).toBeNull();
  const trades = within(screen.getByRole("region", { name: "Покупки и продажи" }));
  expect(trades.getAllByRole("row")).toHaveLength(3);
  expect(trades.getAllByText("10")).toHaveLength(2);
  expect(trades.queryByText("cash-only-nkd")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "К доходности" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/v2/returns?q=synthetic&account=both");
});

test("invalid identity performs no read and foreign Back is not accepted", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  setup("/v2/returns/instrument/not-an-isin?back=https%3A%2F%2Fexample.test");
  expect(screen.getByRole("alert")).toHaveTextContent("Инструмент не выбран");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Назад" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/v2/returns");
});

test("late card response cannot paint another instrument page", async () => {
  let finish: (value: Response) => void = () => {};
  let signal: AbortSignal | null | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) =>
      path.includes("RU000A000002")
        ? new Promise<Response>((resolve) => {
            finish = resolve;
            signal = init?.signal;
          })
        : Promise.resolve(response(instrumentCardFixture("RU000A000003"))),
    ),
  );
  setup("/v2/returns/instrument/RU000A000002");
  fireEvent.click(screen.getByRole("button", { name: "Другой инструмент" }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await screen.findByRole("heading", { level: 1, name: "Проданная облигация" });
  await act(async () => finish(response(instrumentCardFixture())));
  expect(screen.queryByRole("heading", { name: "Учебная акция" })).toBeNull();
});

test.each(["wrong-version", "wrong-isin", "wrong-account", "wrong-analysis-period"])(
  "standalone rejects mismatched server context: %s",
  async (kind) => {
    const value = instrumentCardFixture();
    if (kind === "wrong-version") Object.assign(value, { contract_version: "future" });
    if (kind === "wrong-isin") value.isin = "RU000A000003";
    if (kind === "wrong-account" && value.accounts[0].detail)
      value.accounts[0].detail.scope = "source:WRONG";
    if (kind === "wrong-analysis-period" && value.accounts[0].detail)
      value.accounts[0].detail.analysis.opening.date = "1990-01-01";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(value)),
    );
    setup("/v2/returns/instrument/RU000A000002");
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить инструмент");
    expect(screen.queryByRole("heading", { name: "По счетам" })).toBeNull();
  },
);

test("sold zero and known sibling survive a stale account without stale zero fallback", async () => {
  const value = instrumentCardFixture();
  value.accounts[1].detail = null;
  value.accounts[1].proof_status = "stale";
  value.accounts[1].included = false;
  value.accounts[1].reason_codes = ["source_proof_stale"];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(value)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  const accounts = within(screen.getByRole("region", { name: "Позиции и результат по счетам" }));
  expect(accounts.getByText("0 шт.")).toBeVisible();
  expect(accounts.getByText("+12 ₽")).toBeVisible();
  expect(accounts.getByText("12,00%")).toBeVisible();
  expect(accounts.getByText("Нужна проверка данных")).toBeVisible();
  expect(accounts.getAllByText("—")).toHaveLength(2);
  expect(accounts.queryByText("0 ₽")).toBeNull();
  expect(
    screen.getByText(
      "Проверка выписок устарела; требуется актуальное подтверждение. Счёт: Учебный счёт Б · Инструмент: Учебная акция.",
    ),
  ).toBeInTheDocument();
});

test.each(["0", "-1", "3.5", "03", "9007199254740992", "3&capital_account=4"])(
  "invalid Capital context %s does not select or hide an account",
  async (id) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(instrumentCardFixture())),
    );
    setup(`/v2/returns/instrument/RU000A000002?capital_account=${id}`);
    await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
    expect(screen.getByText(/Связь с выбранным счётом капитала не подтверждена/)).toBeVisible();
    expect(document.querySelector('[data-capital-context="true"]')).toBeNull();
    expect(screen.getByText("Учебный счёт А")).toBeVisible();
    expect(screen.getByText("Учебный счёт Б")).toBeVisible();
  },
);

test("Capital entry highlights exact identity but keeps both accounts and its Back filter", async () => {
  const fetch = vi.fn(async () => response(instrumentCardFixture()));
  vi.stubGlobal("fetch", fetch);
  setup("/v2/returns/instrument/RU000A000002?capital_account=3&back=%2Fv2%2Fcapital%3Fmonth%3D91");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(document.querySelector('[data-capital-context="true"]')).toHaveTextContent(
    "Учебный счёт А",
  );
  expect(screen.getByText("Учебный счёт Б")).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "К капиталу" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/v2/capital?month=91");
});

test("included account with missing quantity does not turn a known zero into a sold position", async () => {
  const value = instrumentCardFixture();
  value.summary.quantity.value = "0";
  value.summary.quantity.reason_codes = [
    "known_instrument_accounts_only",
    "instrument_accounts_missing_or_excluded",
  ];
  const missing = value.accounts[1].detail;
  if (!missing) throw new Error("missing synthetic detail");
  missing.closing_quantity = missing.analysis.closing.quantity = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(value)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(screen.queryByRole("heading", { name: "Позиция продана" })).toBeNull();
  const quantity = within(screen.getByRole("region", { name: "Известное количество инструмента" }));
  expect(quantity.getByRole("heading", { name: "Количество" })).toBeVisible();
  expect(quantity.getByText("0")).toBeVisible();
  expect(screen.getAllByText(/Не по всем счетам подтверждён остаток/)).toHaveLength(1);
});

test("partial component account sets are labelled known constituents without implying an exact bridge", async () => {
  const value = instrumentCardFixture();
  const partial = value.accounts[1].detail;
  if (!partial) throw new Error("missing synthetic detail");
  partial.pnl.value = partial.analysis.pnl.value = null;
  partial.pnl.reason_codes = ["missing_endpoint"];
  partial.analysis.pnl.status = "unavailable";
  partial.analysis.components.coupons.value = "777";
  value.summary.pnl.value = "1200";
  value.summary.pnl.reason_codes = ["instrument_accounts_missing_or_excluded"];
  value.summary.coupons.value = "4277";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(value)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(screen.getByRole("heading", { name: "Из чего сложился результат" })).toBeVisible();
  expect(screen.getByText("Данных для полного разложения пока недостаточно.")).toBeVisible();
  expect(screen.getAllByText("42,77 ₽").length).toBeGreaterThan(0);
  expect(screen.getAllByText("+12 ₽").length).toBeGreaterThan(0);
});

test("standalone instrument explains paid income greater than its exact total", async () => {
  const card = instrumentCardFixture();
  card.accounts = [card.accounts[0]];
  const detail = card.accounts[0].detail;
  if (!detail) throw new Error("missing synthetic detail");
  for (const metric of [
    card.summary.pnl,
    card.summary.coupons,
    card.summary.dividends,
    card.summary.valuation_and_trades,
    card.summary.redemption,
    card.summary.costs,
    card.summary.taxes,
  ])
    Object.assign(metric, { value: "0", estimate: false, reason_codes: [] });
  card.summary.pnl.value = detail.pnl.value = "400";
  detail.pnl.estimate = false;
  card.summary.coupons.value = "1000";
  card.summary.dividends.value = "500";
  card.summary.valuation_and_trades.value = "-1100";
  const metric = (value: string) => ({
    value,
    status: "supported" as const,
    reason_codes: [],
    assumptions: [],
  });
  detail.analysis.pnl = metric("400");
  for (const key of Object.keys(detail.analysis.components))
    Object.assign(
      detail.analysis.components[key as keyof typeof detail.analysis.components],
      metric("0"),
    );
  Object.assign(detail.analysis.components, {
    valuation_and_trades: metric("-1100"),
    coupons: metric("1000"),
    dividends: metric("500"),
    payouts: metric("1500"),
    price_and_trades: metric("-800"),
    commissions: metric("100"),
    paid_nkd: metric("200"),
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(region.getByText("+15 ₽")).toBeVisible();
  expect(region.getByText("+4 ₽")).toBeVisible();
  expect(region.getByText("Комиссии")).toBeVisible();
  expect(region.getByText("Уплаченный НКД")).toBeVisible();
  expect(region.queryByText(/недостаточно/)).toBeNull();
});
