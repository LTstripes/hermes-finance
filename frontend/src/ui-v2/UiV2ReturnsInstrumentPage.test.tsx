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

test("selected scope and exact period show only that account's known return", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(instrumentCardFixture())),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(screen.getByText("Выбранный счёт · 30.04.2030 – 31.05.2030")).toBeVisible();
  const result = screen.getByRole("heading", { name: "Сумма по данным" }).closest("section");
  expect(result).toHaveTextContent("+12 ₽");
  expect(result).not.toHaveTextContent("+8 ₽");
  const accounts = within(screen.getByRole("region", { name: "Позиции и результат по счетам" }));
  expect(accounts.getByText("Учебный счёт А")).toBeVisible();
  expect(accounts.queryByText("Учебный счёт Б")).toBeNull();
});

test("known trade amounts stay visible when the result is unavailable", async () => {
  const card = instrumentCardFixture();
  const clean = card.accounts[0].clean;
  if (!clean) throw new Error("missing synthetic clean data");
  clean.pnl.value = clean.known_result.value = clean.valuation_and_trades.value = null;
  clean.buys = {
    value: "100000",
    status: "partial",
    reason_codes: ["clean_trades_incomplete"],
    assumptions: [],
  };
  clean.sells = { value: "0", status: "supported", reason_codes: [], assumptions: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const facts = within(await screen.findByRole("region", { name: "Известные суммы сделок" }));
  expect(facts.queryByText("Учебный счёт А")).toBeNull();
  expect(facts.getByText(/Покупки:/)).toHaveTextContent("1 000");
  expect(facts.getByText("Включены не все операции.")).toBeVisible();
  expect(facts.getByText(/Продажи:/)).toHaveTextContent("0");
  expect(facts.getByText(/сами по себе не являются доходностью/)).toBeVisible();
  expect(facts.queryByText("Учебный счёт Б")).toBeNull();
});

test("known trades stay visible beside a partial payout result and retain assumptions", async () => {
  const card = instrumentCardFixture();
  const clean = card.accounts[0].clean;
  if (!clean) throw new Error("missing synthetic clean data");
  clean.pnl.value = null;
  clean.known_result = {
    value: "8700",
    status: "partial",
    reason_codes: ["clean_trades_incomplete"],
    assumptions: [],
  };
  clean.buys = {
    value: "100000",
    status: "provisional",
    reason_codes: [],
    assumptions: ["trade_face_value_missing"],
  };
  clean.sells = {
    value: null,
    status: "unavailable",
    reason_codes: ["clean_trades_incomplete"],
    assumptions: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const facts = within(await screen.findByRole("region", { name: "Известные суммы сделок" }));
  expect(facts.getByText(/Покупки · оценка:/)).toHaveTextContent("1 000");
  expect(facts.getByText(/номинал/i)).toBeVisible();
  expect(facts.queryByText(/Продажи:/)).toBeNull();
});

test("selected account shows supported purchase price changes and true zero", async () => {
  const card = instrumentCardFixture();
  if (!card.accounts[0].clean || !card.accounts[1].clean)
    throw new Error("missing synthetic clean data");
  card.accounts[0].purchases = [
    {
      id: "synthetic-a",
      date: "2030-05-01",
      settlement_date: "2030-05-01",
      quantity: "1",
      remaining_quantity: "1",
      cost_kopecks: "10000",
      sale_proceeds_kopecks: "0",
      value_kopecks: "15000",
      price_result_kopecks: "5000",
      return_fraction: "0.5",
      status: "supported",
      reason_codes: [],
    },
    {
      id: "synthetic-b",
      date: "2030-05-02",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: "1",
      cost_kopecks: "15000",
      sale_proceeds_kopecks: "0",
      value_kopecks: "15000",
      price_result_kopecks: "0",
      return_fraction: "0",
      status: "supported",
      reason_codes: [],
    },
  ];
  card.accounts[1].purchases = [
    {
      id: "synthetic-c",
      date: "2030-05-03",
      settlement_date: "2030-05-03",
      quantity: "1",
      remaining_quantity: "1",
      cost_kopecks: "20000",
      sale_proceeds_kopecks: "0",
      value_kopecks: "15000",
      price_result_kopecks: "-5000",
      return_fraction: "-0.25",
      status: "supported",
      reason_codes: [],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("Учебный счёт А")).toBeVisible();
  expect(region.queryByText("Учебный счёт Б")).toBeNull();
  expect(region.getAllByText(/150,00 ₽/).length).toBeGreaterThan(0);
  expect(region.getByText("0,00 ₽")).toBeVisible();
  expect(region.getByText(/самые ранние покупки \(FIFO\)/)).toBeVisible();
});

test("closed purchase remains visible when the open purchase has no valuation", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "a",
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "10000",
      sale_proceeds_kopecks: "18000",
      value_kopecks: "0",
      price_result_kopecks: "8000",
      return_fraction: "0.8",
      status: "supported",
      reason_codes: [],
    },
    {
      id: "b",
      date: "2030-05-03",
      settlement_date: "2030-05-04",
      quantity: "1",
      remaining_quantity: "1",
      cost_kopecks: "20000",
      sale_proceeds_kopecks: "0",
      value_kopecks: null,
      price_result_kopecks: null,
      return_fraction: null,
      status: "partial",
      reason_codes: ["closing_value_unknown"],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("80,00 ₽")).toBeVisible();
  expect(region.getByText("80 %")).toBeVisible();
  expect(region.getAllByText("Неизвестно").length).toBeGreaterThan(0);
  expect(region.getByText("Данные неполные")).toBeVisible();
});

test("unclassified account activity leaves observed purchase cost visible as partial", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "observed-buy",
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: null,
      cost_kopecks: "10000",
      sale_proceeds_kopecks: null,
      value_kopecks: null,
      price_result_kopecks: null,
      return_fraction: null,
      status: "partial",
      reason_codes: ["purchase_allocation_unproven"],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("100,00 ₽")).toBeVisible();
  expect(region.getByText("Данные неполные")).toBeVisible();
  expect(region.queryByText("80,00 ₽")).toBeNull();
});

test("bond purchase keeps a provisional result without a face value warning", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "bond-buy",
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "100000",
      sale_proceeds_kopecks: "101000",
      value_kopecks: "0",
      price_result_kopecks: "1000",
      return_fraction: "0.01",
      status: "partial",
      reason_codes: ["trade_face_value_missing"],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("10,00 ₽")).toBeVisible();
  expect(region.queryByText("Номинал не подтверждён")).not.toBeInTheDocument();
  expect(region.getByText("Данные неполные")).toBeVisible();
});

test("account-level note does not mark each purchase incomplete", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "bond-buy",
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "100000",
      sale_proceeds_kopecks: "101000",
      value_kopecks: "0",
      price_result_kopecks: "1000",
      return_fraction: "0.01",
      status: "partial",
      reason_codes: ["account_money_unattributed"],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("10,00 ₽")).toBeVisible();
  expect(region.queryByText("Данные неполные")).not.toBeInTheDocument();
  expect(
    region.getByText(
      "На счёте есть операции без привязки к бумаге: результат по ней может быть неполным.",
    ),
  ).toBeVisible();
});

test("shows known purchase result and explains conflicting NKD", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "bond-buy",
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "100000",
      sale_proceeds_kopecks: "101000",
      value_kopecks: "0",
      price_result_kopecks: "1000",
      return_fraction: "0.01",
      status: "partial",
      reason_codes: ["source_nkd_conflict"],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("10,00 ₽")).toBeVisible();
  expect(region.getByText("Расхождение по НКД")).toBeVisible();
  expect(region.getByText("Данные неполные")).toBeVisible();
});

test("same-day buys sold together show both supported price results", async () => {
  const card = instrumentCardFixture();
  card.accounts[0].purchases = [
    {
      id: "a",
      date: "2030-05-01",
      settlement_date: "2030-05-03",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "10000",
      sale_proceeds_kopecks: "15000",
      value_kopecks: "0",
      price_result_kopecks: "5000",
      return_fraction: "0.5",
      status: "supported",
      reason_codes: [],
    },
    {
      id: "b",
      date: "2030-05-01",
      settlement_date: "2030-05-03",
      quantity: "1",
      remaining_quantity: "0",
      cost_kopecks: "20000",
      sale_proceeds_kopecks: "15000",
      value_kopecks: "0",
      price_result_kopecks: "-5000",
      return_fraction: "-0.25",
      status: "supported",
      reason_codes: [],
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(
    await screen.findByRole("region", { name: "Результат сохранённых покупок" }),
  );
  expect(region.getByText("50,00 ₽")).toBeVisible();
  expect(region.getByText("−50,00 ₽")).toBeVisible();
  expect(region.queryByText("Данные неполные")).toBeNull();
});

test("selected scope shows producer-owned price, payouts and result with redemption included once", async () => {
  const card = instrumentCardFixture();
  const account = card.accounts[0];
  const clean = account.clean;
  if (!clean) throw new Error("synthetic clean fixture missing");
  clean.valuation_and_trades.value = "-5000";
  clean.payouts.value = clean.dividends.value = "12000";
  clean.pnl.value = clean.known_result.value = "7000";
  clean.redemption.value = "10000";
  account.ai_account_ref = "source-account-2";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(
    region.getByRole("heading", { name: "Стоимость и сделки" }).closest("section"),
  ).toHaveTextContent("−50 ₽");
  expect(
    region.getByRole("heading", { name: "Полученные выплаты" }).closest("section"),
  ).toHaveTextContent("+120 ₽");
  expect(
    region.getByRole("heading", { name: "Сумма по данным" }).closest("section"),
  ).toHaveTextContent("+70 ₽");
  expect(region.getByText(/Погашение включено в стоимость и сделки/)).toBeVisible();
  expect(screen.getByText("В отчёте AI: source-account-2")).toBeVisible();
});

test("unknown and genuine zero payout are not confused", async () => {
  const card = instrumentCardFixture();
  const clean = card.accounts[0].clean;
  if (!clean) throw new Error("synthetic clean fixture missing");
  clean.payouts.value = "0";
  clean.valuation_and_trades.value = null;
  clean.valuation_and_trades.status = "unavailable";
  clean.pnl.value = null;
  clean.known_result.value = "12000";
  clean.known_result.status = "partial";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup(
    "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
  );
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(
    region.getByRole("heading", { name: "Полученные выплаты" }).closest("section"),
  ).toHaveTextContent("0 ₽");
  expect(
    region.getByRole("heading", { name: "Стоимость и сделки" }).closest("section"),
  ).toHaveTextContent("—");
  expect(
    region.getByRole("heading", { name: "Сумма по данным" }).closest("section"),
  ).toHaveTextContent("+120 ₽");
});

test("older v2 card without additive payouts field leaves it unknown", async () => {
  const card = instrumentCardFixture();
  const oldSummary: Partial<typeof card.summary> = card.summary;
  delete oldSummary.payouts;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(
    region.getByRole("heading", { name: "Полученные выплаты" }).closest("section"),
  ).toHaveTextContent("—");
});

test.each([
  [null, "50", "partial", "+0,50 ₽"],
  ["0", "0", "supported", "0 ₽"],
] as const)(
  "selected account keeps its partial value or genuine zero",
  async (pnl, known, status, shown) => {
    const card = instrumentCardFixture();
    const clean = card.accounts[0].clean;
    if (!clean) throw new Error("synthetic clean fixture missing");
    clean.pnl.value = pnl;
    clean.pnl.status = pnl === null ? "unavailable" : "supported";
    clean.known_result.value = known;
    clean.known_result.status = status;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(card)),
    );
    setup(
      "/v2/returns/instrument/RU000A000002?detail_scope=source%3ASYNTH-A&detail_start=2030-04-30&detail_end=2030-05-31",
    );
    const heading = await screen.findByRole("heading", { name: "Сумма по данным" });
    expect(heading.closest("section")).toHaveTextContent(shown);
  },
);

test.each([
  "detail_scope=source%3ASYNTH-A&detail_start=2030-04-01&detail_end=2030-04-30",
  "detail_scope=source%3AMISSING",
  "detail_scope=source%3ASYNTH-A&detail_scope=source%3ASYNTH-B",
  "detail_scope=source%3ASYNTH-A&detail_start=2030-04-30",
  "detail_scope=",
  "detail_scope=source%3ASYNTH-A&detail_start=&detail_end=",
])("a changed or ambiguous scope never substitutes another result: %s", async (selection) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(instrumentCardFixture())),
  );
  setup(`/v2/returns/instrument/RU000A000002?${selection}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("Счёт или период изменились");
  expect(screen.queryByRole("heading", { name: "Сумма по данным" })).toBeNull();
});

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

test("known clean result remains visible when the account proof is stale", async () => {
  const value = instrumentCardFixture();
  value.accounts[1].detail = null;
  value.accounts[1].proof_status = "stale";
  value.accounts[1].included = true;
  value.accounts[1].reason_codes = [];
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
  expect(accounts.getByText("−4 ₽")).toBeVisible();
  expect(accounts.getByText("−4,00%")).toBeVisible();
  expect(accounts.queryByText("Не все показатели доступны")).toBeNull();
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
  const clean = value.accounts[1].clean;
  if (!clean) throw new Error("missing clean fixture");
  clean.pnl.value = null;
  clean.pnl.status = "unavailable";
  clean.known_result.value = "777";
  clean.known_result.status = "partial";
  clean.coupons.value = "777";
  value.summary.pnl.value = "1200";
  value.summary.pnl.reason_codes = ["instrument_accounts_missing_or_excluded"];
  value.summary.coupons.value = "4277";
  value.summary.payouts.value = "4977";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(value)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(screen.getByRole("heading", { name: "Из чего сложился результат" })).toBeVisible();
  expect(
    screen.getByText(
      "Комиссии и налоги не входят в расчёт. НКД учтён в сделках, стоимости и купонах.",
    ),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "Полученные выплаты" }).closest("section"),
  ).toHaveTextContent("+49,77 ₽");
  expect(screen.getByText(/Купоны: \+42,77 ₽/)).toBeVisible();
  expect(screen.getAllByText("+12 ₽").length).toBeGreaterThan(0);
});

test("whole result keeps the note about unattributed account money", async () => {
  const value = instrumentCardFixture();
  value.summary.pnl.value = "1200";
  value.summary.pnl.reason_codes = [
    "clean_partial_result",
    "account_money_unattributed",
    "income_assumed",
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(value)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  expect(
    screen.getByText(
      /На счёте есть операции без привязки к бумаге: результат по ней может быть неполным\./,
    ),
  ).toBeVisible();
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
  card.summary.payouts.value = "1500";
  card.summary.valuation_and_trades.value = "-1100";
  const clean = card.accounts[0].clean;
  if (!clean) throw new Error("missing clean fixture");
  clean.pnl.value = clean.known_result.value = "400";
  clean.coupons.value = "1000";
  clean.dividends.value = "500";
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
  expect(region.getByText(/Купоны: \+10 ₽ · Дивиденды: \+5 ₽/)).toBeVisible();
  expect(
    region.getByRole("heading", { name: "Сумма по данным" }).closest("section"),
  ).toHaveTextContent("+4 ₽");
  expect(region.queryByText(/^Комиссии:/)).toBeNull();
});

test.each([true, false])(
  "card explains missing summary values once, with reasons=%s",
  async (withReasons) => {
    const card = instrumentCardFixture();
    for (const key of ["valuation_and_trades", "payouts", "pnl"] as const) {
      card.summary[key] = {
        ...card.summary[key],
        value: null,
        reason_codes: withReasons ? ["missing_endpoint"] : [],
      };
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(card)),
    );
    setup("/v2/returns/instrument/RU000A000002");
    const section = await screen.findByRole("region", { name: "Разложение результата" });
    const note = within(section).getByRole("note");
    expect(note).toBeVisible();
    expect(note).toHaveTextContent(
      withReasons
        ? "Не хватает стоимости на границе периода."
        : "Нет подтверждённого значения для этого периода.",
    );
    expect(note.textContent?.split(".").filter(Boolean)).toHaveLength(1);
    expect(within(section).getAllByText("—")).toHaveLength(3);
  },
);

test("bridge draws equality only when the shown parts add up to the total", async () => {
  // Fixture summary: −34 ₽ + 49,77 ₽ against a 12 ₽ total from another account set.
  const partial = instrumentCardFixture();
  partial.summary.payouts.value = "4977";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(partial)),
  );
  const { unmount } = setup("/v2/returns/instrument/RU000A000002");
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(region.queryByText("Итог")).toBeNull();
  expect(region.queryByText("=")).toBeNull();
  expect(
    region.getByText(
      "Части и итог посчитаны по разным наборам данных, поэтому их сумма не равна итогу.",
    ),
  ).toBeVisible();
  unmount();

  const whole = instrumentCardFixture();
  whole.summary.valuation_and_trades.value = "-3400";
  whole.summary.payouts.value = "4600";
  whole.summary.pnl.value = "1200";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(whole)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  const exact = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(exact.getByText("Итог")).toBeVisible();
  expect(exact.getByText("=")).toBeInTheDocument();
  expect(exact.queryByText(/по разным наборам данных/)).toBeNull();
});

test("matching partial numbers never draw a complete equality", async () => {
  // Account A knows valuation and trades (100 ₽) but not payouts; account B knows
  // payouts (0 ₽) but not valuation. The available total is 100 ₽ and stays partial.
  const card = instrumentCardFixture();
  const partial = (value: string) => ({
    value,
    unit: "kopecks" as const,
    method: "known_clean_instruments",
    estimate: true,
    reason_codes: ["clean_partial_result"],
  });
  card.summary.valuation_and_trades = partial("10000");
  card.summary.payouts = partial("0");
  card.summary.pnl = partial("10000");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  const region = within(await screen.findByRole("region", { name: "Разложение результата" }));
  expect(region.queryByText("Итог")).toBeNull();
  expect(region.queryByText("=")).toBeNull();
  expect(region.queryByText("+")).toBeNull();
  expect(region.getByText("по доступным данным")).toBeVisible();
  expect(region.getAllByText(/Это не полный итог/)).toHaveLength(1);
  expect(region.queryByText(/по разным наборам данных/)).toBeNull();
});

test("one account card leads with the simple return and annual XIRR, not Modified Dietz", async () => {
  const card = instrumentCardFixture();
  const rate = (method: "simple_return" | "xirr", value: string | null) => ({
    value,
    status: "supported" as const,
    reason_codes: value === null ? ["short_holding"] : [],
    assumptions: [],
    method,
    annualized: method === "xirr",
    invested_kopecks: "100000",
    start_date: "2029-01-10",
    end_date: "2030-05-31",
    holding_days: 506,
    weighted_holding_days: "506.00",
  });
  const clean = card.accounts[0].clean;
  if (!clean) throw new Error("fixture needs a clean account");
  card.accounts = [
    {
      ...card.accounts[0],
      clean: {
        ...clean,
        modified_dietz: { ...clean.modified_dietz, value: "15.72" },
        simple_return: rate("simple_return", "0.1004"),
        xirr: rate("xirr", "0.1212"),
      },
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(card)),
  );
  setup("/v2/returns/instrument/RU000A000002");
  await screen.findByRole("heading", { level: 1, name: "Учебная акция" });
  const result = screen.getByRole("heading", { name: "Сумма по данным" }).closest("section");
  expect(result).toHaveTextContent("+10,04%");
  expect(result).toHaveTextContent("на вложенное · +12,12% годовых");
  expect(screen.queryByText(/Modified Dietz/)).toBeNull();
  expect(screen.queryByText(/1\s?572/)).toBeNull();
  expect(screen.getByText("Как читать процент")).toBeInTheDocument();
});
