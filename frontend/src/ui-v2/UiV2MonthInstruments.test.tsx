import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useSearchParams } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { SourcePayoutPreview } from "../api/sourcePayoutPreview";
import { event, ISIN, metric, source } from "../test/sourceInstrumentFixtures";
import { UiV2MonthInstruments } from "./UiV2MonthInstruments";
import { money, rate } from "./SourceInstrumentDetail";

const STOCK = "RU000STOCK01";
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
function instruments(account = "SYNTH-01") {
  const data = source(account);
  const stock = structuredClone(data.instruments[0]);
  stock.isin = STOCK;
  stock.source_name = "Синтетическая акция";
  stock.instrument_type = "stock";
  stock.analysis.pnl = { ...metric(10001), status: "supported" };
  stock.analysis.modified_dietz = {
    ...stock.analysis.modified_dietz,
    value: "0.10001",
    status: "supported",
  };
  stock.analysis.statement_estimate.pnl.value = null;
  stock.analysis.statement_estimate.modified_dietz.value = null;
  stock.analysis.components.dividends = metric(0);
  data.instruments.push(stock);
  return data;
}
function preview(account = "SYNTH-01", isin = ISIN, asOf = "2030-05-31"): SourcePayoutPreview {
  const row = {
    identity_key: "future-1",
    event_kind: "coupon",
    payment_date: "2030-07-01",
    provider_status: "ok",
    source_method: "GetBondCoupons",
    per_unit_amount: "1.23",
    currency: "RUB",
    announced_amount_kopecks: "9007199254740993",
    personal_tax_known: false as const,
    status: "future" as const,
    countable_future: true,
    actual_event_keys: [],
    reason_codes: [],
  };
  return {
    source_account: account,
    native_source_account: `${account}-000`,
    isin,
    as_of: asOf,
    authority: "provisional",
    financial_authority: "none",
    account_id: null,
    instrument_id: 1,
    quantity: "2.5",
    quantity_authority: "source_observed",
    assumptions: ["fixed_source_quantity_not_entitlement"],
    quantity_references: ["position:1:0:closing"],
    source_references: source().instruments[0].analysis.source_references,
    dependency_fingerprint: "source-mapping-1",
    reason_codes: [],
    provider: "t_invest",
    instrument_uid: "accepted-uid",
    actuals: [
      {
        ...event({
          event_key: "actual-1",
          isin,
          effective_isin: isin,
          native_source_account: `${account}-000`,
          event_date: "2030-06-15",
        }),
        net_payout_kopecks: "1234",
        gross_payout_kopecks: null,
        withheld_tax_kopecks: null,
      },
    ],
    reconciliation_reasons: [],
    rows: [
      row,
      {
        ...row,
        identity_key: "possible-1",
        payment_date: "2030-06-15",
        status: "possible_paid",
        countable_future: false,
        actual_event_keys: ["actual-1"],
        reason_codes: ["actual_provider_identity_unproven"],
      },
      {
        ...row,
        identity_key: null,
        status: "tentative",
        countable_future: false,
        announced_amount_kopecks: null,
      },
    ],
    failures: [],
  };
}
function Harness({ payoutsOnly = false }: { payoutsOnly?: boolean }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const account = params.get("source_account") ?? "SYNTH-01";
  return (
    <>
      <button type="button" onClick={() => setParams({ source_account: "SYNTH-02" })}>
        Другой счёт
      </button>
      <button
        type="button"
        onClick={() => setParams({ source_account: "SYNTH-01", panel: "payouts" })}
      >
        Первый счёт
      </button>
      <output aria-label="URL">
        {params.toString()}
        {location.hash}
      </output>
      <UiV2MonthInstruments
        payoutsOnly={payoutsOnly}
        key={account}
        monthId={1}
        year={2030}
        month={5}
        account={account}
        sourceVersion="source-head-1"
      />
    </>
  );
}
function setup(path = "/v2/close?source_account=SYNTH-01", payoutsOnly = false) {
  const state = {
    reply: null as
      | null
      | ((payload: { source_account: string; isin: string; as_of: string }) => Promise<Response>),
    readReply: null as null | (() => Response),
  };
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/source-returns/quantity-bases")
      return json({
        source_account: url.searchParams.get("source_account"),
        native_source_account: `${url.searchParams.get("source_account")}-000`,
        isin: url.searchParams.get("isin"),
        on_or_before: url.searchParams.get("on_or_before"),
        authority: "provisional",
        financial_authority: "none",
        bases: [
          {
            as_of: "2030-04-30",
            quantity: url.searchParams.get("isin") === STOCK ? "7" : "2.5",
            quantity_references: ["position:1:0:closing"],
            reason_codes: [],
          },
        ],
      });
    if (url.pathname === "/api/source-returns/instruments") {
      const data = instruments(url.searchParams.get("source_account") ?? "");
      if (payoutsOnly) data.instruments[0].analysis.events = [event({})];
      return state.readReply?.() ?? json(data);
    }
    if (url.pathname.endsWith("/payout-preview")) {
      const payload = JSON.parse(String(init?.body));
      return state.reply
        ? state.reply(payload)
        : json(preview(payload.source_account, payload.isin, payload.as_of));
    }
    throw new Error(`Unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Harness payoutsOnly={payoutsOnly} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, fetcher, client, state };
}
const posts = (fetcher: ReturnType<typeof setup>["fetcher"]) =>
  fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
afterEach(() => vi.unstubAllGlobals());

test("payout entry exposes source observations with unknown tax separately and reuses explicit T-Invest preview", async () => {
  const { fetcher } = setup("/v2/close?panel=payouts&month=1&source_account=SYNTH-01", true);
  const observations = await screen.findByRole("region", { name: "Наблюдения выплат источника" });
  expect(observations).toHaveTextContent("не принятые финансовые записи");
  expect(observations).toHaveTextContent("Нетто по источнику: 12,34 ₽");
  expect(observations).toHaveTextContent("Налог: неизвестен");
  expect(
    within(observations).getByRole("link", { name: "Рассмотрение и сверка выписки" }),
  ).toHaveAttribute("href", "#month-source-review");
  expect(posts(fetcher)).toHaveLength(0);
  fireEvent.change(await screen.findByLabelText("Сохранённая дата количества"), {
    target: { value: "2030-04-30" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" }),
  );
  await screen.findByRole("region", { name: "Фактические строки источника (actual)" });
  expect(posts(fetcher)).toHaveLength(1);
  expect(JSON.parse(String(posts(fetcher)[0][1]?.body))).toMatchObject({
    source_account: "SYNTH-01",
    isin: ISIN,
    as_of: "2030-04-30",
  });
});

test("selects a saved historical quantity without substituting the month's closing EOD or calling the provider", async () => {
  const { fetcher } = setup();
  const dates = await screen.findByRole("combobox", { name: "Сохранённая дата количества" });
  expect(screen.getByLabelText("Дата количества из выписки")).toHaveValue("2030-05-31");
  expect(screen.getByText(/На 2030-05-31 сохранённое количество не подтверждено/)).toBeVisible();
  fireEvent.change(dates, { target: { value: "2030-04-30" } });
  expect(screen.getByLabelText("Дата количества из выписки")).toHaveValue("2030-04-30");
  expect(screen.getByText(/Наблюдаемое количество: 2.5 на 2030-04-30/)).toBeVisible();
  expect(screen.getByText(/не заменяет закрывающий EOD 2030-05-31/)).toBeVisible();
  expect(posts(fetcher)).toHaveLength(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Запросить предварительные выплаты T-Invest" }),
  );
  await screen.findByRole("region", { name: "Фактические строки источника (actual)" });
  expect(JSON.parse(String(posts(fetcher)[0][1]?.body)).as_of).toBe("2030-04-30");
});

test.each([false, true])(
  "queued outgoing date cannot undo an ISIN switch (ABA=%s)",
  async (aba) => {
    const { fetcher } = setup(
      `/v2/close?month=1&panel=payouts&source_account=SYNTH-01&keep=yes#details`,
    );
    const outgoingDate = await screen.findByLabelText("Сохранённая дата количества");
    const first = screen.getByRole("button", { pressed: true });
    const stock = screen.getByRole("button", { name: "Синтетическая акция" });
    // Keep React's navigation commit pending while the outgoing native control fires.
    // This exercises the real click/change closures, not a mock URL setter.
    act(() => {
      stock.click();
      if (aba) first.click();
      fireEvent.change(outgoingDate, { target: { value: "2030-04-30" } });
    });
    const expectedIsin = aba ? ISIN : STOCK;
    await screen.findByRole("region", { name: `Инструмент ${expectedIsin}` });
    expect(screen.getByLabelText("URL")).toHaveTextContent(`instrument_isin=${expectedIsin}`);
    expect(screen.getByLabelText("URL")).not.toHaveTextContent("payout_as_of");
    expect(screen.getByLabelText("URL")).toHaveTextContent("keep=yes");
    expect(screen.getByLabelText("URL")).toHaveTextContent("#details");
    expect(posts(fetcher)).toHaveLength(0);
    fireEvent.change(await screen.findByLabelText("Сохранённая дата количества"), {
      target: { value: "2030-04-30" },
    });
    expect(
      screen.getByText(new RegExp(`Наблюдаемое количество: ${aba ? "2.5" : "7"} на 2030-04-30`)),
    ).toBeVisible();
    expect(screen.getByLabelText("URL")).toHaveTextContent(`instrument_isin=${expectedIsin}`);
    expect(screen.getByLabelText("URL")).toHaveTextContent("#details");
    fireEvent.click(screen.getByRole("button", { name: /Запросить предварительные/ }));
    await waitFor(() => expect(posts(fetcher)).toHaveLength(1));
    expect(JSON.parse(String(posts(fetcher)[0][1]?.body))).toEqual({
      source_account: "SYNTH-01",
      isin: expectedIsin,
      as_of: "2030-04-30",
    });
  },
);

test("Month reuses #949 detail, separates full/conditional/NULL and never starts the provider automatically", async () => {
  const { fetcher } = setup();
  await screen.findByText("Сделки, выплаты и расчёт инструмента");
  fireEvent.click(screen.getByText("Сделки, выплаты и расчёт инструмента"));
  await screen.findByRole("region", { name: `Инструмент ${ISIN}` });
  expect(
    within(
      screen.getByRole("heading", { name: "Полный P&L, ₽" }).parentElement as HTMLElement,
    ).getByText("Недоступен"),
  ).toBeVisible();
  expect(screen.getByRole("region", { name: "Условная оценка по выписке" })).toHaveTextContent(
    "0,617 %",
  );
  fireEvent.click(screen.getByRole("button", { name: "Синтетическая акция" }));
  expect(await screen.findByRole("region", { name: `Инструмент ${STOCK}` })).toHaveTextContent(
    "100,01 ₽",
  );
  expect(screen.getByRole("region", { name: `Инструмент ${STOCK}` })).toHaveTextContent("10,001 %");
  expect(
    screen.queryByRole("region", { name: "Условная оценка по выписке" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("99 %")).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(0);
});

test.each([
  "instrument_isin=MISSING",
  "instrument_isin=",
  `instrument_isin=${ISIN}&instrument_isin=${STOCK}`,
])("explicit unavailable ISIN has no fallback: %s", async (query) => {
  const { fetcher } = setup(`/v2/close?source_account=SYNTH-01&${query}`);
  await screen.findByRole("heading", { name: "Выбранный инструмент недоступен" });
  expect(
    screen.queryByRole("button", { name: /Запросить предварительные/ }),
  ).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(0);
});

test("explicit preview retains later actuals and separates possible_paid/future without money precision loss", async () => {
  const { fetcher } = setup();
  fireEvent.click(await screen.findByRole("button", { name: /Запросить предварительные/ }));
  const actual = await screen.findByRole("table", {
    name: "Actual для сверки · включая события после даты количества",
  });
  expect(actual).toHaveTextContent("2030-06-15");
  expect(actual).toHaveTextContent("12,34 ₽");
  expect(actual).toHaveTextContent("Неизвестно / Неизвестно");
  const future = screen.getByRole("table", { name: "Будущие кандидаты (future)" });
  expect(future).toHaveTextContent("90 071 992 547 409,93 ₽");
  expect(future).not.toHaveTextContent("possible_paid");
  expect(
    screen.getByRole("table", { name: "Возможно уже выплачено (possible_paid)" }),
  ).toHaveTextContent("actual-1");
  expect(posts(fetcher)).toHaveLength(1);
  expect(JSON.parse(String(posts(fetcher)[0][1]?.body))).toEqual({
    source_account: "SYNTH-01",
    isin: ISIN,
    as_of: "2030-05-31",
  });
});

test("account switch and date changes retire old results and late provider responses", async () => {
  const { state, fetcher } = setup();
  let finish: ((value: Response) => void) | undefined;
  state.reply = () =>
    new Promise<Response>((resolve) => {
      finish = resolve;
    });
  fireEvent.click(await screen.findByRole("button", { name: /Запросить предварительные/ }));
  fireEvent.change(screen.getByLabelText("Дата количества из выписки"), {
    target: { value: "2030-04-30" },
  });
  await act(async () => finish?.(json(preview())));
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("URL")).toHaveTextContent("payout_as_of=2030-04-30");
  fireEvent.click(screen.getByRole("button", { name: "Другой счёт" }));
  await waitFor(() => expect(screen.getByText(/Выбранный счёт: SYNTH-02/)).toBeVisible());
  expect(await screen.findByLabelText("Дата количества из выписки")).toHaveValue("2030-05-31");
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(1);
});

test("payout entry rejects a late A response after A→B→A even though the account name matches again", async () => {
  const { state, fetcher } = setup("/v2/close?panel=payouts&source_account=SYNTH-01", true);
  let finish: ((value: Response) => void) | undefined;
  state.reply = () =>
    new Promise<Response>((resolve) => {
      finish = resolve;
    });
  fireEvent.click(await screen.findByRole("button", { name: /Запросить предварительные/ }));
  fireEvent.click(screen.getByRole("button", { name: "Другой счёт" }));
  await screen.findByText(/Выбранный счёт: SYNTH-02/);
  fireEvent.click(screen.getByRole("button", { name: "Первый счёт" }));
  await screen.findByText(/Выбранный счёт: SYNTH-01/);
  await act(async () => finish?.(json(preview())));
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(1);
  expect(screen.getByLabelText("Дата количества из выписки")).toHaveValue("2030-05-31");
});

test("read refresh discards provider preview; 409 and wrong scope fail closed without automatic retry", async () => {
  const { state, fetcher } = setup();
  fireEvent.click(await screen.findByRole("button", { name: /Запросить предварительные/ }));
  await screen.findByRole("table", { name: /Actual для сверки/ });
  fireEvent.click(screen.getByRole("button", { name: "Обновить чтение инструментов" }));
  await screen.findByRole("button", { name: /Запросить предварительные/ });
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(1);
  state.reply = async () => json({}, 409);
  fireEvent.click(screen.getByRole("button", { name: /Запросить предварительные/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Источник или сопоставления изменились",
  );
  expect(posts(fetcher)).toHaveLength(2);
  state.reply = async () => json(preview("SYNTH-02"));
  fireEvent.click(screen.getByRole("button", { name: /Запросить предварительные/ }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не подтверждены"));
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
});

test("integer money and Decimal rate formatting preserve zero, large exact values and unavailable inputs", () => {
  expect(money("9007199254740993")).toBe("90 071 992 547 409,93 ₽");
  expect(money(0)).toBe("0,00 ₽");
  expect(money(null)).toBe("Неизвестно");
  expect(money(Number.MAX_SAFE_INTEGER + 1)).toBe("Недоступна точная сумма");
  expect(rate("6.17e-3")).toBe("0,617 %");
  expect(rate("0.00617")).toBe("0,617 %");
  expect(rate("-0.123456785")).toBe("−12,3457 %");
});

test("changed source provenance rejects a mixed result and forecast", async () => {
  const { state, fetcher } = setup();
  state.reply = async () => {
    const value = preview();
    value.source_references[0].journal_revision++;
    return json(value);
  };
  fireEvent.click(await screen.findByRole("button", { name: /Запросить предварительные/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Источники результата и preview изменились",
  );
  expect(screen.queryByRole("table", { name: /Actual для сверки/ })).not.toBeInTheDocument();
  expect(posts(fetcher)).toHaveLength(1);
});

test.each([
  "payout_as_of=2030-02-30",
  "payout_as_of=",
  "payout_as_of=2030-05-31&payout_as_of=2030-04-30",
])("invalid explicit quantity date never falls back: %s", async (query) => {
  const { fetcher } = setup(`/v2/close?source_account=SYNTH-01&${query}`);
  expect(await screen.findByRole("button", { name: /Запросить предварительные/ })).toBeDisabled();
  expect(posts(fetcher)).toHaveLength(0);
});

test.each(["account", "period"])(
  "wrong instrument API %s hides dependent metrics/actions",
  async (kind) => {
    const { state, fetcher } = setup();
    await screen.findByText("Сделки, выплаты и расчёт инструмента");
    fireEvent.click(screen.getByText("Сделки, выплаты и расчёт инструмента"));
    await screen.findByRole("region", { name: `Инструмент ${ISIN}` });
    state.readReply = () => {
      const value = instruments();
      if (kind === "account") value.source_account = "SYNTH-02";
      else value.instruments[0].analysis.closing_date = "2030-06-30";
      return json(value);
    };
    fireEvent.click(screen.getByRole("button", { name: "Обновить чтение инструментов" }));
    await screen.findByRole("heading", { name: "Инструменты месяца не подтверждены" });
    expect(screen.queryByRole("heading", { name: "Полный P&L, ₽" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Запросить предварительные/ }),
    ).not.toBeInTheDocument();
    expect(posts(fetcher)).toHaveLength(0);
  },
);
