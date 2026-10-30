import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import {
  detailFixture,
  may,
  april,
  contextFixture,
  overviewFixture,
  basketFixture,
} from "./returns/fixtures";
import { overallFixture } from "./returns/overallFixtures";
import type { Overall } from "./returns/overall";
import { UiV2ReturnsEntry, UiV2ReturnsAccountEntry } from "./UiV2Entry";

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function install(
  value: Overall = overallFixture(),
  override?: (url: URL) => Promise<Response> | undefined,
) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = new URL(input, "http://localhost");
      calls.push(url.pathname + url.search);
      return (
        override?.(url) ??
        Promise.resolve(
          response(
            url.pathname.endsWith("overall")
              ? value
              : url.pathname.endsWith("instrument")
                ? detailFixture(
                    url.searchParams.get("scope") ?? "",
                    {
                      start: url.searchParams.get("start") ?? "",
                      end: url.searchParams.get("end") ?? "",
                    },
                    url.searchParams.get("isin") ?? "",
                  )
                : url.pathname.endsWith("context")
                  ? contextFixture
                  : url.pathname.endsWith("basket")
                    ? basketFixture(may)
                    : overviewFixture(url.searchParams.get("scope") ?? "portfolio", may),
          ),
        )
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
afterEach(() => vi.unstubAllGlobals());
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
test("one ISIN retains exact account and interval, ignores late response and supports Back context", async () => {
  let finish: (value: Response) => void = () => {};
  const calls = install(overallFixture(), (url) =>
    url.pathname.endsWith("instrument") && url.searchParams.get("scope") === "source:SYNTH-A"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined,
  );
  setup();
  await screen.findByRole("button", { name: "Учебная акция" });
  fireEvent.click(screen.getByRole("button", { name: "Учебная акция" }));
  expect(calls).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Разбор: Учебный счёт А" }));
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("scope=source%3ASYNTH-A") &&
          url.includes(`start=${may.start}`) &&
          url.includes(`end=${may.end}`),
      ),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Разбор: Учебный счёт Б" }));
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("scope=source%3ASYNTH-B") &&
          url.includes(`start=${april.start}`) &&
          url.includes(`end=${april.end}`),
      ),
    ).toBe(true),
  );
  await act(async () => finish(response(detailFixture("source:SYNTH-A", may, "RU000A000002"))));
  expect(screen.getByRole("button", { name: "Разбор: Учебный счёт Б" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByTestId("location")).toHaveTextContent("detail_scope=source%3ASYNTH-B");
  fireEvent.click(screen.getByRole("button", { name: "К списку счетов этой бумаги" }));
  expect(screen.getByRole("button", { name: "Учебная акция" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent("detail_scope=source%3ASYNTH-B"),
  );
  const links = screen.getAllByRole("link", { name: "История счёта" });
  expect(links[0]).toHaveAttribute(
    "href",
    `/v2/returns/account?scope=source%3ASYNTH-A&start=${may.start}&end=${may.end}`,
  );
});
test("mismatched detail URL never fetches a different interval", async () => {
  const calls = install();
  setup(
    "/v2/returns?isin=RU000A000002&detail_scope=source:SYNTH-A&detail_start=2030-01-01&detail_end=2030-05-31",
  );
  await screen.findByRole("button", { name: "Разбор: Учебный счёт А" });
  expect(calls).toEqual(["/api/returns/overall"]);
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
  expect(screen.getByText("Нет доступных расчётов по инструментам.")).toBeVisible();
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

test("metadata-only instrument has no artificial detail period", async () => {
  const value = overallFixture();
  value.instruments = [
    { ...value.instruments[0], accounts: [{ ...value.instruments[0].accounts[0], period: null }] },
  ];
  const calls = install(value);
  setup("/v2/returns?isin=RU000A000002");
  expect(await screen.findByRole("button", { name: "Разбор: Учебный счёт А" })).toBeDisabled();
  expect(calls).toEqual(["/api/returns/overall"]);
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

test("Capital ISIN and unique canonical account open exact source detail, replace URL and preserve Back", async () => {
  const calls = install();
  setup("/v2/returns?isin=RU000A000002&capital_account=3", "/v2/capital?month=91");
  await waitFor(() => expect(calls.filter((url) => url.includes("/instrument?"))).toHaveLength(1));
  expect(calls[1]).toContain("scope=source%3ASYNTH-A");
  expect(calls[1]).toContain(`start=${may.start}&end=${may.end}`);
  expect(screen.getByTestId("location")).not.toHaveTextContent("capital_account=");
  expect(screen.getByRole("button", { name: "Разбор: Учебный счёт А" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByRole("heading", { name: "Капитал: исходный контекст" });
  expect(screen.getByTestId("location")).toHaveTextContent("/v2/capital?month=91");
});
test.each(["0", "-1", "3.5", "03", "9007199254740992", "NaN", "3&capital_account=4"])(
  "invalid/duplicate Capital account %s never picks source detail",
  async (id) => {
    const calls = install();
    setup(`/v2/returns?isin=RU000A000002&capital_account=${id}`);
    await screen.findByText(/нет единственного подтверждённого соответствия/);
    expect(calls).toEqual(["/api/returns/overall"]);
  },
);
test.each(["unmapped", "conflict", "missing-period", "invalid-period"])(
  "Capital %s metadata never guesses; manual source selection stays available",
  async (kind) => {
    const value = overallFixture();
    if (kind === "unmapped") value.instruments[0].accounts[0].canonical_account_id = null;
    if (kind === "conflict") value.instruments[0].accounts[1].canonical_account_id = 3;
    if (kind === "missing-period") value.instruments[0].accounts[0].period = null;
    if (kind === "invalid-period")
      value.instruments[0].accounts[0].period = { start: "2030-02-31", end: may.end };
    const calls = install(value);
    setup("/v2/returns?isin=RU000A000002&capital_account=3");
    await screen.findByText(/нет единственного подтверждённого соответствия/);
    expect(calls).toEqual(["/api/returns/overall"]);
    fireEvent.click(screen.getByRole("button", { name: "Разбор: Учебный счёт Б" }));
    await waitFor(() =>
      expect(calls.filter((url) => url.includes("/instrument?"))).toHaveLength(1),
    );
    expect(calls[1]).toContain("scope=source%3ASYNTH-B");
    expect(screen.getByTestId("location")).not.toHaveTextContent("capital_account=");
  },
);
test("same ISIN canonical navigation never joins by account label", async () => {
  const value = overallFixture();
  value.instruments[0].accounts[0].label = "Учебный счёт Б";
  const calls = install(value);
  setup("/v2/returns?isin=RU000A000002&capital_account=4");
  await waitFor(() => expect(calls.filter((url) => url.includes("/instrument?"))).toHaveLength(1));
  expect(calls[1]).toContain("scope=source%3ASYNTH-B");
  expect(calls[1]).toContain(`start=${april.start}&end=${april.end}`);
});
test("gold from Capital focuses only exact saved snapshot and never opens source detail", async () => {
  const calls = install();
  setup("/v2/returns?capital_account=10&gold_instrument=20#returns-gold");
  await screen.findByText(/Выбран сохранённый снимок/);
  await waitFor(() =>
    expect(document.activeElement).toHaveAttribute("data-capital-selected", "true"),
  );
  expect(document.activeElement).toHaveTextContent("Учебное золото");
  expect(calls).toEqual(["/api/returns/overall"]);
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
  expect(within(card).getByText(/проверка устарела/)).toBeVisible();
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
  expect(within(card).getByText(/конфликт данных/)).toBeVisible();
  expect(card).toHaveTextContent("9 990 ₽");
  expect(card).toHaveTextContent("не включён");
});
