import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import {
  basketFixture,
  contextFixture,
  detailFixture,
  longHistoryContext,
  longHistoryOverview,
  longHistoryPeriods,
  may,
  overviewFixture,
} from "./returns/fixtures";
import { ReturnsLegacyRedirect } from "./returns/ReturnsLegacyRedirect";
import UiV2ReturnsPage from "./UiV2ReturnsPage";

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.search}
      {location.hash}
    </output>
  );
}
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function install(override?: (url: URL) => Promise<Response> | undefined) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = new URL(input, "http://localhost");
      calls.push(url.pathname + url.search);
      const custom = override?.(url);
      if (custom) return custom;
      const scope = url.searchParams.get("scope") ?? "source:SYNTH-A";
      const period = {
        start: url.searchParams.get("start") ?? may.start,
        end: url.searchParams.get("end") ?? may.end,
      };
      return Promise.resolve(
        response(
          url.pathname.endsWith("basket")
            ? basketFixture(period, url.searchParams.get("categories") ?? undefined)
            : url.pathname.endsWith("context")
              ? contextFixture
              : url.pathname.endsWith("instrument")
                ? detailFixture(scope, period, url.searchParams.get("isin") ?? undefined)
                : overviewFixture(scope, period),
        ),
      );
    }),
  );
  return calls;
}
function setup(path = "/v2/returns?scope=source:SYNTH-A") {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/v2/returns" element={<UiV2ReturnsPage />} />
          <Route path="/v2/capital/monthly-returns" element={<ReturnsLegacyRedirect />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

test("unscoped CLOSED history opens the accepted portfolio even without saved statements", async () => {
  install((url) =>
    url.pathname.endsWith("context")
      ? Promise.resolve(
          response({
            ...contextFixture,
            accounts: contextFixture.accounts.filter((a) => a.basis === "accepted"),
          }),
        )
      : undefined,
  );
  setup("/v2/returns");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("start=2030-04-30"));
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.getByRole("combobox", { name: "Счёт" })).toHaveValue("portfolio");
  expect(screen.getByRole("combobox", { name: "Представление" })).toHaveValue("accepted");
  expect(screen.getByRole("link", { name: "Открыть отчёты месяцев" })).toHaveAttribute(
    "href",
    "/v2/data/months",
  );
});

test("refresh reads context, overview and basket once in parallel and exposes context failure", async () => {
  let hold = false;
  let complete: (response: Response) => void = () => {};
  const calls = install((url) =>
    hold && url.pathname.endsWith("context")
      ? new Promise<Response>((resolve) => {
          complete = resolve;
        })
      : undefined,
  );
  setup();
  await screen.findByRole("region", { name: "Результат периода" });
  hold = true;
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await waitFor(() => {
    expect(calls.filter((c) => c.includes("/overview?"))).toHaveLength(2);
    expect(calls.filter((c) => c.includes("/basket?"))).toHaveLength(2);
  });
  expect(screen.queryByRole("region", { name: "Результат периода" })).toBeNull();
  await act(async () => complete(response(contextFixture)));
  await screen.findByRole("region", { name: "Результат периода" });
  expect(calls.filter((c) => c.includes("/overview?"))).toHaveLength(2);
  expect(calls.filter((c) => c.includes("/basket?"))).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await act(async () => complete(response({}, 503)));
  await screen.findByText("Не удалось загрузить выбранную корзину.");
  expect(screen.queryByRole("region", { name: "Результат периода" })).toBeNull();
});

test("brokerage selector excludes accepted accounts until explicitly switched; deep links stay valid", async () => {
  install();
  setup();
  await screen.findByRole("region", { name: "Результат периода" });
  const accounts = screen.getByRole("combobox", { name: "Счёт" });
  expect(within(accounts).queryByRole("option", { name: "Общий портфель" })).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "Представление" }), {
    target: { value: "accepted" },
  });
  await waitFor(() => expect(accounts).toHaveValue("portfolio"));
  expect(within(accounts).getByRole("option", { name: "Общий портфель" })).toBeVisible();
  expect(within(accounts).queryByRole("option", { name: "Учебный счёт А" })).toBeNull();
});

test("proven alias URL normalizes only scope and preserves exact period/hash", async () => {
  const calls = install((url) =>
    url.pathname.endsWith("context")
      ? Promise.resolve(
          response({
            ...contextFixture,
            scope_aliases: { "source:OLD-A": "source:SYNTH-A" },
          }),
        )
      : undefined,
  );
  setup("/v2/returns?scope=source:OLD-A&start=2030-03-31&end=2030-04-30#details");
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.getByTestId("location")).toHaveTextContent(
    "scope=source%3ASYNTH-A&start=2030-03-31&end=2030-04-30#details",
  );
  expect(calls.some((c) => c.includes("OLD-A") && !c.endsWith("context"))).toBe(false);
});

test("duplicate scope containing a proven alias stays invalid and never selects the first account", async () => {
  const calls = install((url) =>
    url.pathname.endsWith("context")
      ? Promise.resolve(
          response({
            ...contextFixture,
            scope_aliases: { "source:OLD-A": "source:SYNTH-A" },
          }),
        )
      : undefined,
  );
  const path =
    "/v2/returns?scope=source:OLD-A&scope=source:SYNTH-B&start=2030-03-31&end=2030-04-30";
  setup(path);
  await screen.findByRole("option", { name: "Учебный счёт А" });
  expect(screen.getByTestId("location")).toHaveTextContent(path.slice(path.indexOf("?")));
  expect(screen.queryByRole("region", { name: "Результат периода" })).toBeNull();
  expect(calls.filter((c) => c.includes("/overview"))).toHaveLength(0);
});

test("partial history shows server RUB subtotal with coverage and no invented rate", async () => {
  install((url) => {
    if (!url.pathname.endsWith("overview")) return;
    const data = overviewFixture();
    data.available_months_total = {
      period: { start: "2030-03-31", end: "2030-06-30" },
      partial: true,
      pnl: { ...data.selected.pnl, value: "8000", method: "available_calendar_months" },
      included: [
        { start: "2030-03-31", end: "2030-04-30" },
        { start: "2030-05-31", end: "2030-06-30" },
      ],
      missing: [
        { period: { start: "2030-04-30", end: "2030-05-31" }, reason_codes: ["missing_endpoint"] },
      ],
      covered_months: 2,
      total_months: 3,
    };
    return Promise.resolve(response(data));
  });
  setup();
  const card = await screen.findByRole("region", { name: "За доступные месяцы" });
  expect(card).toHaveTextContent("За доступные месяцы · 2 из 3");
  expect(card).toHaveTextContent("+80 ₽");
  expect(card).not.toHaveTextContent("%");
  expect(screen.queryByRole("region", { name: "За всю историю" })).toBeNull();
  const info = within(card).getByLabelText("Подробнее: Покрытие доступных месяцев");
  fireEvent.click(info);
  expect(within(card).getByText("Не хватает стоимости на границе периода.")).toBeVisible();
  expect(within(card).getByText("Не учтён: 30.04.2030 — 31.05.2030")).toBeVisible();
});

test("missing name is explained in table, tops and lazy detail without a lookup", async () => {
  const calls = install((url) => {
    if (url.pathname.endsWith("overview")) {
      const data = overviewFixture();
      data.instruments[0].name = data.instruments[0].isin;
      return Promise.resolve(response(data));
    }
    if (url.pathname.endsWith("instrument")) {
      const data = detailFixture("source:SYNTH-A", may, "RU000A000001");
      data.name = data.isin;
      return Promise.resolve(response(data));
    }
  });
  setup();
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.getAllByLabelText("Подробнее: Название RU000A000001")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: /▸ RU000A000001/ }));
  await screen.findByText("Количество: 10 → 0");
  expect(screen.getAllByLabelText("Подробнее: Название RU000A000001")).toHaveLength(3);
  expect(calls.every((c) => c.startsWith("/api/returns/"))).toBe(true);
});

test("tops show the name first, ISIN second and an honest single ISIN fallback", async () => {
  install((url) => {
    if (!url.pathname.endsWith("overview")) return;
    const data = overviewFixture();
    data.instruments[1].name = data.instruments[1].isin;
    return Promise.resolve(response(data));
  });
  setup();
  const tops = await screen.findByRole("region", { name: "Лидеры и отстающие" });
  const rows = within(tops).getAllByRole("listitem");
  expect(rows[0].querySelector("span")?.firstChild?.textContent).toBe("Северные технологии");
  expect(rows[0].querySelector("small")).toHaveTextContent("RU000A000001");
  expect(rows[1]).toHaveTextContent("RU000A000002");
  expect(rows[1].querySelector("small")).toBeNull();
  expect(rows).toHaveLength(3);
});

test("source seam context stays behind each metric's details while values remain visible", async () => {
  install((url) => {
    if (!url.pathname.endsWith("overview")) return;
    const data = overviewFixture();
    for (const [key, value] of Object.entries({
      pnl: "2700",
      rate: "0.027",
      coupons: "300",
      dividends: "200",
    })) {
      const metric = data.selected[key as "pnl" | "rate" | "coupons" | "dividends"];
      metric.value = value;
      metric.reason_codes = ["seam_mismatch"];
    }
    return Promise.resolve(response(data));
  });
  setup();
  const result = await screen.findByRole("region", { name: "Результат периода" });
  expect(result).toHaveTextContent("+27 ₽");
  expect(result).toHaveTextContent("2,70%");
  for (const name of ["Результат периода", "Полученные купоны", "Полученные дивиденды"]) {
    const card = screen.getByRole("region", { name });
    const info = within(card).getAllByText("Остатки соседних периодов расходятся.");
    for (const explanation of info) expect(explanation).not.toBeVisible();
    for (const control of within(card).getAllByLabelText(/^Подробнее:/)) {
      expect(control).toHaveTextContent("ⓘ");
      fireEvent.click(control);
    }
    for (const explanation of info) expect(explanation).toBeVisible();
  }
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("account reconciliation explains the whole account in metric details", async () => {
  install((url) => {
    if (!url.pathname.endsWith("overview")) return;
    const data = overviewFixture();
    data.selected.pnl = {
      ...data.selected.pnl,
      value: "12345",
      method: "source_account_reconciliation",
    };
    return Promise.resolve(response(data));
  });
  setup();
  const card = await screen.findByRole("region", { name: "Результат периода" });
  expect(card).toHaveTextContent("+123,45");
  const explanation = within(card).getByText(/Результат всего счёта за указанные даты/);
  expect(explanation).not.toBeVisible();
  fireEvent.click(within(card).getByLabelText("Подробнее: Результат периода"));
  expect(explanation).toBeVisible();
  expect(explanation).toHaveTextContent("денежный остаток и операции счёта");
  expect(within(card).queryByText(/Результат бумаги/)).not.toBeInTheDocument();
});

test("pins CLOSED default in URL and loads trades only on expansion", async () => {
  const calls = install();
  setup();
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.getByTestId("location")).toHaveTextContent("start=2030-04-30&end=2030-05-31");
  expect(calls.filter((c) => c.includes("/instrument?"))).toHaveLength(0);
  expect(
    within(screen.getByRole("region", { name: "За всю историю" })).getByText("—"),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Горизонт — проданная/ }));
  await screen.findByText("Продажа");
  expect(screen.getByText("Количество: 10 → 0")).toBeVisible();
  expect(calls.filter((c) => c.includes("/instrument?"))).toHaveLength(1);
  fireEvent.change(screen.getByRole("combobox", { name: "Тип" }), { target: { value: "bond" } });
  expect(screen.queryByRole("button", { name: /Северные технологии/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Учебная облигация/ })).toBeVisible();
});

test("late account response cannot populate the new scope; error hides cached financial results", async () => {
  let resolveA: (r: Response) => void = () => {};
  let fail = false;
  install((url) => {
    if (!url.pathname.endsWith("overview")) return;
    if (fail) return Promise.resolve(response({}, 503));
    if (url.searchParams.get("scope") === "source:SYNTH-A")
      return new Promise((resolve) => {
        resolveA = resolve;
      });
  });
  setup();
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:SYNTH-A"),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Счёт" }), {
    target: { value: "source:SYNTH-B" },
  });
  const result = await screen.findByRole("region", { name: "Результат периода" });
  expect(result).toHaveTextContent("−1 750,25");
  await act(async () => resolveA(response(overviewFixture())));
  expect(result).toHaveTextContent("−1 750,25");
  fail = true;
  fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Результат периода" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Подробнее о данных"));
  expect(screen.getByRole("link", { name: "Открыть диагностику выписок" })).toHaveAttribute(
    "href",
    "/v2/capital/monthly-returns?diagnostics=1&source_account=SYNTH-B",
  );
});

test("legacy bond deep link preserves exact account and month", async () => {
  install();
  setup("/v2/capital/monthly-returns?source_account=SYNTH-B&bond_period=2030-04-01#bond-slice");
  await screen.findByRole("region", { name: "Результат периода" });
  expect(screen.getByTestId("location")).toHaveTextContent(
    "scope=source%3ASYNTH-B&start=2030-03-31&end=2030-04-30",
  );
});

test("mismatched server account/period is an error, never a numeric fallback", async () => {
  install((url) =>
    url.pathname.endsWith("overview")
      ? Promise.resolve(response(overviewFixture("source:WRONG")))
      : undefined,
  );
  setup();
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: "Результат периода" })).not.toBeInTheDocument();
});

test.each(["&bond_period=history", ""])(
  "legacy history link '%s' retains full dates and ISIN",
  async (selection) => {
    install();
    setup(
      `/v2/capital/monthly-returns?source_account=SYNTH-A${selection}&bond_isin=RU000A000002#bond-slice`,
    );
    await screen.findByText("Продажа");
    expect(screen.getByTestId("location")).toHaveTextContent("isin=RU000A000002");
    expect(screen.getByTestId("location")).toHaveTextContent("start=2030-03-31&end=2030-05-31");
    expect(screen.getByTestId("location")).toHaveTextContent("#returns-instruments");
  },
);

test("24 months keep an earlier selection visible after loading and period changes", async () => {
  install((url) => {
    if (url.pathname.endsWith("context")) return Promise.resolve(response(longHistoryContext));
    if (url.pathname.endsWith("overview"))
      return Promise.resolve(
        response(
          longHistoryOverview(url.searchParams.get("scope") ?? "", {
            start: url.searchParams.get("start") ?? "",
            end: url.searchParams.get("end") ?? "",
          }),
        ),
      );
  });
  setup();
  await screen.findByRole("region", { name: "Результат периода" });
  fireEvent.click(screen.getByRole("button", { name: "Более ранние месяцы" }));
  fireEvent.click(
    within(screen.getByRole("group", { name: "История результата в рублях" })).getByRole("button", {
      name: /янв.*2029/,
    }),
  );
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("end=2029-01-31"));
  await screen.findByRole("region", { name: "Результат периода" });
  const selectedBar = () =>
    within(screen.getByRole("group", { name: "История результата в рублях" })).getByRole("button", {
      name: /янв.*2029/,
    });
  expect(selectedBar()).toHaveAttribute("aria-pressed", "true");
  fireEvent.change(screen.getByRole("combobox", { name: "Период" }), {
    target: { value: `${longHistoryPeriods[12].start}/${longHistoryPeriods[12].end}` },
  });
  await screen.findByRole("region", { name: "Результат периода" });
  fireEvent.change(screen.getByRole("combobox", { name: "Период" }), {
    target: { value: `${longHistoryPeriods[0].start}/${longHistoryPeriods[0].end}` },
  });
  await screen.findByRole("region", { name: "Результат периода" });
  expect(selectedBar()).toHaveAttribute("aria-pressed", "true");
});

test("without CLOSED months source intervals remain selectable without silently selecting DRAFT", async () => {
  install((url) =>
    url.pathname.endsWith("context")
      ? Promise.resolve(response({ ...contextFixture, default_period: null, closed_periods: [] }))
      : undefined,
  );
  setup();
  await screen.findByText(/Закрытых месяцев пока нет/);
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:SYNTH-A"),
  );
  // Flush post-context URL effects: source periods are offered for manual
  // selection, not silently adopted in place of a missing CLOSED default.
  await act(async () => {});
  expect(screen.getByTestId("location")).not.toHaveTextContent("start=");
  expect(screen.getByTestId("location")).not.toHaveTextContent("end=");
  expect(screen.queryByRole("region", { name: "Результат периода" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Подробнее о данных"));
  expect(screen.getByRole("link", { name: "Открыть диагностику выписок" })).toHaveAttribute(
    "href",
    "/v2/capital/monthly-returns?diagnostics=1&source_account=SYNTH-A",
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Период" }), {
    target: { value: `${may.start}/${may.end}` },
  });
  await screen.findByRole("region", { name: "Результат периода" });
});
