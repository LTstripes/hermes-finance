import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import type { Metric } from "./model";
import { Explanation, Value } from "./ReturnsInfo";

test("known reason renders a phrase, with its raw code only in closed details", () => {
  render(<Explanation codes={["missing_endpoint"]} />);
  expect(screen.getByText("Не хватает стоимости на границе периода.")).toBeVisible();
  expect(screen.getByText("missing_endpoint")).not.toBeVisible();
  fireEvent.click(screen.getByText("Подробности"));
  expect(screen.getByText("missing_endpoint")).toBeVisible();
});
test("account gift disclosure is quiet while a real missing endpoint remains explained", () => {
  const view = render(<Explanation codes={["broker_gift_external_flow", "missing_endpoint"]} />);
  expect(screen.getByText("Не хватает стоимости на границе периода.")).toBeVisible();
  expect(screen.queryByText(/Подарок был учтён/)).toBeNull();
  fireEvent.click(screen.getByText("Подробности"));
  expect(screen.getByText("missing_endpoint")).toBeVisible();
  expect(screen.queryByText("broker_gift_external_flow")).toBeNull();
  view.rerender(<Explanation codes={["broker_gift_external_flow"]} />);
  expect(view.container).toBeEmptyDOMElement();
});
test("unknown reason never diagnoses missing data or renders a guessed action", () => {
  render(
    <Explanation
      codes={["future_valuation_flow_error"]}
      context={{ actions: { month: { available: true, href: "/v2/close?month=1" } } }}
    />,
  );
  expect(screen.getByText("Значение сейчас недоступно")).toBeVisible();
  expect(screen.getByText("future_valuation_flow_error")).not.toBeVisible();
  expect(screen.queryByText(/не хватает проверенных данных/)).toBeNull();
  expect(screen.queryByRole("link", { name: "Исправить" })).toBeNull();
});
test.each([true, false])(
  "renders Исправить only when the supplied action is available: %s",
  (available) => {
    render(
      <MemoryRouter>
        <Explanation
          codes={["mapping_ambiguous"]}
          context={{
            month: "январь 2030",
            account: "Учебный счёт",
            instrument: "Учебная бумага",
            actions: { instrumentMapping: { available, href: "/v2/data/catalogs" } },
          }}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByText(/Месяц: январь 2030 · Счёт: Учебный счёт · Инструмент: Учебная бумага/),
    ).toBeVisible();
    if (available)
      expect(screen.getByRole("link", { name: "Исправить" })).toHaveAttribute(
        "href",
        "/v2/data/catalogs",
      );
    else expect(screen.queryByRole("link", { name: "Исправить" })).toBeNull();
  },
);
test("copy never hides a zero value or promotes unavailable data", () => {
  const metric: Metric = {
    value: "0",
    unit: "kopecks",
    method: "source_monthly",
    estimate: true,
    reason_codes: ["future_valuation_flow_error"],
  };
  const view = render(<Value metric={metric} label="Учебный результат" />);
  expect(screen.getByText(/0.*₽/)).toBeVisible();
  view.rerender(<Value metric={{ ...metric, value: null }} label="Учебный результат" />);
  expect(screen.getByText("—")).toBeVisible();
  expect(metric.value).toBe("0");
});
