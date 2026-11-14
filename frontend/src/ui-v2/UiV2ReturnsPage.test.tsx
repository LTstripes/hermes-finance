import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { notifyApiWrite } from "../api/client";
import type { Overall } from "./returns/overall";
import { incomeFixture, overallFixture } from "./returns/overallFixtures";
import UiV2ReturnsPage from "./UiV2ReturnsPage";

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function install(
  value = overallFixture(),
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
      if (url.pathname.endsWith("income")) {
        const kind = url.searchParams.get("kind") === "dividend" ? "dividend" : "coupon";
        const income = incomeFixture(kind);
        income.summary = kind === "coupon" ? value.coupon_income : value.dividend_income;
        return Promise.resolve(response(income));
      }
      if (url.pathname === "/api/owner-manual-gold-history")
        return Promise.resolve(
          response({ contract_version: "owner_manual_gold_history_v1", histories: [] }),
        );
      return Promise.resolve(response(value));
    }),
  );
  return calls;
}
function Location() {
  const l = useLocation();
  return (
    <output data-testid="location">
      {l.pathname}
      {l.search}
    </output>
  );
}
function setup(
  path = "/v2/returns",
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/v2/returns" element={<UiV2ReturnsPage />} />
          <Route path="/v2/returns/instrument/:isin" element={<h1>Отдельная карточка</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

test("shows the backend annual portfolio rate and switches to the account's own rate", async () => {
  const data = overallFixture();
  const annual = {
    pnl: data.overall.pnl,
    rate: {
      ...data.overall.rate,
      value: "0.125",
      reason_codes: [],
      method: "portfolio_inception_xirr",
    },
    first_operation_date: "2028-01-01",
    valuation_date: "2030-12-31",
    weighted_holding_days: "500",
    eligibility_basis: "capital_weighted_holding_days" as const,
  };
  data.annual_return = {
    portfolio: annual,
    accounts: [
      {
        ...annual,
        scope: data.source_accounts[0].scope,
        rate: { ...annual.rate, value: null, reason_codes: ["overall_source_proof_stale"] },
      },
    ],
  };
  install(data);
  setup();
  const rate = await screen.findByRole("region", { name: "Годовая доходность" });
  expect(rate).toHaveTextContent("12,5");
  expect(rate).toHaveTextContent("годовых, с");
  expect(rate).toHaveTextContent("2028");
  fireEvent.click(
    screen.getByRole("button", {
      name: data.source_accounts[0].account_link?.label ?? data.source_accounts[0].label,
    }),
  );
  expect(
    await screen.findByText(
      "Годовая доходность пока неизвестна: подтверждение истории счёта требует проверки.",
    ),
  ).toBeVisible();
  expect(screen.queryByRole("region", { name: "Годовая доходность" })).toBeNull();
  expect(screen.queryByText("overall_source_proof_stale")).toBeNull();
});

test("uses the server short name and keeps a missing name separate from ISIN", async () => {
  const data = overallFixture();
  data.instruments[0].name = "Long source label (SYN)";
  data.instruments[0].short_name = "Короткое имя";
  data.instruments[1].name = data.instruments[1].isin;
  data.instruments[1].short_name = null;
  install(data);
  setup();
  const table = await screen.findByRole("table", { name: "Все бумаги" });
  expect(within(table).getByRole("link", { name: "Короткое имя" })).toBeVisible();
  expect(within(table).getByRole("link", { name: "Без названия" })).toBeVisible();
  expect(within(table).queryByText("Long source label (SYN)")).toBeNull();
  fireEvent.change(screen.getByRole("searchbox", { name: "Поиск" }), {
    target: { value: "Короткое" },
  });
  expect(within(table).getByRole("link", { name: "Короткое имя" })).toBeVisible();
  expect(within(table).queryByRole("link", { name: "Без названия" })).toBeNull();
});

test("server instrument aggregate supplies rates, value, split and open/sold filtering", async () => {
  const data = overallFixture();
  const metric = (value: string | null) => ({
    value,
    status: "supported" as const,
    reason_codes: [],
    assumptions: [],
  });
  const rate = (method: "simple_return" | "xirr", value: string) => ({
    ...metric(value),
    method,
    annualized: method === "xirr",
    invested_kopecks: "10000",
    start_date: "2028-01-01",
    end_date: "2030-01-01",
    holding_days: 731,
    weighted_holding_days: "731.00",
  });
  const aggregate = {
    pnl: metric("2500"),
    realized_result: metric("1000"),
    unrealized_result: metric("1500"),
    current_value: metric("11500"),
    is_open: true,
    position_reason_codes: [],
    simple_return: rate("simple_return", "0.25"),
    xirr: rate("xirr", "0.118"),
  };
  data.instruments = [
    { ...data.instruments[0], name: "Открытая бумага", aggregate },
    {
      ...data.instruments[1],
      name: "Проданная бумага",
      aggregate: {
        ...aggregate,
        is_open: false,
        current_value: metric("0"),
        unrealized_result: metric("0"),
        realized_result: metric("2500"),
      },
    },
  ];
  install(data);
  setup();
  const table = await screen.findByRole("table", { name: "Все бумаги" });
  const row = within(table).getByRole("row", { name: /Открытая бумага/ });
  expect(row).toHaveTextContent("+25,0%");
  expect(row).toHaveTextContent("+11,8%");
  expect(row).toHaveTextContent("115 ₽");
  expect(within(table).queryByText("Проданная бумага")).toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: "Разложение результата" }));
  expect(row).toHaveTextContent("Зафикс. +10 ₽");
  expect(row).toHaveTextContent("В цене +15 ₽");
  fireEvent.change(screen.getByLabelText("Позиции"), { target: { value: "sold" } });
  expect(within(table).queryByText("Открытая бумага")).toBeNull();
  expect(within(table).getByText("Проданная бумага")).toBeVisible();
  fireEvent.change(screen.getByLabelText("Позиции"), { target: { value: "all" } });
  expect(within(table).getByText("Открытая бумага")).toBeVisible();
});

test("one instrument total matches the chart and counts once, with both account rows always visible", async () => {
  const data = overallFixture();
  data.instruments = [data.instruments[0]];
  const [a, b] = data.instruments[0].accounts;
  b.period = a.period;
  install(data);
  setup();
  const table = await screen.findByRole("table", { name: "Все бумаги" });
  const total = within(table).getByRole("row", { name: /Учебная акция/ });
  expect(total).toHaveTextContent("+8 ₽");
  expect(within(total).getAllByText("по счетам")).toHaveLength(2);
  expect(within(table).getByRole("row", { name: /^Учебный счёт А/ })).toHaveTextContent("+12 ₽");
  expect(within(table).getByRole("row", { name: /^Учебный счёт Б/ })).toHaveTextContent("−4 ₽");
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  expect(screen.getByRole("region", { name: "Все бумаги · 1" })).toBeVisible();
  const chart = screen.getByRole("region", { name: "Вклад инструментов" });
  expect(chart).toHaveTextContent("+8 ₽");
  expect(chart).toHaveTextContent("бумаг: в плюсе 1 · в минусе 0 · без итога 0");
  expect(table.querySelector("details")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Учебный счёт А" }));
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByRole("row", { name: /Учебная акция/ })).toHaveTextContent("+12 ₽");
});

test("shows ten instruments by absolute result and expands or collapses the list", async () => {
  const data = overallFixture();
  const template = data.instruments[1];
  data.instruments = [
    "100",
    "-900",
    "300",
    "-500",
    "0",
    "700",
    null,
    "600",
    "-800",
    "200",
    "400",
    "-1000",
  ].map((value, index) => ({
    ...template,
    isin: `TEST${index}`,
    name: `Инструмент ${index}`,
    accounts: template.accounts.map((account) => ({
      ...account,
      pnl: { ...account.pnl, value },
    })),
  }));
  install(data);
  setup();
  const section = await screen.findByRole("region", { name: "Все бумаги · 12" });
  const names = () =>
    within(section)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("link")[0].textContent);
  expect(names()).toEqual([
    "Инструмент 11",
    "Инструмент 1",
    "Инструмент 8",
    "Инструмент 5",
    "Инструмент 7",
    "Инструмент 3",
    "Инструмент 10",
    "Инструмент 2",
    "Инструмент 9",
    "Инструмент 0",
  ]);
  fireEvent.click(within(section).getByRole("button", { name: "Показать все 12" }));
  expect(names()).toHaveLength(12);
  expect(screen.getByTestId("location")).toHaveTextContent("show=all");
  fireEvent.click(within(section).getByRole("button", { name: "Свернуть" }));
  expect(names()).toHaveLength(10);
});

test("sorts and displays a native instrument period despite stale account proof", async () => {
  const data = overallFixture();
  data.source_accounts[0].proof_status = "stale";
  const template = data.instruments[1];
  data.instruments = ["100", "200", "300", "400", "500", "-900"].map((value, index) => ({
    ...template,
    isin: `NATIVE${index}`,
    name: `Бумага ${index}`,
    accounts: template.accounts.map((account) => ({
      ...account,
      native_period: index === 5,
      period: index === 5 ? { start: "2030-04-30", end: "2030-10-31" } : account.period,
      valuation_date: index === 5 ? "2030-10-31" : account.valuation_date,
      pnl: { ...account.pnl, value },
    })),
  }));
  install(data);
  setup();
  const section = await screen.findByRole("region", { name: "Все бумаги · 6" });
  const rows = within(section).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Бумага 5");
  expect(rows[1]).toHaveTextContent("−9 ₽");
  expect(rows[1]).not.toHaveTextContent("Нет доступного результата");
  expect(within(rows[1]).getByRole("link")).toHaveAttribute(
    "href",
    expect.stringContaining("/v2/returns/instrument/NATIVE5?back="),
  );
  expect(within(rows[2]).getAllByRole("cell")[0]).toHaveTextContent("—");
});

test("different account periods stay separate and preserve the instrument list", async () => {
  const calls = install();
  setup();
  await screen.findByRole("table");
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
  expect(screen.getByRole("button", { name: "Все счета" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("region", { name: "Вклад инструментов" })).toHaveTextContent(
    "Проданная облигация",
  );
  expect(screen.getByRole("table")).toHaveTextContent("Проданная облигация");
  expect(screen.queryByRole("region", { name: "Депозиты" })).toBeNull();
  expect(screen.queryByText("Счета и периоды")).toBeNull();
  expect(screen.queryByText("Фактически полученные выплаты")).toBeNull();
  expect(calls).toEqual(["/api/returns/overall?include_instrument_summaries=true"]);
  expect(screen.queryByRole("region", { name: "Доходность периода" })).toBeNull();
});

test("separate account rows identify a partial result without a disclosure or a false total", async () => {
  const data = overallFixture();
  data.instruments[0].accounts[0].pnl = {
    ...data.instruments[0].accounts[0].pnl,
    reason_codes: ["clean_partial_result"],
    value: "1200",
  };
  data.instruments[0].accounts[1].pnl.reason_codes = [];
  install(data);
  setup();
  const table = await screen.findByRole("table", { name: "Все бумаги" });
  const rows = within(table).getAllByRole("row", { name: /^Учебный счёт [АБ]/ });
  expect(rows).toHaveLength(2);
  const partial = rows.find((row) => row.textContent?.includes("Учебный счёт А"));
  const complete = rows.find((row) => row.textContent?.includes("Учебный счёт Б"));
  expect(partial).toHaveTextContent("+12 ₽");
  expect(partial).toHaveTextContent("неполный");
  expect(complete).not.toHaveTextContent("неполный");
  expect(table.querySelector("details")).toBeNull();
  expect(table.querySelector("sup")).toBeNull();
  expect(
    screen.getByText("Неполный результат включает только известные составляющие."),
  ).toBeVisible();
});

test("comparison shows partial amounts without ranking them as full returns", async () => {
  const data = overallFixture();
  data.instruments = data.instruments.map((instrument) => ({
    ...instrument,
    accounts: instrument.accounts.map((account) => ({
      ...account,
      pnl: { ...account.pnl },
    })),
  }));
  for (const instrument of data.instruments) {
    instrument.accounts[0].period = data.instruments[0].accounts[0].period;
  }
  data.instruments[0].accounts[0].pnl.reason_codes = ["clean_partial_result"];
  data.instruments[0].accounts[0].pnl.value = "1200";
  data.instruments[1].accounts[0].pnl.reason_codes = ["clean_partial_result"];
  data.instruments[1].accounts[0].pnl.value = "0";
  install(data);
  setup("/v2/returns?accounts=source%3ASYNTH-A");
  const table = await screen.findByRole("table");
  const zeroRow = within(table).getByRole("row", { name: /Проданная облигация/ });
  expect(zeroRow).toHaveTextContent("0 ₽");
  expect(zeroRow).toHaveTextContent("Учебный счёт А");
  // Partial amounts stay in the table; the leaders chart ranks full results only.
  expect(screen.queryByRole("region", { name: "Вклад инструментов" })).toBeNull();
  expect(
    screen.queryByText("Показаны известные составляющие; часть истории может отсутствовать."),
  ).toBeNull();
});

test("shows the five largest confirmed losses without ranking partial or missing amounts", async () => {
  const data = overallFixture();
  const template = data.instruments[1];
  data.instruments = ["-100", "-200", "-300", "-400", "-500", "-600", "-9999", null].map(
    (value, index) => ({
      ...template,
      isin: `LOSS${index}`,
      name: `Проверка ${index}`,
      accounts: template.accounts.map((account) => ({
        ...account,
        native_period: true,
        period: { start: "2030-04-30", end: "2030-10-31" },
        pnl: {
          ...account.pnl,
          value,
          reason_codes: index === 6 ? ["clean_partial_result"] : [],
        },
      })),
    }),
  );
  install(data);
  setup("/v2/returns?accounts=source%3ASYNTH-A");
  const leaders = await screen.findByRole("region", { name: "Вклад инструментов" });
  const losses = leaders;
  expect(within(losses).getAllByRole("listitem")).toHaveLength(5);
  expect(losses).toHaveTextContent("Проверка 5");
  expect(losses).not.toHaveTextContent("Проверка 0");
  expect(losses).not.toHaveTextContent("Проверка 6");
  expect(losses).not.toHaveTextContent("Проверка 7");
});
test("one account selection keeps its own period without inventing an aggregate rate", async () => {
  const data = overallFixture();
  if (!data.source_accounts[1].result) throw new Error("missing synthetic account");
  data.source_accounts[1].result.rate.value = null;
  const calls = install(data);
  setup();
  await screen.findByRole("table");
  fireEvent.click(
    within(screen.getByRole("group", { name: "Счета" })).getByRole("button", {
      name: "Учебный счёт Б",
    }),
  );
  expect(screen.getByRole("region", { name: "Результат" })).toHaveTextContent("−4 ₽");
  expect(screen.queryByRole("region", { name: "Доходность периода" })).toBeNull();
  expect(calls).toHaveLength(1);
});
test("exact native account eligibility excludes conflicts, keeps source provisional numbers and known zero", async () => {
  const data = overallFixture();
  data.mixed_result.components[1].included = false;
  data.mixed_result.components[1].coverage.status = "conflict";
  data.mixed_result.components[0].amount = {
    ...data.mixed_result.components[0].amount,
    value: "0",
  };
  install(data);
  setup();
  const total = await screen.findByRole("region", { name: "Результат" });
  expect(total).toHaveTextContent("0 ₽");
  expect(screen.queryByText(/Показаны известные составляющие/)).toBeNull();
  const table = screen.getByRole("table");
  expect(table).toHaveTextContent("+12 ₽");
  expect(table).not.toHaveTextContent("−4 ₽");
});
test("no eligible operand remains unknown rather than zero and is not replaced by excluded gold", async () => {
  const data = overallFixture();
  data.mixed_result.components.forEach((c) => {
    c.included = false;
  });
  data.source_accounts.forEach((a) => {
    a.proof_status = "stale";
    a.result = null;
  });
  install(data);
  setup();
  await screen.findByRole("group", { name: "Счета" });
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
  expect(screen.getAllByText("Пока нет результата по сохранённым данным")).toHaveLength(2);
});
test("ambiguous or unknown account URL never silently chooses a numeric scope", async () => {
  install();
  setup("/v2/returns?accounts=source:SYNTH-A&accounts=source:SYNTH-B");
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
});
test("refresh hides previous financial values and error never retains stale totals", async () => {
  let reject = false;
  install(overallFixture(), () => (reject ? Promise.resolve(response({}, 503)) : undefined));
  setup();
  await screen.findByRole("table");
  reject = true;
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
});
test("version mismatch is an error rather than partial trusted payload", async () => {
  install({ ...overallFixture(), contract_version: "unexpected" } as unknown as Overall);
  setup();
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
});
test("card links preserve filtered context and do not load card before entry", async () => {
  const calls = install();
  setup("/v2/returns?accounts=source%3ASYNTH-A&q=акция");
  await screen.findByRole("table");
  const link = within(screen.getByRole("table")).getAllByRole("link", { name: "Учебная акция" })[0];
  expect(link.getAttribute("href")).toContain("/v2/returns/instrument/RU000A000002?back=");
  expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("q=акция");
  const target = new URL(link.getAttribute("href") ?? "", "http://test.invalid");
  expect(target.searchParams.get("detail_scope")).toBe("source:SYNTH-A");
  expect(target.searchParams.get("detail_start")).toBe("2030-04-30");
  expect(target.searchParams.get("detail_end")).toBe("2030-05-31");
  expect(calls).toHaveLength(1);
  fireEvent.click(link);
  await screen.findByRole("heading", { name: "Отдельная карточка" });
});
test("an unknown overview period cannot silently select a different card period", async () => {
  const data = overallFixture();
  data.instruments[0].accounts[0].period = null;
  install(data);
  setup("/v2/returns?accounts=source%3ASYNTH-A&q=акция");
  const link = within(await screen.findByRole("table")).getByRole("link", {
    name: "Учебная акция",
  });
  const target = new URL(link.getAttribute("href") ?? "", "http://test.invalid");
  expect(target.searchParams.get("detail_start")).toBe("unavailable");
  expect(target.searchParams.get("detail_end")).toBe("unavailable");
});
test("paid income loads on disclosure, filters selected accounts and retains repeated legitimate occurrences", async () => {
  const data = overallFixture();
  const detail = incomeFixture("coupon");
  detail.instruments[0].accounts[0].amount.value = "3500";
  detail.events.push({ ...detail.events[0] });
  const calls = install(data, (url) =>
    url.pathname.endsWith("income") ? Promise.resolve(response(detail)) : undefined,
  );
  setup();
  const coupon = await screen.findByRole("region", { name: "Полученные купоны" });
  expect(coupon).toHaveTextContent("35 ₽");
  expect(calls).toHaveLength(1);
  fireEvent.click(within(coupon).getByText("По инструментам", { exact: true }));
  await waitFor(() =>
    expect(calls.filter((c) => c.includes("income?kind=coupon"))).toHaveLength(1),
  );
  await within(coupon).findByRole("table");
  expect(within(coupon).queryByText("Счета и периоды")).toBeNull();
  expect(within(coupon).getAllByText(/15.05.2030/).length).toBeGreaterThanOrEqual(2);
});
test("closing income disclosure aborts obsolete request", async () => {
  let signal: AbortSignal | null | undefined;
  let finish: (r: Response) => void = () => {};
  install(overallFixture(), (url, init) =>
    url.pathname.endsWith("income")
      ? new Promise((resolve) => {
          signal = init?.signal;
          finish = resolve;
        })
      : undefined,
  );
  setup();
  const coupon = await screen.findByRole("region", { name: "Полученные купоны" });
  const toggle = within(coupon).getByText("По инструментам", { exact: true });
  fireEvent.click(toggle);
  await waitFor(() => expect(signal).toBeDefined());
  fireEvent.click(toggle);
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await act(async () => finish(response(incomeFixture("coupon"))));
  expect(within(coupon).queryByRole("table")).toBeNull();
});
test("backend account labels replace browser aliases and gold quantities stay compact", async () => {
  const data = overallFixture();
  data.source_accounts[0].account_link = {
    source_account_id: "SYNTH-CONTRACT",
    financial_account_id: 1,
    account_type: "brokerage",
    label: "Личный брокерский",
    status: "linked",
    reason_codes: [],
  };
  localStorage.setItem(
    "hermes.returns.account-display-names.v1",
    JSON.stringify({ "source:SYNTH-A": "Старая подпись" }),
  );
  install(data, (url) =>
    url.pathname === "/api/accounts"
      ? Promise.resolve(response([{ id: 1, name: "Личный брокерский" }]))
      : undefined,
  );
  setup();
  const selector = await screen.findByRole("group", { name: "Счета" });
  expect(
    await within(selector).findByRole("button", { name: "Личный брокерский" }),
  ).toHaveAttribute("title", "SYNTH-CONTRACT");
  expect(screen.queryByText("Старая подпись")).toBeNull();
  expect(screen.queryByText("Названия счетов")).toBeNull();
  expect(screen.queryByText("Брокерский SYNTH-CONTRACT")).toBeNull();
  const gold = screen.getByRole("region", { name: "Золото" });
  expect(gold).toHaveTextContent("2.5 г");
  expect(gold).not.toHaveTextContent("2.500");
  expect(within(gold).getAllByRole("heading")).toHaveLength(1);
});

test("gold exact target opens only its source and never dispatches a financial write", async () => {
  const calls = install();
  setup("/v2/returns?capital_account=10&gold_instrument=20#returns-gold");
  await screen.findByRole("button", { name: "Предпросмотр истории" });
  await waitFor(() =>
    expect(calls.filter((c) => c.includes("owner-manual-gold-history"))).toHaveLength(1),
  );
  expect(calls.some((c) => c.includes("instrument-card"))).toBe(false);
  expect(calls.some((c) => c.includes("confirm"))).toBe(false);
});

test("dirty gold form blocks instrument navigation and survives summary refresh", async () => {
  install();
  setup("/v2/returns?capital_account=10&gold_instrument=20");
  const quantity = await screen.findByLabelText("Заявленное количество на конец истории, г");
  fireEvent.change(quantity, { target: { value: "3.25" } });
  fireEvent.click(
    within(screen.getByRole("table")).getAllByRole("link", { name: "Учебная акция" })[0],
  );
  await screen.findByRole("alertdialog");
  expect(screen.queryByRole("heading", { name: "Отдельная карточка" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Остаться$/ }));
  fireEvent.click(screen.getByRole("link", { name: "По месяцам" }));
  await screen.findByRole("alertdialog");
  expect(screen.getByTestId("location")).toHaveTextContent("/v2/returns?capital_account=10");
  fireEvent.click(screen.getByRole("button", { name: /^Остаться$/ }));
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await screen.findByRole("table");
  expect(screen.getByLabelText("Заявленное количество на конец истории, г")).toHaveValue("3.25");
});

test("instrument results retain each account's money, rate and own dates, including missing evidence", async () => {
  const data = overallFixture();
  data.instruments[0].accounts[0].pnl.value = "0";
  data.instruments[0].accounts[0].rate = {
    ...data.instruments[0].accounts[0].rate,
    value: null,
    reason_codes: ["missing_endpoint"],
  };
  const calls = install(data);
  setup();
  const table = await screen.findByRole("table");
  const rows = within(table).getAllByRole("row", { name: /^Учебный счёт [АБ]/ });
  expect(rows).toHaveLength(2);
  const a = rows.find((row) => row.textContent?.includes("Учебный счёт А"));
  const b = rows.find((row) => row.textContent?.includes("Учебный счёт Б"));
  expect(a).toHaveTextContent("0 ₽");
  expect(a).toHaveTextContent("—");
  expect(b).toHaveTextContent("−4 ₽");
  expect(table.querySelector("details")).toBeNull();
  expect(calls).toEqual(["/api/returns/overall?include_instrument_summaries=true"]);
});

test("partial account and income subtotals are marked once, also for screen readers", async () => {
  const data = overallFixture();
  for (const account of data.source_accounts)
    if (account.result)
      account.result.pnl = {
        ...account.result.pnl,
        reason_codes: ["clean_partial_result"],
        estimate: true,
      };
  // Both accounts are included, but one subtotal is itself partial.
  const [first, second] = data.coupon_income.accounts;
  Object.assign(second, {
    included: true,
    proof_status: "current",
    exclusion_reason: null,
    reason_codes: [],
    period: first.period,
    amount: { ...first.amount, value: "100", reason_codes: [] },
  });
  data.coupon_income.accounts[0].amount = {
    ...data.coupon_income.accounts[0].amount,
    reason_codes: ["clean_partial_result"],
  };
  install(data);
  setup();
  const accounts = await screen.findByRole("list", { name: "Счета" });
  expect(accounts.querySelector("sup")).toBeNull();
  expect(accounts).not.toHaveTextContent("не полный итог");
  expect(screen.getByText("Показана только известная часть результата.")).toBeVisible();
  const coupon = screen.getByRole("region", { name: "Полученные купоны" });
  expect(coupon).not.toHaveTextContent("не полный итог");
});
test("a position shows the simple return on invested and annual XIRR instead of Modified Dietz", async () => {
  const data = overallFixture();
  const rate = (
    method: "simple_return" | "xirr",
    value: string | null,
    reasons: string[] = [],
  ) => ({
    value,
    status: "supported" as const,
    reason_codes: reasons,
    assumptions: [],
    method,
    annualized: method === "xirr",
    invested_kopecks: "100000",
    start_date: "2029-01-10",
    end_date: "2030-05-31",
    holding_end_date: "2030-02-10",
    holding_days: 506,
    weighted_holding_days: "506.00",
  });
  const template = data.instruments[1];
  data.instruments = [
    {
      ...template,
      isin: "RU000A0RATE1",
      name: "Долгая бумага",
      accounts: template.accounts.map((account) => ({
        ...account,
        rate: { ...account.rate, value: "15.72", method: "modified_dietz" },
        simple_return: rate("simple_return", "0.1004"),
        xirr: rate("xirr", "0.1212"),
      })),
    },
    {
      ...template,
      isin: "RU000A0RATE2",
      name: "Короткая бумага",
      accounts: template.accounts.map((account) => ({
        ...account,
        simple_return: rate("simple_return", "0.2313"),
        xirr: rate("xirr", null, ["short_holding"]),
      })),
    },
  ];
  install(data);
  setup();
  const section = await screen.findByRole("region", { name: "Все бумаги · 2" });
  const long = within(section).getByRole("row", { name: /Долгая бумага/ });
  expect(long).toHaveTextContent("+10,0%");
  expect(long).toHaveTextContent("+12,1%");
  expect(within(long).getAllByRole("cell")[2]).toHaveAttribute(
    "title",
    "Владение: 10.01.2029 — 10.02.2030 · выплаты учтены по 31.05.2030",
  );
  expect(long).not.toHaveTextContent("1 572");
  const short = within(section).getByRole("row", { name: /Короткая бумага/ });
  expect(short).toHaveTextContent("+23,1%");
  expect(short).not.toHaveTextContent("годовых");
  expect(within(short).getAllByRole("cell")[2]).toHaveTextContent("—");
  expect(within(short).getByRole("link")).toHaveAttribute(
    "href",
    expect.stringContaining("/v2/returns/instrument/RU000A0RATE2"),
  );
});

test("first load keeps tabs visible and announces a skeleton without financial values", async () => {
  let finish: (response: Response) => void = () => {};
  install(
    overallFixture(),
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  setup();
  expect(screen.getByRole("navigation", { name: "Разделы доходности" })).toBeVisible();
  expect(screen.getByRole("status", { name: "Загружаем доходность…" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  expect(screen.queryByRole("table")).toBeNull();
  await act(async () => finish(response(overallFixture())));
  await screen.findByRole("table");
});

test("uninvalidated cached overview stays visible during a read and disappears on refresh failure", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const data = overallFixture();
  client.setQueryData(["returns", "overall", "summaries"], data);
  let finish: (response: Response) => void = () => {};
  const calls = install(
    data,
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  setup("/v2/returns", client);
  expect(screen.getByRole("table")).toBeVisible();
  expect(calls).toHaveLength(0);
  void client.refetchQueries({ queryKey: ["returns", "overall"] });
  await screen.findByText("Обновляем…");
  expect(screen.getByRole("table")).toBeVisible();
  await act(async () => finish(response({}, 503)));
  await screen.findByRole("alert");
  expect(screen.queryByRole("table")).toBeNull();
});

test("a notified saved write retires the cached overview before another navigation", async () => {
  install();
  setup();
  await screen.findByRole("table");
  act(() => notifyApiWrite("/api/accounts/1", "PATCH"));
  await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
});

test("clicking table headings keeps account rows with their instrument and preserves back context", async () => {
  install();
  setup("/v2/returns?show=all&q=акция");
  const table = await screen.findByRole("table");
  fireEvent.click(within(table).getByRole("button", { name: "Результат, ₽" }));
  expect(screen.getByTestId("location")).toHaveTextContent("sort=pnl-desc");
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Учебная акция");
  expect(within(table).getAllByRole("row")[2]).toHaveTextContent("Учебный счёт А");
  fireEvent.click(within(table).getByRole("button", { name: "Результат, ₽" }));
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Учебная акция");
  expect(within(table).getAllByRole("row")[3]).toHaveTextContent("Учебный счёт Б");
  for (const [title, sort] of [
    ["Бумага", "name-desc"],
    ["На вложенное", "rate-desc"],
    ["Годовых", "xirr-desc"],
  ]) {
    fireEvent.click(within(table).getByRole("button", { name: title }));
    expect(screen.getByTestId("location")).toHaveTextContent(`sort=${sort}`);
  }
  const link = within(table).getAllByRole("link")[0];
  const back = new URL(link.getAttribute("href") ?? "", "http://localhost").searchParams.get(
    "back",
  );
  expect(back).toContain("show=all");
  expect(back).toContain("sort=xirr-desc");
  expect(back).toContain("q=");
});

test("income cells preserve a known zero and separate payment kinds without a combined total", async () => {
  const data = overallFixture();
  data.instruments = [
    {
      ...data.instruments[1],
      accounts: [
        {
          ...data.instruments[1].accounts[0],
          coupons: { ...data.instruments[1].accounts[0].coupons, value: "0" },
          dividends: { ...data.instruments[1].accounts[0].dividends, value: null },
        },
      ],
    },
  ];
  install(data);
  setup();
  const table = await screen.findByRole("table");
  const income = within(table).getAllByRole("row")[1].querySelector("td:last-child");
  expect(income).toHaveTextContent(/^0$/);
  expect(income).not.toHaveTextContent("див.");
});
