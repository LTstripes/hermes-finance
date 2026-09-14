import { onlineManager, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatMoney } from "../lib/format";
import { createQueryClient, queryKeys } from "../queryClient";
import { makeUiV2Workflow, uiV2Months } from "../test/uiV2Fixtures";
import { UiV2ErrorBoundary } from "../ui-v2/UiV2Entry";
import UiV2Page from "../ui-v2/UiV2Page";

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="test-location">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
      <button type="button" onClick={() => navigate(-1)}>
        Назад в тесте
      </button>
    </>
  );
}

function setup(path = "/v2", response = makeUiV2Workflow()) {
  const client = createQueryClient();
  const reads: string[] = [];
  const state = {
    months: uiV2Months,
    workflow: response,
    monthsError: false,
    workflowError: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = options?.method ?? "GET";
      reads.push(`${method} ${url.pathname}`);
      if (method !== "GET") throw new Error(`Unexpected write: ${method}`);
      let data: unknown;
      let status = 200;
      if (url.pathname === "/api/health") data = { status: "ok", version: "synthetic" };
      else if (url.pathname === "/api/months") {
        data = state.months;
        status = state.monthsError ? 503 : 200;
      } else if (/^\/api\/months\/(12|91)\/close-workflow$/.test(url.pathname)) {
        data = url.pathname.includes("/91/") ? makeUiV2Workflow({ monthId: 91 }) : state.workflow;
        status = state.workflowError ? 503 : 200;
      } else throw new Error(`Unexpected API: ${url.pathname}`);
      return new Response(
        JSON.stringify(
          status === 200
            ? data
            : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
        ),
        { status, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <Routes>
            <Route path="v2" element={<UiV2Page />} />
            <Route path="months/:monthId/close" element={<h1>Текущий маршрут</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { state, client, reads, mount };
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});
afterEach(() => {
  onlineManager.setOnline(true);
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("pins the newest calendar month in the URL and renders distinct exact financial values", async () => {
  const { mount, reads } = setup();
  mount();
  expect((await screen.findByTestId("v2-capital")).textContent).toBe(formatMoney("2846500.00"));
  expect(screen.getByTestId("v2-passive-actual").textContent).toBe(formatMoney("17500.00"));
  expect(screen.getByTestId("v2-passive-forecast").textContent).toBe(formatMoney("21000.00"));
  expect(screen.getByTestId("test-location")).toHaveTextContent("/v2?month=12");
  expect(screen.getByRole("link", { name: "Вернуться к текущему интерфейсу →" })).toHaveAttribute(
    "href",
    "/months/12",
  );
  expect(screen.getByText(/Не обещание выплаты/)).toBeVisible();
  expect(screen.getByText(/Без недвижимости и ипотеки/)).toBeVisible();
  expect(
    reads.every((read) => /^GET \/api\/(health|months|months\/12\/close-workflow)$/.test(read)),
  ).toBe(true);
});

it("uses server readiness and progress, not warning states or a client checklist", async () => {
  const workflow = makeUiV2Workflow();
  workflow.progress = { completed_or_skipped: 3, total_applicable: 8 };
  const { mount } = setup("/v2?month=12", workflow);
  mount();
  expect(await screen.findByTestId("v2-progress")).toHaveTextContent("3 из 8");
  expect(screen.getByTestId("v2-blockers")).toHaveTextContent("0");
  expect(screen.getByRole("heading", { name: "Можно перейти к итоговой проверке" })).toBeVisible();
  expect(screen.getByTestId("v2-primary-action")).toHaveAttribute(
    "href",
    "/months/12/close#alfa_baseline",
  );
});

it("selecting a step focuses its actionable panel and preserves the month in the v1 handoff", async () => {
  const { mount, reads } = setup("/v2?month=12");
  mount();
  await screen.findByTestId("v2-capital");
  const count = reads.length;
  fireEvent.click(screen.getByTestId("v2-step-actual_payouts"));
  await waitFor(() => expect(document.getElementById("v2-action")).toHaveFocus());
  expect(reads).toHaveLength(count);
  expect(screen.getByTestId("v2-primary-action")).toHaveAttribute(
    "href",
    "/months/12/close#actual_payouts",
  );
  expect(screen.getByRole("link", { name: "Вернуться к текущему интерфейсу →" })).toHaveAttribute(
    "href",
    "/months/12/close#actual_payouts",
  );
  fireEvent.click(screen.getByTestId("v2-primary-action"));
  expect(await screen.findByRole("heading", { name: "Текущий маршрут" })).toBeVisible();
  fireEvent.click(screen.getByText("Назад в тесте"));
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
  expect(screen.getByTestId("test-location")).toHaveTextContent("/v2?month=12&step=actual_payouts");
});

it("renders a closed month with a view-only next-month handoff and no close/reopen mutation", async () => {
  const { mount, reads } = setup("/v2?month=91");
  mount();
  expect(await screen.findByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible();
  expect(screen.getByTestId("v2-primary-action")).toHaveAttribute(
    "href",
    "/months/91/close#next_month_outlook",
  );
  expect(screen.queryByRole("button", { name: /Закрыть|Открыть заново/ })).toBeNull();
  expect(reads.every((read) => read.startsWith("GET "))).toBe(true);
});

it.each(["999", "", "0", "12&month=91"])(
  "never substitutes a month for the explicit invalid/missing URL %s",
  async (query) => {
    const { mount, reads } = setup(`/v2?month=${query}`);
    mount();
    expect(await screen.findByRole("heading", { name: "Месяц по ссылке не найден" })).toBeVisible();
    expect(reads.some((read) => read.includes("close-workflow"))).toBe(false);
    expect(screen.queryByTestId("v2-capital")).toBeNull();
  },
);

it("supports an empty database without manufactured zero metrics", async () => {
  const { mount, state } = setup();
  state.months = [];
  mount();
  expect(await screen.findByRole("heading", { name: "Начни с первого месяца" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Создать первый месяц →" })).toHaveAttribute(
    "href",
    "/months",
  );
  expect(screen.queryByTestId("v2-capital")).toBeNull();
});

it("distinguishes a real zero from unavailable results while keeping workflow usable", async () => {
  const { mount, state, client } = setup("/v2?month=12", makeUiV2Workflow({ zeroIncome: true }));
  mount();
  expect((await screen.findByTestId("v2-passive-actual")).textContent).toBe(formatMoney("0.00"));
  state.workflow = makeUiV2Workflow({ unavailable: true });
  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.monthCloseWorkflow(12) });
  });
  expect(await screen.findByRole("heading", { name: "Итоги пока недоступны" })).toBeVisible();
  expect(screen.queryByTestId("v2-capital")).toBeNull();
  expect(screen.getByTestId("v2-primary-action")).toBeVisible();
});

it.each(["month", "review", "version"])(
  "rejects a mismatched %s response instead of relabelling it",
  async (kind) => {
    const workflow = makeUiV2Workflow();
    if (kind === "month") workflow.month.id = 999;
    if (kind === "review" && workflow.final_review.available)
      workflow.final_review.month_header.id = 999;
    if (kind === "version")
      (workflow as unknown as { contract_version: string }).contract_version = "future_unsupported";
    const { mount } = setup("/v2?month=12", workflow);
    mount();
    expect(
      await screen.findByRole("heading", { name: "Не удалось получить состояние месяца" }),
    ).toBeVisible();
    expect(screen.queryByTestId("v2-capital")).toBeNull();
  },
);

it("hides cached results when revalidation fails and recovers with explicit retry", async () => {
  const { mount, state, client } = setup("/v2?month=12");
  mount();
  await screen.findByTestId("v2-capital");
  state.workflowError = true;
  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.monthCloseWorkflow(12) });
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Не удалось получить состояние месяца",
  );
  expect(screen.queryByTestId("v2-capital")).toBeNull();
  expect(screen.queryByTestId("v2-primary-action")).toBeNull();
  state.workflowError = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
});

it("hides cached results while offline revalidation is paused", async () => {
  const { mount, client, reads } = setup("/v2?month=12");
  mount();
  await screen.findByTestId("v2-capital");
  const readCount = reads.length;

  act(() => {
    onlineManager.setOnline(false);
    void client.invalidateQueries({ queryKey: queryKeys.monthCloseWorkflow(12) });
  });

  await waitFor(() => expect(screen.queryByTestId("v2-capital")).toBeNull());
  expect(document.getElementById("v2-main")).toHaveAttribute("aria-busy", "true");
  expect(
    screen.getByText("Ждём подключения, чтобы подтвердить состояние выбранного месяца…"),
  ).toBeVisible();
  expect(reads).toHaveLength(readCount);

  await act(async () => {
    onlineManager.setOnline(true);
  });
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
});

it("recovers a failed month list without querying a guessed month", async () => {
  const { mount, state, reads } = setup();
  state.monthsError = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить месяцы");
  expect(reads.some((read) => read.includes("close-workflow"))).toBe(false);
  state.monthsError = false;
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  expect(await screen.findByTestId("v2-capital")).toBeVisible();
});

it("explains unknown step links without inventing a new recommendation", async () => {
  const workflow = makeUiV2Workflow();
  workflow.recommended_step_id = null;
  const { mount } = setup("/v2?month=12&step=unknown", workflow);
  mount();
  await screen.findByTestId("v2-capital");
  expect(screen.getByTestId("v2-primary-action")).toHaveAttribute(
    "href",
    "/months/12/close#final_review_close",
  );
});

describe("UI v2 isolation", () => {
  it("offers a v1 escape when the lazy page crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Broken(): never {
      throw new Error("synthetic component failure");
    }
    render(
      <MemoryRouter>
        <UiV2ErrorBoundary>
          <Broken />
        </UiV2ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Новый интерфейс не загрузился");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/");
  });
});
