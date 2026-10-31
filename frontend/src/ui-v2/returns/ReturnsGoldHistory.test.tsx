import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { GOLD_VERSION, type GoldHistory, goldPendingKey } from "./goldHistory";
import {
  goldHistoryFixture,
  goldIntentFixture,
  goldPreviewFixture,
  goldReceiptFixture,
} from "./goldHistoryFixtures";
import { ReturnsGoldHistory } from "./ReturnsGoldHistory";

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function install(
  options: {
    histories?: GoldHistory[];
    lostAck?: boolean;
    applyStatus?: number;
    holdRead?: boolean;
    wrongRead?: boolean;
    readStatus?: number;
  } = {},
) {
  const calls: { path: string; method: string; body: Record<string, unknown> | null }[] = [];
  let intent = goldIntentFixture();
  let requestId = "";
  let finish: (value: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ path, method, body });
      if (path.includes("/preview")) {
        intent = body;
        return response(goldPreviewFixture(intent));
      }
      if (path.includes("/apply")) {
        requestId = String(body.request_id);
        if (options.applyStatus)
          return response({ detail: "gold_preview_stale" }, options.applyStatus);
        if (options.lostAck) throw new Error("synthetic lost acknowledgement");
        return response(goldReceiptFixture(intent, requestId));
      }
      if (path.includes("/receipts/"))
        return response(goldReceiptFixture(intent, requestId || path.split("/").at(-1) || ""));
      if (path.endsWith("/50")) {
        if (options.readStatus)
          return response({ detail: "synthetic_read_rejected" }, options.readStatus);
        const history = goldHistoryFixture(intent);
        if (options.wrongRead) history.account_id = 999;
        if (options.holdRead)
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        return response(history);
      }
      return response({ contract_version: GOLD_VERSION, histories: options.histories ?? [] });
    }),
  );
  return {
    calls,
    finish: (history?: GoldHistory) => finish(response(history ?? goldHistoryFixture(intent))),
    intent: () => intent,
  };
}
function setup(onConfirmed?: () => Promise<unknown>) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ReturnsGoldHistory accountId={10} instrumentId={20} onConfirmed={onConfirmed} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
async function fill() {
  await screen.findByText("История операций пока не сохранена.");
  fireEvent.click(screen.getByText("Ввести или исправить историю операций"));
  fireEvent.change(screen.getByLabelText("История с"), { target: { value: "2044-01-01" } });
  fireEvent.change(screen.getByLabelText("История по"), { target: { value: "2044-03-31" } });
  fireEvent.change(screen.getByLabelText("Заявленное количество на конец истории, г"), {
    target: { value: "2" },
  });
  fireEvent.change(screen.getByLabelText("Источник: документ или запись"), {
    target: { value: "SYNTHETIC-DOCUMENT" },
  });
  fireEvent.click(screen.getByLabelText("История за указанный период полная"));
  fireEvent.click(screen.getByLabelText("На начало периода золота не было"));
  fireEvent.change(screen.getByLabelText("Дата операции"), { target: { value: "2044-01-02" } });
  fireEvent.change(screen.getByLabelText("Граммы"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Сумма операции без отдельной комиссии, ₽"), {
    target: { value: "5000" },
  });
  fireEvent.change(screen.getByLabelText("Отдельная комиссия"), {
    target: { value: "known_zero" },
  });
}
afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
test("gold new form has no private prefills or second valuation input and no POST before preview", async () => {
  const { calls } = install();
  setup();
  await screen.findByText("История операций пока не сохранена.");
  expect(screen.getByLabelText("Сумма операции без отдельной комиссии, ₽")).toHaveValue("");
  expect(screen.getByLabelText("Заявленное количество на конец истории, г")).toHaveValue("");
  expect(screen.queryByLabelText(/Текущая цена/)).toBeNull();
  expect(calls.every((call) => call.method === "GET")).toBe(true);
});
test("gold preview binds exact intent; confirmation waits for independent GET before success", async () => {
  const api = install({ holdRead: true });
  const onConfirmed = vi.fn(async () => {
    expect(sessionStorage.getItem(goldPendingKey(10, 20))).toBeNull();
  });
  setup(onConfirmed);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  const preview = await screen.findByRole("region", { name: "Предпросмотр истории золота" });
  expect(preview).toHaveTextContent("2044-03-30");
  expect(preview).toHaveTextContent("снимок месяца 2044-03-31");
  expect(preview).toHaveTextContent("Налоги не предоставлены");
  fireEvent.click(within(preview).getByRole("button", { name: "Подтвердить сохранение истории" }));
  await waitFor(() => expect(api.calls.some((call) => call.path.endsWith("/50"))).toBe(true));
  expect(screen.queryByText(/подтверждена независимым чтением/)).toBeNull();
  expect(onConfirmed).not.toHaveBeenCalled();
  const post = api.calls.find((call) => call.path.endsWith("/apply"));
  expect(post?.body).toMatchObject({ ...api.intent(), confirmation_digest: "a".repeat(64) });
  await act(async () => api.finish());
  await screen.findByText(/подтверждена независимым чтением/);
  expect(onConfirmed).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(goldPendingKey(10, 20))).toBeNull();
});
test("gold any edit invalidates preview and derived basis sends only its chosen amount field", async () => {
  const api = install();
  setup();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  await screen.findByRole("region", { name: "Предпросмотр истории золота" });
  fireEvent.change(screen.getByLabelText("Основа суммы"), {
    target: { value: "derived_unit_price" },
  });
  expect(screen.queryByRole("button", { name: "Подтвердить сохранение истории" })).toBeNull();
  expect(screen.queryByLabelText("Сумма операции без отдельной комиссии, ₽")).toBeNull();
  fireEvent.change(screen.getByLabelText("Цена за грамм без отдельной комиссии, ₽"), {
    target: { value: "2500" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  await screen.findByRole("region", { name: "Предпросмотр истории золота" });
  expect(api.intent().events[0]).toMatchObject({
    amount_basis: "derived_unit_price",
    unit_price_rub: "2500",
    amount_rub: null,
  });
});
test("gold lost ACK blocks a second POST and recovers through receipt then independent history GET", async () => {
  const api = install({ lostAck: true });
  setup();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение истории" }));
  await screen.findByText(/Сохранение не подтверждено/);
  expect(screen.getByRole("button", { name: "Подтвердить сохранение истории" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Проверить результат сохранения" }));
  await screen.findByText(/подтверждена независимым чтением/);
  expect(api.calls.filter((call) => call.path.endsWith("/apply"))).toHaveLength(1);
  expect(api.calls.some((call) => call.path.includes("/receipts/"))).toBe(true);
  expect(api.calls.at(-1)?.path).toMatch(/\/50$/);
});
test("gold pending receipt survives remount with GET-only recovery and no new request dispatch", async () => {
  sessionStorage.setItem(goldPendingKey(10, 20), "gold_pending_synthetic");
  const api = install();
  setup();
  await screen.findByRole("button", { name: "Проверить результат сохранения" });
  fireEvent.click(screen.getByText("Ввести или исправить историю операций"));
  expect(screen.getByRole("button", { name: "Предпросмотр истории" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Проверить результат сохранения" }));
  await screen.findByText(/подтверждена независимым чтением/);
  expect(api.calls.every((call) => call.method === "GET")).toBe(true);
});
test("gold stale preview is a confirmed rejection, requires new preview and never retries apply", async () => {
  const api = install({ applyStatus: 409 });
  setup();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение истории" }));
  await screen.findByText(/gold_preview_stale/);
  expect(screen.queryByRole("button", { name: "Подтвердить сохранение истории" })).toBeNull();
  expect(api.calls.filter((call) => call.path.endsWith("/apply"))).toHaveLength(1);
  expect(sessionStorage.getItem(goldPendingKey(10, 20))).toBeNull();
});
test("gold mismatched independent readback never claims success and remains recovery-only", async () => {
  const api = install({ wrongRead: true });
  setup();
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение истории" }));
  await screen.findByText(/Сохранение не подтверждено/);
  expect(screen.queryByText(/подтверждена независимым чтением/)).toBeNull();
  expect(screen.getByRole("button", { name: "Подтвердить сохранение истории" })).toBeDisabled();
  expect(api.calls.filter((call) => call.path.endsWith("/apply"))).toHaveLength(1);
});

test("gold readback rejection after acknowledged save remains recovery-only", async () => {
  const api = install({ readStatus: 409 });
  const onConfirmed = vi.fn(async () => {});
  setup(onConfirmed);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить сохранение истории" }));
  await screen.findByText(/Сохранение не подтверждено/);
  expect(onConfirmed).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(goldPendingKey(10, 20))).not.toBeNull();
  expect(screen.getByRole("button", { name: "Подтвердить сохранение истории" })).toBeDisabled();
  expect(api.calls.filter((call) => call.path.endsWith("/apply"))).toHaveLength(1);
});
test("gold correction explicitly loads existing revision and requires reason without changing saved valuation", async () => {
  const prior = goldHistoryFixture();
  const api = install({ histories: [prior] });
  setup();
  await screen.findByText(/Сохранённая история · ревизия 1/);
  expect(screen.getByLabelText("Сумма операции без отдельной комиссии, ₽")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Изменить сохранённую историю" }));
  expect(screen.getByLabelText("Сумма операции без отдельной комиссии, ₽")).toHaveValue("5000.00");
  const reason = screen.getByLabelText("Причина исправления");
  expect(reason).toBeRequired();
  fireEvent.change(reason, { target: { value: "Synthetic document correction" } });
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр истории" }));
  await screen.findByRole("region", { name: "Предпросмотр истории золота" });
  expect(api.intent().expected_revision).toBe(1);
  expect(api.intent().change_reason).toBe("Synthetic document correction");
});

test("gold saved DRAFT quote keeps its actual quote date and separate snapshot date", async () => {
  const history = goldHistoryFixture();
  if (!history.valuation) throw new Error("synthetic quote missing");
  history.valuation.month_status = "draft";
  history.valuation.provisional = true;
  history.result.valuation_provisional = true;
  install({ histories: [history] });
  setup();
  const quote = await screen.findByText(/Оценка.*2044-03-30/);
  expect(quote).toHaveTextContent("предварительная");
  expect(quote).toHaveTextContent("снимок месяца 2044-03-31");
  expect(screen.queryByLabelText(/Новая цена/)).toBeNull();
});

test("gold missing quote preserves independently known realized result without a valuation date", async () => {
  const history = goldHistoryFixture();
  history.valuation = null;
  history.result.total_result_kopecks = null;
  history.result.unrealized_result_kopecks = null;
  history.result.valuation_date = null;
  history.result.valuation_basis = null;
  history.result.reason_codes = ["gold_quote_unavailable"];
  history.result.total_reason_codes = ["gold_quote_unavailable"];
  history.result.unrealized_reason_codes = ["gold_quote_unavailable"];
  install({ histories: [history] });
  setup();
  const realized = await screen.findByText("От продажи");
  expect(realized.nextElementSibling).toHaveTextContent("0,00 ₽");
  expect(screen.getByText(/Операции учтены по/)).toHaveTextContent("оценка не подтверждена");
  expect(screen.queryByText("Изменение стоимости остатка")).toBeNull();
  expect(screen.queryByText("Общий результат", { selector: "dt" })).toBeNull();
});
