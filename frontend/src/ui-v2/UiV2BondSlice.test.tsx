import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type {
  InstrumentAnalysis,
  InstrumentEvent,
  SourceInstrumentReturns,
} from "../api/sourceReturns";
import { UiV2BondSlice } from "./UiV2BondSlice";

const ISIN = "RU000A000001";
const metric = <T,>(value: T | null, codes: string[] = []) => ({
  value,
  status: value === null ? ("unavailable" as const) : ("provisional" as const),
  reason_codes: codes,
  assumptions: [],
});
function analysis(): InstrumentAnalysis {
  const basis = ["bond_valuation_basis_unknown"];
  const endpoint = {
    quantity: "2",
    reported_value_kopecks: 200000,
    economic_value_kopecks: null,
    accrued_interest_kopecks: null,
    valuation_basis: "reported_unknown" as const,
    source_references: ["position:1:0"],
    reason_codes: basis,
  };
  return {
    contract_version: "instrument_return_v2",
    opening_date: "2030-04-30",
    closing_date: "2030-05-31",
    history_start: "2030-04-30",
    history_end: "2030-05-31",
    history_complete_since_acquisition: false,
    opening: { ...endpoint, date: "2030-04-30" },
    closing: { ...endpoint, date: "2030-05-31", reported_value_kopecks: 201234 },
    events: [],
    components: {
      buys: metric<number>(null),
      sells: metric<number>(null),
      coupons: metric(1234),
      dividends: metric<number>(null),
      redemption: metric<number>(null),
      fees: metric<number>(null),
      taxes: metric<number>(null),
      valuation_and_trades: metric<number>(null),
    },
    pnl: metric<number>(null, basis),
    known_subtotal: { ...metric(1234), status: "partial" },
    modified_dietz: {
      ...metric<string>(null, [...basis, "missing_endpoint"]),
      method: "modified_dietz",
      approximate: true,
      annualized: false,
      capital_days: null,
    },
    chained_monthly: metric<string>(null),
    coverage: {
      events: { complete: true, reason_codes: [] },
      quantity: { complete: true, reason_codes: [] },
      endpoints: { complete: true, reason_codes: [] },
      payouts: { complete: true, reason_codes: [] },
      costs: { complete: true, reason_codes: [] },
      valuation: { complete: false, reason_codes: basis },
    },
    source_references: [
      {
        intake_id: 1,
        original_digest: "a".repeat(64),
        parser_version: "synthetic-v1",
        journal_revision: 3,
        manifest_digest: "b".repeat(64),
        classification_dependencies: [],
        link_dependencies: "c".repeat(64),
      },
    ],
    reason_codes: basis,
    assumptions: [],
    statement_estimate: {
      pnl: metric(1234),
      modified_dietz: {
        ...metric("0.00617"),
        method: "modified_dietz",
        approximate: true,
        annualized: false,
        capital_days: 6200000,
      },
      assumptions: basis,
    },
  };
}
function event(patch: Partial<InstrumentEvent>): InstrumentEvent {
  return {
    event_key: "synthetic-event",
    provider: "synthetic",
    native_source_account: "SYNTH-01-000",
    isin: ISIN,
    kind: "COUPON",
    source_references: ["money:1:coupon:0"],
    event_date: "2030-05-15",
    native_identity: null,
    native_ids: [],
    trade_time: null,
    cash_settlement_date: null,
    depository_settlement_date: null,
    quantity_delta: null,
    unit_price: null,
    price_unit: "UNKNOWN",
    face_value: null,
    face_value_date: null,
    native_trade_amount_kopecks: null,
    native_total_basis: null,
    proof_dependency: null,
    accrued_interest_kopecks: null,
    commission_kopecks: null,
    gross_payout_kopecks: null,
    withheld_tax_kopecks: null,
    net_payout_kopecks: 1234,
    classification: "coupon",
    classification_origin: "default_rule",
    classification_status: "assumed",
    persisted_link_status: "linked",
    attribution_basis: "persisted_link",
    effective_isin: ISIN,
    current: true,
    counted: true,
    cash_legs: [],
    reason_codes: [],
    assumptions: ["income_assumed"],
    ...patch,
  };
}
function source(account = "SYNTH-01"): SourceInstrumentReturns {
  const a = analysis();
  const totals = {
    buys_cost_kopecks: null,
    sells_proceeds_kopecks: null,
    price_effect_kopecks: null,
    coupons_kopecks: 1234,
    dividends_kopecks: null,
    assumed_income_kopecks: 1234,
    confirmed_income_kopecks: null,
    income_kopecks: 1234,
    total_kopecks: 99999999,
    capital_base_kopecks: null,
    return_percent: "99",
    income_assumptions_used: true,
    income_complete: true,
    flags: [],
    approximate: true,
  };
  return {
    source_account: account,
    native_source_account: `${account}-000`,
    financial_authority: "none",
    authority: "provisional",
    currency: "RUB",
    gaps: [],
    unresolved_events: [],
    account_reconciliation_events: [],
    reconciliation: null,
    income: [],
    instruments: [
      {
        isin: ISIN,
        source_name: `Синтетическая облигация ${account}`,
        instrument_type: "bond",
        analysis: a,
        months: [
          {
            ...totals,
            month: "2030-05-01",
            opening_quantity: "2",
            closing_quantity: "2",
            opening_value_kopecks: 200000,
            closing_value_kopecks: 201234,
            intake_ids: [1],
            analysis: a,
          },
        ],
        all_time: {
          ...totals,
          available_months: [],
          missing_months: [],
          partial_months: [],
          partial: true,
        },
      },
    ],
  };
}
function LocationReadback() {
  return <output aria-label="Текущий URL">{useLocation().search}</output>;
}
function setup(data = source(), url = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (next: SourceInstrumentReturns) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <UiV2BondSlice key={next.source_account} account={next.source_account} sources={next} />
        <LocationReadback />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { ...render(tree(data)), tree };
}
afterEach(() => vi.unstubAllGlobals());
const card = (name: string) =>
  within(screen.getByRole("heading", { name }).parentElement as HTMLElement);
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

function twoBonds() {
  const data = source();
  data.instruments.push({
    ...source().instruments[0],
    isin: "RU000A000002",
    source_name: "Вторая синтетическая облигация",
    analysis: analysis(),
  });
  return data;
}

test.each(["RU000STALE01", ""])(
  "explicit absent ISIN %j never substitutes another bond, including after reload",
  async (isin) => {
    const data = twoBonds();
    const url = `/?source_account=SYNTH-01&bond_isin=${isin}`;
    const first = setup(data, url);
    expect(screen.getByText("Выбранная облигация недоступна")).toBeVisible();
    expect(screen.queryByRole("region", { name: /Детали облигации/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Полный P&L, ₽" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Условная оценка по выписке" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { pressed: true })).not.toBeInTheDocument();
    const savedUrl = screen.getByLabelText("Текущий URL").textContent;
    expect(new URLSearchParams(savedUrl ?? "").get("bond_isin")).toBe(isin);
    first.unmount();
    setup(data, `/${savedUrl}`);
    expect(screen.getByText("Выбранная облигация недоступна")).toBeVisible();
    expect(screen.queryByRole("region", { name: /Детали облигации/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Вторая синтетическая облигация" }));
    expect(screen.getByRole("region", { name: "Детали облигации RU000A000002" })).toBeVisible();
    expect(screen.queryByText("Выбранная облигация недоступна")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Текущий URL")).toHaveTextContent("bond_isin=RU000A000002");
  },
);

test("without explicit ISIN the first bond is selected by default", () => {
  setup(twoBonds(), "/?source_account=SYNTH-01");
  expect(screen.getByRole("region", { name: `Детали облигации ${ISIN}` })).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Синтетическая облигация SYNTH-01", pressed: true }),
  ).toBeVisible();
  expect(
    screen.queryByRole("region", { name: "Детали облигации RU000A000002" }),
  ).not.toBeInTheDocument();
  expect(
    new URLSearchParams(screen.getByLabelText("Текущий URL").textContent ?? "").has("bond_isin"),
  ).toBe(false);
});

test("explicit ISIN removed from the selected period stays unavailable and preserves URL scope", async () => {
  const data = twoBonds();
  const month = twoBonds();
  month.instruments.shift();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(month)),
  );
  setup(data, `/?source_account=SYNTH-01&bond_isin=${ISIN}`);
  expect(screen.getByRole("region", { name: `Детали облигации ${ISIN}` })).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText("Период облигаций"), "2030-05-01");
  await screen.findByText("Выбранная облигация недоступна");
  expect(screen.queryByRole("region", { name: /Детали облигации/ })).not.toBeInTheDocument();
  const params = new URLSearchParams(screen.getByLabelText("Текущий URL").textContent ?? "");
  expect(Object.fromEntries(params)).toEqual({
    source_account: "SYNTH-01",
    bond_isin: ISIN,
    bond_period: "2030-05-01",
  });
});

test("no-trade bond shows reported operands and server-only conditional fraction, with full result NULL", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  setup();
  expect(screen.getByText("SYNTH-01-000")).toBeVisible();
  const row = within(screen.getByRole("table", { name: "Облигации выбранного счёта и периода" }));
  expect(row.getByText("2")).toBeVisible();
  expect(row.getByText(/2.012,34/)).toBeVisible();
  expect(row.getByText("2030-05-31")).toBeVisible();
  expect(card("Полный P&L, ₽").getByText("Недоступен")).toBeVisible();
  expect(card("Modified Dietz · приблизительно, за период").getByText("Недоступен")).toBeVisible();
  const estimate = within(screen.getByRole("region", { name: "Условная оценка по выписке" }));
  expect(estimate.getByText("0,617 %")).toBeVisible();
  expect(estimate.getByText(/12,34 ₽/)).toBeVisible();
  expect(screen.queryByText("99 %")).not.toBeInTheDocument();
  expect(screen.queryByText(/999.999,99/)).not.toBeInTheDocument();
  expect(screen.getByText(/Сделок в выбранном интервале нет/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

test("unknown NKD/gross/tax stays unknown and source units, unsettled trade and coupon assumptions stay visible", async () => {
  const data = source();
  data.instruments[0].analysis.events = [
    event({}),
    event({
      event_key: "trade",
      kind: "BUY",
      net_payout_kopecks: null,
      trade_time: "2030-05-10T12:00:00",
      quantity_delta: "1",
      unit_price: "98.5",
      price_unit: "PERCENT_OF_FACE",
      native_trade_amount_kopecks: 100000,
      counted: false,
      reason_codes: ["trade_nkd_basis_unknown"],
      persisted_link_status: null,
    }),
  ];
  setup(data);
  const trades = within(screen.getByRole("table", { name: "Сделки по строкам источников" }));
  expect(trades.getByText(/% от номинала/)).toBeVisible();
  expect(trades.getByText("Не учтено в расчёте")).toBeVisible();
  expect(trades.getByText("Неизвестно / Неизвестно")).toBeVisible();
  const coupons = within(screen.getByRole("table", { name: "Купоны по строкам источников" }));
  expect(coupons.getByText("Неизвестно / Неизвестно")).toBeVisible();
  expect(coupons.getByText(/Классификация: правило по умолчанию/)).toBeVisible();
  expect(screen.getAllByText(/Нужна dirty-оценка/).length).toBeGreaterThan(0);
  await userEvent.click(screen.getByText("Полнота и происхождение"));
  expect(screen.getByText("a".repeat(64))).toBeVisible();
});

test("zero is a known conditional result; each nullable estimate metric is gated independently", () => {
  const data = source();
  const estimate = data.instruments[0].analysis.statement_estimate;
  estimate.pnl.value = 0;
  estimate.modified_dietz.value = null;
  estimate.modified_dietz.reason_codes = ["non_positive_dietz_denominator"];
  setup(data);
  expect(card("Условный результат, ₽").getByText("0,00 ₽")).toBeVisible();
  expect(
    card("Условный Modified Dietz · приблизительно, за период").getByText("Недоступен"),
  ).toBeVisible();
  expect(screen.getByText(/Нет положительной базы/)).toBeVisible();
});

test("blocked flows hide both conditional figures while keeping known coupon and exact reasons", async () => {
  const data = source();
  const a = data.instruments[0].analysis;
  a.statement_estimate.pnl = metric<number>(null, ["trade_nkd_basis_unknown"]);
  a.statement_estimate.modified_dietz.value = null;
  a.statement_estimate.modified_dietz.reason_codes = ["trade_nkd_basis_unknown"];
  a.components.coupons.status = "partial";
  a.closing.quantity = null;
  a.closing.reported_value_kopecks = null;
  setup(data);
  expect(
    screen.queryByRole("region", { name: "Условная оценка по выписке" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Условная оценка недоступна"));
  expect(screen.getByText(/Не подтверждено, входит ли НКД/)).toBeVisible();
  expect(screen.getByText("Нет оценки на 2030-05-31")).toBeVisible();
  expect(screen.getByText(/Известный компонент купонов/).parentElement).toHaveTextContent(
    "12,34 ₽ · неполный компонент",
  );
});

test("month selection requests exact EOD interval and never writes", async () => {
  const data = source();
  const fetcher = vi.fn<typeof fetch>(async () => json(data));
  vi.stubGlobal("fetch", fetcher);
  setup(data);
  await userEvent.selectOptions(screen.getByLabelText("Период облигаций"), "2030-05-01");
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const url = new URL(String(fetcher.mock.calls[0][0]), "http://localhost");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    source_account: "SYNTH-01",
    opening_date: "2030-04-30",
    closing_date: "2030-05-31",
  });
  expect(fetcher.mock.calls[0][1]?.method ?? "GET").toBe("GET");
});

test("same ISIN across accounts and late old response never combine positions", async () => {
  let resolveOld: (value: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveOld = resolve;
        }),
    ),
  );
  const first = source();
  const { rerender, tree } = setup(first);
  await userEvent.selectOptions(screen.getByLabelText("Период облигаций"), "2030-05-01");
  const second = source("SYNTH-02");
  second.instruments[0].analysis.closing.quantity = "700";
  rerender(tree(second));
  expect(screen.getByText("SYNTH-02-000")).toBeVisible();
  expect(
    screen.getByRole("table", { name: "Облигации выбранного счёта и периода" }),
  ).toHaveTextContent("700");
  await act(async () => resolveOld(json(first)));
  expect(
    screen.getByRole("table", { name: "Облигации выбранного счёта и периода" }),
  ).toHaveTextContent("700");
  expect(screen.queryByText("SYNTH-01-000")).not.toBeInTheDocument();
});

test("mismatched native response is withheld; read errors offer GET retry", async () => {
  const first = source();
  const wrong = source("SYNTH-02");
  let count = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => (++count === 1 ? json({ message: "synthetic failure" }, 500) : json(wrong))),
  );
  setup(first);
  await userEvent.selectOptions(screen.getByLabelText("Период облигаций"), "2030-05-01");
  await screen.findByText("Не удалось прочитать облигации");
  await userEvent.click(screen.getByRole("button", { name: "Повторить чтение облигаций" }));
  await screen.findByText("Счёт ответа не совпадает с выбранным");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

test("unknown instrument type is not inferred to be a bond", () => {
  const data = source();
  data.instruments[0].instrument_type = null;
  setup(data);
  expect(screen.getByText(/нет облигаций с подтверждённым типом/)).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
