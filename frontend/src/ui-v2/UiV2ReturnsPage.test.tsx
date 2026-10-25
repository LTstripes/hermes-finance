import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import UiV2ReturnsPage from "./UiV2ReturnsPage";
import { ReturnsLegacyRedirect } from "./returns/ReturnsLegacyRedirect";
import { contextFixture, detailFixture, may, overviewFixture } from "./returns/fixtures";

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
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

test("legacy history and ISIN select the full dated interval and expand only that paper", async () => {
  install();
  setup(
    "/v2/capital/monthly-returns?source_account=SYNTH-A&bond_period=history&bond_isin=RU000A000002#bond-slice",
  );
  await screen.findByText("Продажа");
  expect(screen.getByTestId("location")).toHaveTextContent("isin=RU000A000002");
  expect(screen.getByTestId("location")).toHaveTextContent("start=2030-03-31&end=2030-05-31");
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
  fireEvent.change(screen.getByRole("combobox", { name: "Период" }), {
    target: { value: `${may.start}/${may.end}` },
  });
  await screen.findByRole("region", { name: "Результат периода" });
});
