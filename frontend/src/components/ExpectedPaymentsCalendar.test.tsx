import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ExpectedCalendarMonth } from "../api/types";
import { formatMoney, formatMonth } from "../lib/format";
import { rub } from "../lib/money";
import { ExpectedPaymentsCalendar } from "./ExpectedPaymentsCalendar";

function month(
  year: number,
  monthNumber: number,
  amounts: Partial<Record<"coupon" | "dividend" | "interest" | "redemption" | "other", string>>,
): ExpectedCalendarMonth {
  const money = (key: string) => rub(amounts[key as keyof typeof amounts] ?? "0.00");
  const coupon = money("coupon");
  const dividend = money("dividend");
  const interest = money("interest");
  const redemption = money("redemption");
  const other = money("other");
  const kop = (mv: { amount: string }) => Number(mv.amount.replace(".", ""));
  const passive = String((kop(coupon) + kop(dividend) + kop(interest) + kop(other)) / 100);
  const total = String(
    (kop(coupon) + kop(dividend) + kop(interest) + kop(other) + kop(redemption)) / 100,
  );
  return {
    year,
    month: monthNumber,
    coupon,
    dividend,
    interest,
    redemption,
    other,
    passive_net: rub(passive),
    total_net: rub(total),
    items: [],
  };
}

const june = month(2031, 6, { coupon: "870.00", dividend: "500.00" });
const july = month(2031, 7, { redemption: "10000.00" });

describe("ExpectedPaymentsCalendar", () => {
  const chip = (text: string) =>
    screen.getByText(
      (_, el) => el?.classList.contains("flow-chip") === true && el?.textContent === text,
    );
  const monthName = (text: string) =>
    screen.getByText(
      (_, el) =>
        el?.classList.contains("payments-calendar__month-name") === true &&
        el?.textContent === text,
    );
  const cell = (text: string) =>
    screen.getByText((_, el) => el?.tagName === "TD" && el?.textContent === text);

  it("shows month names, per-type chips and passive net", () => {
    render(<ExpectedPaymentsCalendar months={[june, july]} />);
    expect(monthName(formatMonth(2031, 6))).toBeInTheDocument();
    expect(monthName(formatMonth(2031, 7))).toBeInTheDocument();
    expect(chip(`Купон ${formatMoney("870.00")}`)).toBeInTheDocument();
    expect(chip(`Дивиденды ${formatMoney("500.00")}`)).toBeInTheDocument();
    expect(chip(`Погашение ${formatMoney("10000.00")}`)).toBeInTheDocument();
    expect(screen.getAllByText(/Пассивный доход, нетто:/)).toHaveLength(2);
  });

  it("renders an empty state without calendar months", () => {
    render(<ExpectedPaymentsCalendar months={[]} />);
    expect(screen.getByText("Нет ожидаемых выплат")).toBeInTheDocument();
  });

  it("lists payout details with dates, accounts and net amounts", () => {
    const withItems = month(2031, 6, { coupon: "870.00" });
    withItems.items = [
      {
        id: 1,
        expected_date: "2031-06-15",
        flow_type: "coupon",
        account_name: "Брокер",
        instrument_name: "ОФЗ",
        expected_net_amount: rub("870.00"),
        is_confirmed: true,
        is_approximate: false,
        source: "manual",
      },
    ];
    render(<ExpectedPaymentsCalendar months={[withItems]} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("Брокер")).toBeInTheDocument();
    expect(within(table).getByText("ОФЗ")).toBeInTheDocument();
    expect(cell(formatMoney("870.00"))).toBeInTheDocument();
  });

  it("marks approximate and unconfirmed items in the details", () => {
    const withItems = month(2031, 6, { interest: "100.00" });
    withItems.items = [
      {
        id: 2,
        expected_date: "2031-06-20",
        flow_type: "interest",
        account_name: "Вклад",
        instrument_name: null,
        expected_net_amount: rub("100.00"),
        is_confirmed: false,
        is_approximate: true,
        source: "manual",
      },
    ];
    render(<ExpectedPaymentsCalendar months={[withItems]} />);
    expect(screen.getByText(/приблизительно/)).toBeInTheDocument();
    expect(screen.getByText(/не подтверждено/)).toBeInTheDocument();
  });
});
