import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { type AcceptedIncome, displayMetric, unavailable } from "./model";
import { ReturnsAcceptedIncome } from "./ReturnsAcceptedIncome";

const value: AcceptedIncome = {
  net_kopecks: "10440",
  gross_kopecks: "12000",
  tax_kopecks: "1560",
  fees_kopecks: null,
  coupons_kopecks: null,
  dividends_kopecks: "10440",
  partial: true,
  reason_codes: ["whole_interval_coverage_unknown"],
  instruments: [
    {
      id: "1:1",
      account: "Учебный счёт",
      name: "Учебная акция",
      isin: "RU000A000001",
      net_kopecks: "10440",
      gross_kopecks: "12000",
      tax_kopecks: "1560",
      fees_kopecks: null,
      coupons_kopecks: null,
      dividends_kopecks: "10440",
    },
  ],
};

// toHaveTextContent collapses received whitespace (incl. Intl \u00a0 / \u202f) to a plain space;
// normalize the expected formatted amount the same way so the comparison stays exact.
const money = (amount: string) =>
  displayMetric({ ...unavailable, value: amount }).replace(/\s+/g, " ");

test("accepted payments show exact net and tax with partial coverage independently of return", () => {
  render(<ReturnsAcceptedIncome value={value} />);
  const panel = screen.getByRole("region", { name: "Разложение выплат" });
  expect(
    within(panel).getByRole("heading", { name: "Выплаты (купоны + дивиденды)" }),
  ).toBeVisible();
  expect(within(panel).getByText(/покрытие периода частичное/)).toBeVisible();
  expect(within(panel).queryByText("Оценка")).toBeNull();
  const row = within(panel).getAllByRole("row")[1];
  const cells = within(row).getAllByRole("cell");
  expect(cells[0]).toHaveTextContent("—");
  for (const [index, amount] of ["10440", "12000", "1560"].entries()) {
    expect(cells[index + 1]).toHaveTextContent(money(amount));
  }
});

test("unknown tax remains a dash while a proven zero payment remains zero", () => {
  render(
    <ReturnsAcceptedIncome
      value={{
        ...value,
        net_kopecks: "0",
        gross_kopecks: null,
        tax_kopecks: null,
        instruments: [
          {
            ...value.instruments[0],
            dividends_kopecks: "0",
            gross_kopecks: null,
            tax_kopecks: null,
          },
        ],
      }}
    />,
  );
  const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
  expect(cells[1]).toHaveTextContent(money("0"));
  expect(cells[2]).toHaveTextContent("—");
  expect(cells[3]).toHaveTextContent("—");
});
