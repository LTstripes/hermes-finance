import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
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
function setup(path = "/v2/returns") {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
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

test("shows five instruments by absolute result and expands or collapses the list", async () => {
  const data = overallFixture();
  const template = data.instruments[1];
  data.instruments = ["100", "-900", "300", "-500", "0", "700", null].map((value, index) => ({
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
  const section = await screen.findByRole("region", { name: "Доходность по инструментам (7)" });
  const names = () =>
    within(section)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("link")[0].textContent);
  expect(names()).toEqual([
    "Инструмент 1",
    "Инструмент 5",
    "Инструмент 3",
    "Инструмент 2",
    "Инструмент 0",
  ]);
  fireEvent.click(within(section).getByRole("button", { name: "Показать все" }));
  expect(names()).toHaveLength(7);
  fireEvent.click(within(section).getByRole("button", { name: "Свернуть" }));
  expect(names()).toHaveLength(5);
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
  const section = await screen.findByRole("region", { name: "Доходность по инструментам (6)" });
  const rows = within(section).getAllByRole("row");
  expect(rows[1]).toHaveTextContent("Бумага 5");
  expect(rows[1]).toHaveTextContent("−9 ₽");
  expect(rows[1]).not.toHaveTextContent("Нет доступного результата");
  fireEvent.click(within(rows[1]).getByText("Учебный счёт А"));
  expect(within(rows[1]).getByText(/30\.04\.2030 — 31\.10\.2030/)).toBeVisible();
  expect(rows[2]).toHaveTextContent("Нет доступного результата");
});

test("different account periods stay separate and preserve the instrument list", async () => {
  const calls = install();
  setup();
  await screen.findByRole("table");
  expect(screen.queryByRole("region", { name: "Результат" })).toBeNull();
  expect(screen.getByRole("combobox", { name: "Счета" })).toHaveValue("all");
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

test("collapsed account row identifies a known partial result without hiding it", async () => {
  const data = overallFixture();
  const [partial, complete] = data.instruments[0].accounts;
  partial.pnl.reason_codes = ["clean_partial_result"];
  partial.pnl.value = "1200";
  complete.pnl.reason_codes = [];
  install(data);
  setup();
  const section = await screen.findByRole("region", { name: /Доходность по инструментам/ });
  const row = within(section).getByRole("row", { name: /Учебная акция/ });
  const partialAccount = within(row).getByRole("region", { name: "Учебный счёт А" });
  const completeAccount = within(row).getByRole("region", { name: "Учебный счёт Б" });
  expect(partialAccount.querySelector("details")).not.toHaveAttribute("open");
  expect(partialAccount.querySelector("summary")).toHaveTextContent("Известная часть: +12 ₽");
  expect(completeAccount.querySelector("summary")).not.toHaveTextContent("Известная часть");
  fireEvent.click(within(partialAccount).getByText(/Известная часть:/));
  expect(within(partialAccount).getByText("Известная часть результата ₽")).toBeVisible();
});

test("comparison and leaders label a known partial amount, including zero", async () => {
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
  expect(zeroRow.querySelector("summary")).toHaveTextContent("Известная часть: 0 ₽");
  expect(screen.getByRole("region", { name: "Вклад инструментов" })).toHaveTextContent(
    "Известная часть: +12 ₽",
  );
  const leaders = screen.getByRole("region", { name: "Лидеры и отстающие" });
  expect(leaders).toHaveTextContent("Известная часть: +12 ₽");
  expect(leaders).toHaveTextContent("часть результатов неполна");
});
test("one account selection keeps its own period without inventing an aggregate rate", async () => {
  const data = overallFixture();
  if (!data.source_accounts[1].result) throw new Error("missing synthetic account");
  data.source_accounts[1].result.rate.value = null;
  const calls = install(data);
  setup();
  await screen.findByRole("table");
  fireEvent.change(screen.getByRole("combobox", { name: "Счета" }), {
    target: { value: "source:SYNTH-B" },
  });
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
  expect(screen.getByText(/Показаны известные составляющие/)).toBeVisible();
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
  await screen.findByRole("combobox", { name: "Счета" });
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
  const link = within(screen.getByRole("table")).getByRole("link", { name: "Учебная акция" });
  expect(link.getAttribute("href")).toContain("/v2/returns/instrument/RU000A000002?back=");
  expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain("q=акция");
  expect(calls).toHaveLength(1);
  fireEvent.click(link);
  await screen.findByRole("heading", { name: "Отдельная карточка" });
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
test("private display labels affect selection only and gold quantities trim trailing zeros", async () => {
  install();
  setup();
  await screen.findByRole("combobox", { name: "Счета" });
  fireEvent.change(screen.getByRole("textbox", { name: "Название: Учебный счёт А" }), {
    target: { value: "Личный брокерский" },
  });
  expect(screen.getByRole("option", { name: "Личный брокерский" })).toHaveValue("source:SYNTH-A");
  expect(localStorage.getItem("hermes.returns.account-display-names.v1")).toContain(
    "Личный брокерский",
  );
  const gold = screen.getByRole("region", { name: "Золото" });
  expect(gold).toHaveTextContent("2.5 г");
  expect(gold).not.toHaveTextContent("2.500");
  expect(within(gold).getAllByRole("heading")).toHaveLength(1);
});
test("gold exact target opens only its source and never dispatches a financial write", async () => {
  const calls = install();
  setup("/v2/returns?capital_account=10&gold_instrument=20#returns-gold");
  await screen.findByRole("button", { name: "Предпросмотр истории" });
  expect(calls.filter((c) => c.includes("owner-manual-gold-history"))).toHaveLength(1);
  expect(calls.some((c) => c.includes("instrument-card"))).toBe(false);
  expect(calls.some((c) => c.includes("confirm"))).toBe(false);
});

test("dirty gold form blocks instrument navigation and survives summary refresh", async () => {
  install();
  setup("/v2/returns?capital_account=10&gold_instrument=20");
  const quantity = await screen.findByLabelText("Заявленное количество на конец истории, г");
  fireEvent.change(quantity, { target: { value: "3.25" } });
  fireEvent.click(within(screen.getByRole("table")).getByRole("link", { name: "Учебная акция" }));
  await screen.findByRole("alertdialog");
  expect(screen.queryByRole("heading", { name: "Отдельная карточка" })).toBeNull();
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
  const row = within(table).getByRole("row", { name: /Учебная акция/ });
  const a = within(row).getByRole("region", { name: "Учебный счёт А" });
  const b = within(row).getByRole("region", { name: "Учебный счёт Б" });
  expect(within(a).getAllByText("Не хватает стоимости на границе периода.")[0]).toBeVisible();
  fireEvent.click(within(a).getByText("Учебный счёт А"));
  fireEvent.click(within(b).getByText("Учебный счёт Б"));
  expect(a).toHaveTextContent("0 ₽");
  expect(a).toHaveTextContent("Не хватает стоимости на границе периода");
  expect(a).toHaveTextContent("30.04.2030 — 31.05.2030");
  expect(b).toHaveTextContent("−4 ₽");
  expect(b).toHaveTextContent("−4,00%");
  expect(b).toHaveTextContent("31.03.2030 — 30.04.2030");
  expect(calls).toEqual(["/api/returns/overall?include_instrument_summaries=true"]);
});
