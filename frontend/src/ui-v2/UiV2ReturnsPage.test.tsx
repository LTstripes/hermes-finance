import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import UiV2ReturnsPage from "./UiV2ReturnsPage";
import { ReturnsLegacyRedirect } from "./returns/ReturnsLegacyRedirect";
import {
  contextFixture,
  detailFixture,
  longHistoryContext,
  longHistoryOverview,
  longHistoryPeriods,
  may,
  overviewFixture,
} from "./returns/fixtures";

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
          url.pathname.endsWith("context")
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
function setup(path = "/v2/returns") {
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
