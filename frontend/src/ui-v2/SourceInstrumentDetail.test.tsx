import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { analysis, event } from "../test/sourceInstrumentFixtures";
import { detailFixture } from "./returns/fixtures";
import { SourceInstrumentDetail } from "./SourceInstrumentDetail";

const card = (name: string) =>
  within(screen.getByRole("heading", { name }).parentElement as HTMLElement);

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
