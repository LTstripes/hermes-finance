import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { analysis, event } from "../test/sourceInstrumentFixtures";
import { detailFixture } from "./returns/fixtures";
import { SourceInstrumentDetail } from "./SourceInstrumentDetail";

const card = (name: string) =>
  within(screen.getByRole("heading", { name }).parentElement as HTMLElement);

test("original-bound identity is visible without pretending to have a legacy link", () => {
  const a = analysis();
  a.events = [
    event({
      kind: "BUY",
      event_key: "source-buy",
      persisted_link_status: null,
      attribution_basis: "native_money_group_bridge",
      classification_status: "confirmed",
      trade_time: null,
      event_date: "2030-05-15",
      net_payout_kopecks: null,
    }),
    event({
      event_key: "source-coupon",
      persisted_link_status: null,
      attribution_basis: "xml_pdf_original_bound",
      classification_status: "confirmed",
    }),
  ];
  render(
    <MemoryRouter>
      <SourceInstrumentDetail analysis={a} personalResult />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByText("Сделки и выплаты (2)"));
  const payouts = within(
    screen.getByRole("table", { name: "Фактические выплаты по строкам источников" }),
  );
  expect(payouts.getByText("12,34 ₽")).toBeVisible();
  expect(payouts.getByText(/Связь подтверждена исходными документами/)).toBeVisible();
  expect(payouts.getByText(/Классификация: подтверждена/)).toBeVisible();
  expect(payouts.queryByText("Сохранённая связь с инструментом")).not.toBeInTheDocument();
  expect(screen.queryByText(/Несвязанные события/)).not.toBeInTheDocument();
});

test("personal summary keeps exact money, dated zero closing position and secondary period MD", () => {
  const a = detailFixture().analysis;
  a.pnl.value = "900719925474099301";
  render(
    <MemoryRouter>
      <SourceInstrumentDetail analysis={a} instrumentType="stock" personalResult />
    </MemoryRouter>,
  );
  expect(card("Мой результат за период, ₽").getByText("9 007 199 254 740 993,01 ₽")).toBeVisible();
  expect(card("Позиция на 31.05.2030").getByText("0,00 ₽")).toBeVisible();
  expect(screen.getByText("Позиция закрыта на эту дату")).toBeVisible();
  expect(screen.getByText("10 %")).not.toBeVisible();
  fireEvent.click(screen.getByText("Доходность в процентах · Modified Dietz за период"));
  expect(screen.getByText("10 %")).toBeVisible();
  expect(screen.getByText(/30.04.2030 — 31.05.2030.*не годовая/)).toBeVisible();
});

test("history reveals separate buy prices, partial sale, actual coupon, NKD, costs and provenance", () => {
  const a = analysis();
  a.closing.quantity = "4";
  a.events = [
    event({
      event_key: "buy-early",
      kind: "BUY",
      quantity_delta: "2",
      trade_time: "2030-05-05 10:00:00",
      unit_price: "100.25",
      price_unit: "PERCENT_OF_FACE",
      native_trade_amount_kopecks: 200500,
      accrued_interest_kopecks: 123,
      commission_kopecks: 45,
      net_payout_kopecks: null,
    }),
    event({
      event_key: "buy-late",
      kind: "BUY",
      quantity_delta: "3",
      trade_time: "2030-05-20 11:00:00",
      unit_price: "101.50",
      price_unit: "PERCENT_OF_FACE",
      native_trade_amount_kopecks: 304500,
      net_payout_kopecks: null,
    }),
    event({
      event_key: "partial-sale",
      kind: "SELL",
      quantity_delta: "-1",
      trade_time: "2030-05-25 12:00:00",
      native_trade_amount_kopecks: 110000,
      net_payout_kopecks: null,
    }),
    event({ event_key: "actual-coupon", gross_payout_kopecks: null, withheld_tax_kopecks: null }),
  ];
  render(
    <MemoryRouter>
      <SourceInstrumentDetail analysis={a} personalResult />
    </MemoryRouter>,
  );
  expect(card("Мой результат за период, ₽").getByText("Недоступен")).toBeVisible();
  expect(
    screen.getByRole("region", { name: "Условная оценка по выписке", hidden: true }),
  ).not.toBeVisible();
  fireEvent.click(screen.getByText("Сделки и выплаты (4)"));
  const trades = within(screen.getByRole("table", { name: "Сделки по строкам источников" }));
  expect(trades.getAllByText("Покупка")).toHaveLength(2);
  expect(trades.getByText("Продажа")).toBeVisible();
  expect(trades.getByText("100.25")).toBeVisible();
  expect(trades.getByText("101.50")).toBeVisible();
  expect(trades.getByText("1,23 ₽ / 0,45 ₽")).toBeVisible();
  const payouts = within(
    screen.getByRole("table", { name: "Фактические выплаты по строкам источников" }),
  );
  expect(payouts.getByText("12,34 ₽")).toBeVisible();
  expect(payouts.getByText("Неизвестно / Неизвестно")).toBeVisible();
  fireEvent.click(payouts.getByText("Строки источников (1)"));
  expect(payouts.getByText("money:1:coupon:0")).toBeVisible();
});

test("source zero-origin flag never asserts lifetime ownership or trims a late first purchase", () => {
  const a = detailFixture().analysis;
  a.history_start = a.opening_date = a.opening.date = "2020-01-01";
  a.history_complete_since_acquisition = true;
  a.events[0].kind = "BUY";
  render(
    <MemoryRouter>
      <SourceInstrumentDetail analysis={a} instrumentType="stock" personalResult />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByText("Полнота и происхождение"));
  expect(screen.getByText(/Этот признак не проверяет владение до начала источников/)).toBeVisible();
  fireEvent.click(screen.getByText("Доходность в процентах · Modified Dietz за период"));
  expect(screen.getByText(/01.01.2020 — 31.05.2030/)).toBeVisible();
  expect(screen.queryByText("История с приобретения: подтверждена.")).not.toBeInTheDocument();
});

test("absent holding and unknown value never look like a closed zero position", () => {
  const a = analysis();
  a.closing.quantity = a.closing.reported_value_kopecks = null;
  render(
    <MemoryRouter>
      <SourceInstrumentDetail analysis={a} personalResult />
    </MemoryRouter>,
  );
  expect(card("Позиция на 31.05.2030").getByText("Неизвестно", { exact: true })).toBeVisible();
  expect(screen.getByText("Количество: 2 → Неизвестно")).toBeVisible();
  expect(screen.queryByText("Позиция закрыта на эту дату")).not.toBeInTheDocument();
});

test.each([false, true])(
  "unbound same-issuer cash rows stay separate from instrument history (personal=%s)",
  (personalResult) => {
    const a = analysis();
    // A linked stock dividend adds catalogue name «Пример». The bond exists only
    // in trades. Money «НКД по сделке» / «Пример 001Р-01» has no ISIN/execution ID:
    // legacy name matching sets isin to the stock, but effective_isin stays null.
    a.events = [
      event({ event_key: "stock-dividend", kind: "DIVIDEND" }),
      event({
        event_key: "pending-stock-buy",
        kind: "BUY",
        native_trade_amount_kopecks: 50000,
        net_payout_kopecks: null,
        current: false,
        counted: false,
        reason_codes: ["trade_missing_settlement"],
      }),
      ...[123, 234].map((amount, index) =>
        event({
          event_key: `unbound-nkd-${index}`,
          kind: "UNRESOLVED",
          effective_isin: null,
          attribution_basis: "legacy_text",
          persisted_link_status: null,
          classification: "trade_settlement",
          net_payout_kopecks: null,
          current: false,
          counted: false,
          assumptions: [],
          reason_codes: ["unmatched_trade_money"],
          source_references: [`money:1:unbound-nkd:${index}`],
          cash_legs: [
            {
              ownership: `unbound-nkd-${index}`,
              date: "2030-05-15",
              role: "trade_settlement",
              account_cash_kopecks: -amount,
              instrument_flow_kopecks: amount,
              source_references: [`money:1:unbound-nkd:${index}`],
            },
          ],
        }),
      ),
    ];
    a.pnl.reason_codes = ["unmatched_trade_money"];
    const before = structuredClone(a);
    render(
      <MemoryRouter>
        <SourceInstrumentDetail
          analysis={a}
          instrumentType="stock"
          personalResult={personalResult}
        />
      </MemoryRouter>,
    );
    const summary = screen.getByText("Сделки и выплаты (2)");
    if (personalResult) fireEvent.click(summary);
    const history = within(summary.parentElement as HTMLElement);
    expect(history.getByText("Покупка")).toBeVisible();
    expect(history.getByText("Не учтено в расчёте")).toBeVisible();
    expect(history.getByText("Дивиденд")).toBeVisible();
    expect(history.queryByText(/−1,23 ₽|−2,34 ₽/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Строки без подтверждённого инструмента (2)"));
    const unbound = within(
      screen.getByRole("region", { name: "Строки без подтверждённого инструмента" }),
    );
    expect(unbound.getByText(/Совпадение названия не подтверждает связь/)).toBeVisible();
    expect(unbound.getByText(/−1,23 ₽/)).toBeVisible();
    expect(unbound.getByText(/−2,34 ₽/)).toBeVisible();
    expect(
      unbound.getAllByText("Не установлена принадлежность денежной строки сделке."),
    ).toHaveLength(2);
    fireEvent.click(unbound.getAllByText("Строки источников (1)")[0]);
    expect(unbound.getByText("money:1:unbound-nkd:0")).toBeVisible();
    expect(
      card(personalResult ? "Мой результат за период, ₽" : "Полный P&L, ₽").getByText("Недоступен"),
    ).toBeVisible();
    expect(a).toEqual(before);
  },
);
