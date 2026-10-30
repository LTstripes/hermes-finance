import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import {
  detailFixture,
  may,
  contextFixture,
  overviewFixture,
  basketFixture,
} from "./returns/fixtures";
import { overallFixture, incomeFixture, instrumentCardFixture } from "./returns/overallFixtures";
import type { Overall } from "./returns/overall";
import { UiV2ReturnsEntry, UiV2ReturnsAccountEntry } from "./UiV2Entry";
// Load the page module before assertions; route-chunk compilation is outside these component tests.
import "./UiV2ReturnsPage";
import "./returns/ReturnsGoldHistory";
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function install(
  value: Overall = overallFixture(),
  override?: (url: URL, init?: RequestInit) => Promise<Response> | undefined,
) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const url = new URL(input, "http://localhost");
      calls.push(url.pathname + url.search);
      const custom = override?.(url, init);
      if (custom) return custom;
      if (url.pathname.endsWith("instrument-card"))
        return Promise.resolve(response(instrumentCardFixture(url.searchParams.get("isin") ?? "")));
      if (url.pathname.endsWith("income")) {
        const kind = url.searchParams.get("kind") === "dividend" ? "dividend" : "coupon";
        const data = incomeFixture(kind);
        data.summary = kind === "coupon" ? value.coupon_income : value.dividend_income;
        return Promise.resolve(response(data));
      }
      if (url.pathname === "/api/owner-manual-gold-history")
        return Promise.resolve(
          response({ contract_version: "owner_manual_gold_history_v1", histories: [] }),
        );
      const period = {
        start: url.searchParams.get("start") ?? may.start,
        end: url.searchParams.get("end") ?? may.end,
      };
      return Promise.resolve(
        response(
          url.pathname.endsWith("overall")
            ? value
            : url.pathname.endsWith("context")
              ? contextFixture
              : url.pathname.endsWith("basket")
                ? basketFixture(period)
                : url.pathname.endsWith("instrument")
                  ? detailFixture(url.searchParams.get("scope") ?? "", period)
                  : overviewFixture(url.searchParams.get("scope") ?? "portfolio", period),
        ),
      );
    }),
  );
  return calls;
}
function Context() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
    </>
  );
}
function setup(path = "/v2/returns", previous?: string) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={previous ? [previous, path] : [path]}>
        <Context />
        <Routes>
          <Route path="/v2/capital" element={<h1>Капитал: исходный контекст</h1>} />
          <Route path="/v2/returns" element={<UiV2ReturnsEntry />} />
          <Route path="/v2/returns/account" element={<UiV2ReturnsAccountEntry />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
test("default loads only all-history overall, shows known backend result with explicit included components", async () => {
  const calls = install();
  setup();
  await screen.findByRole("heading", { name: "В целом" });
  await screen.findByRole("region", { name: "Известный результат" });
  expect(calls).toEqual(["/api/returns/overall"]);
  expect(screen.queryByRole("combobox", { name: "Представление" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Период" })).toBeNull();
  const total = screen.getByRole("region", { name: "Известный результат" });
  expect(total).toHaveTextContent("Известный результат за доступную историю");
  expect(total).toHaveTextContent("Полный результат может быть выше или ниже");
  expect(total).toHaveTextContent("Общая процентная доходность не рассчитана");
  expect(total).toHaveTextContent("Доступен отдельно — не включён");
  expect(total).toHaveTextContent("Золото с неподтверждённым пересечением");
  expect(total).not.toHaveTextContent("12,00%");
  expect(screen.getByRole("button", { name: "Проданная облигация" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Депозиты" })).toHaveTextContent("0 ₽");
  expect(screen.getByRole("region", { name: "Депозиты" })).toHaveTextContent("draft");
  expect(screen.getByRole("region", { name: "Золото" })).toHaveTextContent("20,00%");
  expect(screen.getByRole("region", { name: "Золото" })).toHaveTextContent("без приведения к году");
});

test.each(["source:SYNTH-A", "portfolio"])(
  "old %s URL preserves authority, dates and hash on account route",
  async (scope) => {
    const calls = install();
    setup(`/v2/returns?scope=${scope}&start=${may.start}&end=${may.end}#details`);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `/v2/returns/account?scope=${scope}&start=${may.start}&end=${may.end}#details`,
      ),
    );
    expect(calls.includes("/api/returns/overall")).toBe(false);
  },
);

test("metadata-only stale account, missing snapshots and empty instruments make no numeric claims", async () => {
  const value = overallFixture();
  value.source_accounts = [
    {
      ...value.source_accounts[0],
      result: null,
      period: null,
      proof_status: "stale",
      reason_codes: ["source_proof_stale"],
    },
  ];
  value.instruments = [];
  value.gold.snapshots = [];
  value.deposits.interest = { ...value.deposits.interest, value: null };
  value.deposits.periods = [];
  install(value);
  setup();
  await screen.findByText("Нет подтверждённых числовых значений.");
  expect(
    within(screen.getByRole("region", { name: "По счетам" })).getByText(/проверка устарела/),
  ).toBeVisible();
  expect(screen.getByText("Нет доступного индекса инструментов.")).toBeVisible();
  expect(screen.getByRole("region", { name: "Депозиты" })).not.toHaveTextContent("0 ₽");
  expect(screen.getByRole("region", { name: "Золото" })).toHaveTextContent(
    "Нет доступных сохранённых снимков золота.",
  );
});

test("refresh hides stale values and exposes error before retry", async () => {
  let fail = false;
  install(overallFixture(), () => (fail ? Promise.resolve(response({}, 503)) : undefined));
  setup();
  await screen.findByRole("region", { name: "Известный результат" });
  fail = true;
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Известный результат" })).toBeNull();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  await screen.findByRole("region", { name: "Известный результат" });
});

test("unsupported overall version is an error", async () => {
  install({ ...overallFixture(), contract_version: "future" } as unknown as Overall);
  setup();
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Известный результат" })).toBeNull();
});

test("mixed headline renders exact backend money without calculating or counting excluded components", async () => {
  const value = overallFixture();
  value.mixed_result.components[2].interval = may;
  value.mixed_result.known_result = {
    ...value.mixed_result.known_result,
    value: "987654321098765432100",
  };
  install(value);
  setup();
  const section = await screen.findByRole("region", { name: "Известный результат" });
  expect(section).toHaveTextContent("Известный результат за доступную историю");
  expect(section).toHaveTextContent("9 876 543 210 987 654 321");
  expect(section).toHaveTextContent("Включено: 2");
  expect(section).toHaveTextContent("Снимок на 31.05.2030");
  expect(section).toHaveTextContent("Доступен отдельно — не включён");
});

test.each([null, "0"])(
  "mixed result preserves unavailable and exact zero distinctly: %s",
  async (amount) => {
    const value = overallFixture();
    value.mixed_result.known_result = { ...value.mixed_result.known_result, value: amount };
    value.mixed_result.included_component_count = amount === null ? 0 : 2;
    install(value);
    setup();
    const section = await screen.findByRole("region", { name: "Известный результат" });
    const headline = within(section).getByRole("region", { name: "Известная сумма результата" });
    if (amount === null) expect(headline).not.toHaveTextContent("0 ₽");
    else expect(headline).toHaveTextContent("0 ₽");
  },
);

test("legacy month/category URL remains on the account path without changing authority", async () => {
  const calls = install();
  setup("/v2/returns?month=7&categories=gold#details");
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/v2/returns/account?month=7&categories=gold",
    ),
  );
  expect(calls.includes("/api/returns/overall")).toBe(false);
});

test.each([
  "capital_account=0&gold_instrument=20",
  "capital_account=10&gold_instrument=21",
  "capital_account=10&gold_instrument=20&gold_instrument=20",
])("gold identity mismatch stays explicit: %s", async (selection) => {
  const calls = install();
  setup(`/v2/returns?${selection}#returns-gold`);
  await screen.findByText(/нет единственного подтверждённого соответствия/);
  expect(document.querySelector('[data-capital-selected="true"]')).toBeNull();
  expect(calls).toEqual(["/api/returns/overall"]);
});

test("coupon card uses server sum once, independent of instrument coupons and P&L", async () => {
  const value = overallFixture();
  value.coupon_income.known_total.value = "987654321";
  value.instruments[0].accounts[0].coupons.value = "999999999999";
  value.mixed_result.known_result.value = "800";
  install(value);
  setup();
  const card = await screen.findByRole("region", { name: "Полученные купоны" });
  expect(within(card).getByRole("region", { name: "Известная сумма купонов" })).toHaveTextContent(
    "9 876 543,21 ₽",
  );
  expect(card).toHaveTextContent("включено счетов 1 из 2");
  expect(card).toHaveTextContent("повторно не прибавляется");
  fireEvent.click(within(card).getByText("Счета, периоды и покрытие купонов"));
  expect(await within(card).findByText(/проверка устарела/)).toBeVisible();
  expect(within(card).getByRole("link", { name: "Учебный счёт А" })).toHaveAttribute(
    "href",
    `/v2/returns/account?scope=source%3ASYNTH-A&start=${may.start}&end=${may.end}`,
  );
  expect(screen.getByRole("region", { name: "Известная сумма результата" })).toHaveTextContent(
    "+8 ₽",
  );
});

test.each([null, "0"])(
  "partial coupon total retains true zero versus unknown: %s",
  async (amount) => {
    const value = overallFixture();
    value.coupon_income.known_total.value = amount;
    value.coupon_income.accounts[0].amount.value = amount;
    install(value);
    setup();
    const card = await screen.findByRole("region", { name: "Полученные купоны" });
    const total = within(card).getByRole("region", { name: "Известная сумма купонов" });
    if (amount === null) expect(total).not.toHaveTextContent("0 ₽");
    else expect(total).toHaveTextContent("0 ₽");
    expect(card).toHaveTextContent("Частичное покрытие");
  },
);

test("conflicting coupon sibling remains visible but cannot inflate the server's known zero", async () => {
  const value = overallFixture();
  value.coupon_income.known_total.value = "0";
  value.coupon_income.accounts[0].amount.value = "0";
  Object.assign(value.coupon_income.accounts[1], {
    amount: { ...value.coupon_income.accounts[1].amount, value: "999000" },
    proof_status: "conflict",
    exclusion_reason: "source_account_identity_mapping_conflict",
    reason_codes: ["source_account_identity_mapping_conflict"],
  });
  install(value);
  setup();
  const card = await screen.findByRole("region", { name: "Полученные купоны" });
  expect(within(card).getByRole("region", { name: "Известная сумма купонов" })).toHaveTextContent(
    "0 ₽",
  );
  fireEvent.click(within(card).getByText("Счета, периоды и покрытие купонов"));
  expect(await within(card).findByText(/конфликт данных/)).toBeVisible();
  expect(card).toHaveTextContent("9 990 ₽");
  expect(card).toHaveTextContent("не включён");
});

test("lazy index never renders deferred metrics as financial null and opens one all-account card", async () => {
  const value = overallFixture();
  for (const row of value.instruments)
    for (const account of row.accounts) {
      account.details_loaded = false;
      for (const key of ["pnl", "rate", "coupons", "dividends"] as const)
        account[key] = {
          ...account[key],
          value: null,
          reason_codes: ["instrument_details_not_requested"],
        };
    }
  const calls = install(value);
  setup();
  await screen.findByRole("button", { name: "Учебная акция" });
  const index = screen.getByRole("region", { name: "По инструментам" });
  expect(index).toHaveTextContent("Подробности не запрошены");
  expect(index).not.toHaveTextContent("instrument_details_not_requested");
  expect(calls).toEqual(["/api/returns/overall"]);
  fireEvent.click(within(index).getByRole("button", { name: "Учебная акция" }));
  const card = await screen.findByRole("region", { name: "Карточка инструмента RU000A000002" });
  await within(card).findByRole("heading", { name: "Учебная акция" });
  expect(calls).toEqual(["/api/returns/overall", "/api/returns/instrument-card?isin=RU000A000002"]);
  expect(card).toHaveTextContent("Учебный счёт А");
  expect(card).toHaveTextContent("Учебный счёт Б");
  expect(card).toHaveTextContent("31.05.2030");
  expect(card).toHaveTextContent("30.04.2030");
  expect(card).toHaveTextContent("12,00%");
  expect(card).toHaveTextContent("−4,00%");
  const accountDetail = within(card)
    .getByText("Операции и расчёт: Учебный счёт А")
    .closest("details");
  if (!accountDetail) throw new Error("Account disclosure missing");
  fireEvent.click(within(card).getByText("Операции и расчёт: Учебный счёт А"));
  fireEvent.click(within(accountDetail).getByText(/Сделки и выплаты/));
  expect(within(accountDetail).getByText("Продажа", { exact: true })).toBeVisible();
  expect(card).toHaveTextContent("11800");
  expect(calls).toHaveLength(2);
});
test("lazy card cancellation and late response never replace another ISIN", async () => {
  let finish: (response: Response) => void = () => {};
  let signal: AbortSignal | null | undefined;
  const calls = install(overallFixture(), (url, init) =>
    url.pathname.endsWith("instrument-card") && url.searchParams.get("isin") === "RU000A000002"
      ? new Promise((resolve) => {
          finish = resolve;
          signal = init?.signal;
        })
      : undefined,
  );
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Учебная акция" }));
  await waitFor(() => expect(calls).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "К списку инструментов" }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Проданная облигация" }));
  const card = await screen.findByRole("region", { name: "Карточка инструмента RU000A000003" });
  await within(card).findByRole("heading", { name: "Проданная облигация" });
  await act(async () => finish(response(instrumentCardFixture())));
  expect(screen.queryByRole("region", { name: "Карточка инструмента RU000A000002" })).toBeNull();
});
test("lazy Capital entry opens the same all-account card without selecting one account and Back returns", async () => {
  const calls = install();
  setup("/v2/returns?isin=RU000A000002&capital_account=3", "/v2/capital?month=91");
  const card = await screen.findByRole("region", { name: "Карточка инструмента RU000A000002" });
  await within(card).findByRole("heading", { name: "Учебная акция" });
  expect(card).toHaveTextContent("карточка показывает все счета");
  expect(card.querySelector('[data-capital-context="true"]')).toHaveTextContent("Учебный счёт А");
  expect(
    within(card).getByText("Операции и расчёт: Учебный счёт А").closest("details"),
  ).not.toHaveAttribute("open");
  expect(
    within(card).getByText("Операции и расчёт: Учебный счёт Б").closest("details"),
  ).not.toHaveAttribute("open");
  expect(calls).toHaveLength(2);
  expect(calls.some((call) => call.startsWith("/api/returns/instrument?"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByRole("heading", { name: "Капитал: исходный контекст" });
  expect(screen.getByTestId("location")).toHaveTextContent("month=91");
});
test.each(["0", "-1", "3.5", "03", "9007199254740992", "3&capital_account=4"])(
  "lazy invalid Capital context %s never chooses or hides an account",
  async (id) => {
    const calls = install();
    setup(`/v2/returns?isin=RU000A000002&capital_account=${id}`);
    const card = await screen.findByRole("region", { name: "Карточка инструмента RU000A000002" });
    await within(card).findByText(/не подтверждён однозначно/);
    expect(card.querySelector('[data-capital-context="true"]')).toBeNull();
    expect(card).toHaveTextContent("Учебный счёт Б");
    expect(calls).toHaveLength(2);
  },
);
test.each(["wrong-version", "wrong-isin", "wrong-account", "wrong-analysis-period"])(
  "lazy card rejects mismatched server context: %s",
  async (kind) => {
    const value = instrumentCardFixture();
    if (kind === "wrong-version") Object.assign(value, { contract_version: "future" });
    if (kind === "wrong-isin") value.isin = "RU000A000003";
    if (kind === "wrong-account" && value.accounts[0].detail)
      value.accounts[0].detail.scope = "source:WRONG";
    if (kind === "wrong-analysis-period" && value.accounts[0].detail)
      value.accounts[0].detail.analysis.opening.date = "1990-01-01";
    install(overallFixture(), (url) =>
      url.pathname.endsWith("instrument-card") ? Promise.resolve(response(value)) : undefined,
    );
    setup("/v2/returns?isin=RU000A000002");
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить карточку");
    expect(screen.queryByText("Все счета этого ISIN")).toBeNull();
  },
);
test("lazy card keeps sold zero quantity and known sibling metrics beside a stale account", async () => {
  const value = instrumentCardFixture();
  value.accounts[1].detail = null;
  value.accounts[1].proof_status = "stale";
  value.accounts[1].included = false;
  value.accounts[1].reason_codes = ["source_proof_stale"];
  install(overallFixture(), (url) =>
    url.pathname.endsWith("instrument-card") ? Promise.resolve(response(value)) : undefined,
  );
  setup("/v2/returns?isin=RU000A000002");
  const card = await screen.findByRole("region", { name: "Карточка инструмента RU000A000002" });
  await within(card).findByText(/Старые числовые значения не подставляются/);
  expect(card).toHaveTextContent("+12 ₽");
  expect(card).toHaveTextContent("12,00%");
  expect(card).toHaveTextContent("0,00 ₽");
});
test("lazy coupon/dividend disclosures load only their own events and keep same-looking occurrences", async () => {
  const calls = install(overallFixture(), (url) => {
    if (!url.pathname.endsWith("income")) return undefined;
    const kind = url.searchParams.get("kind") === "dividend" ? "dividend" : "coupon";
    const value = incomeFixture(kind);
    value.events = [value.events[0], { ...value.events[0] }];
    return Promise.resolve(response(value));
  });
  setup();
  const coupon = await screen.findByRole("region", { name: "Полученные купоны" });
  const dividend = screen.getByRole("region", { name: "Полученные дивиденды" });
  expect(calls).toEqual(["/api/returns/overall"]);
  fireEvent.click(within(coupon).getByText("Счета, периоды и покрытие купонов"));
  await within(coupon).findByRole("heading", { name: "Фактически полученные выплаты" });
  expect(within(coupon).getAllByText("15.05.2030")).toHaveLength(2);
  expect(calls.filter((call) => call.includes("/income?"))).toEqual([
    "/api/returns/income?kind=coupon",
  ]);
  fireEvent.click(within(dividend).getByText("Счета, периоды и покрытие дивидендов"));
  await within(dividend).findByRole("heading", { name: "Фактически полученные выплаты" });
  expect(calls.filter((call) => call.includes("/income?"))).toHaveLength(2);
  fireEvent.click(within(coupon).getByRole("button", { name: "Учебная акция" }));
  await screen.findByRole("region", { name: "Карточка инструмента RU000A000002" });
  expect(calls.some((call) => call.startsWith("/api/returns/instrument?"))).toBe(false);
});
test("lazy closing paid-income disclosure aborts obsolete work", async () => {
  let signal: AbortSignal | null | undefined;
  const calls = install(overallFixture(), (url, init) =>
    url.pathname.endsWith("income")
      ? new Promise(() => {
          signal = init?.signal;
        })
      : undefined,
  );
  setup();
  const card = await screen.findByRole("region", { name: "Полученные купоны" });
  const toggle = within(card).getByText("Счета, периоды и покрытие купонов");
  fireEvent.click(toggle);
  await waitFor(() => expect(calls).toHaveLength(2));
  fireEvent.click(toggle);
  await waitFor(() => expect(signal?.aborted).toBe(true));
});
test("lazy gold instrument entry loads only its exact full-history source and leaves initial facts empty", async () => {
  const calls = install();
  setup("/v2/returns?capital_account=10&gold_instrument=20#returns-gold");
  await screen.findByRole("heading", { name: "В целом" });
  await screen.findByRole("region", { name: "История золота владельца" });
  await screen.findByText("История операций пока не сохранена.");
  expect(calls).toEqual([
    "/api/returns/overall",
    "/api/owner-manual-gold-history?account_id=10&instrument_id=20",
  ]);
  expect(screen.getByLabelText("Заявленное количество на конец истории, г")).toHaveValue("");
  expect(screen.getByLabelText("Сумма операции без отдельной комиссии, ₽")).toHaveValue("");
});

test("lazy gold history summary remains visible without a snapshot and opens only its exact source", async () => {
  const value = overallFixture();
  const metric = value.gold.snapshots[0].unrealized_result;
  value.gold.snapshots = [];
  value.gold.histories = [
    {
      account_id: 10,
      instrument_id: 20,
      label: "Synthetic gold history",
      revision: 1,
      source_kind: "owner_manual_gold_history",
      authority: "owner_attestation",
      amount_basis: "actual",
      tax_treatment: "not_provided",
      currentness: "current",
      period: may,
      valuation_date: null,
      valuation_status: null,
      total_result: metric,
      realized_result: metric,
      unrealized_result: metric,
      buy_amount: metric,
      sale_amount: metric,
      separate_fees: metric,
      reason_codes: [],
    },
  ];
  const calls = install(value);
  setup();
  const summary = await screen.findByRole("region", {
    name: "Результаты истории золота владельца",
  });
  expect(summary).toHaveTextContent("Сведения владельца".toLocaleLowerCase("ru"));
  expect(calls).toEqual(["/api/returns/overall"]);
  expect(
    screen.queryByText("Данные не подтверждают реализованный результат или историю сделок."),
  ).toBeNull();
  fireEvent.click(within(summary).getByRole("link", { name: "Открыть историю золота" }));
  await screen.findByText("История операций пока не сохранена.");
  expect(calls.at(-1)).toBe("/api/owner-manual-gold-history?account_id=10&instrument_id=20");
  expect(screen.queryByText(/Исходная сохранённая оценка:/)).toBeNull();
});

test("lazy income retains dated payouts with unresolved instrument identity", async () => {
  install(undefined, (url) => {
    if (!url.pathname.endsWith("income")) return undefined;
    const data = incomeFixture("coupon");
    data.events[0].isin = null;
    data.events[0].name = null;
    return Promise.resolve(response(data));
  });
  setup();
  const coupon = await screen.findByRole("region", { name: "Полученные купоны" });
  fireEvent.click(within(coupon).getByText("Счета, периоды и покрытие купонов"));
  expect(await within(coupon).findByText(/Инструмент не установлен/)).toHaveTextContent(
    "ISIN не подтверждён",
  );
});
