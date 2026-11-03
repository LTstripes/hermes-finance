import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { detailFixture, m } from "./fixtures";
import { ReturnsInstrumentResult } from "./ReturnsInstrumentResult";

const setup = (props: Parameters<typeof ReturnsInstrumentResult>[0]) =>
  render(
    <MemoryRouter>
      <ReturnsInstrumentResult {...props} />
    </MemoryRouter>,
  );

test("preserves exact large money and negative period rate from the server", () => {
  setup({
    result: { pnl: m("900719925474099312"), rate: m("-0.03125", "fraction", "modified_dietz") },
  });
  expect(screen.getByText("+9 007 199 254 740 993,12 ₽")).toBeVisible();
  expect(screen.getByText("−3,13%")).toBeVisible();
  expect(screen.getByText("Modified Dietz · за период, не годовая")).toBeVisible();
  expect(screen.queryByText("Нужна проверка данных")).toBeNull();
});
test("known zero remains numeric while a missing percentage has a visible explanation", () => {
  setup({ result: { pnl: m("0"), rate: m(null, "fraction", "modified_dietz") } });
  expect(screen.getByText("0 ₽")).toBeVisible();
  expect(screen.getByText("—")).toBeVisible();
  expect(screen.getByText("Нужна проверка данных")).toBeVisible();
  expect(screen.getByText(/^Причины:/)).toHaveTextContent(
    "Не хватает стоимости на границе периода",
  );
});
test("missing detail never becomes zero or a conditional or partial result", () => {
  const detail = detailFixture();
  detail.pnl = m(null);
  detail.rate = m(null, "fraction", "modified_dietz");
  detail.analysis.statement_estimate.pnl.value = "7654321";
  detail.analysis.known_subtotal.value = "1234567";
  setup({ result: detail, analysis: detail.analysis });
  expect(screen.getAllByText("—")).toHaveLength(2);
  expect(screen.queryByText(/76 543|12 345|0 ₽/)).toBeNull();
});
test("assumptions on analysis, metrics and events remain visible and deduplicated", () => {
  const detail = detailFixture();
  detail.analysis.assumptions = ["face_value_assumed"];
  detail.analysis.pnl.assumptions = ["face_value_assumed"];
  detail.analysis.events[0].assumptions = ["income_assumed"];
  setup({ result: detail, analysis: detail.analysis });
  const notes = screen.getByText(/^Допущения:/);
  expect(notes).toBeVisible();
  expect(notes).toHaveTextContent("Номинал сделки принят с допущением");
  expect(notes).toHaveTextContent("Классификация выплаты основана на правиле по умолчанию");
  expect(notes.textContent?.match(/Номинал сделки/g)).toHaveLength(1);
});
test("absent result shows two unavailable values and a review status", () => {
  const { container } = setup({ result: null });
  expect(within(container).getAllByText("—")).toHaveLength(2);
  expect(screen.getByText("Нужна проверка данных")).toBeVisible();
  expect(screen.queryByText("0 ₽")).toBeNull();
});

test("excluded or stale events do not label the result with unused assumptions", () => {
  const detail = detailFixture();
  detail.analysis.events[0].assumptions = ["income_assumed"];
  detail.analysis.events[0].current = false;
  setup({ result: detail, analysis: detail.analysis });
  expect(screen.queryByText(/^Допущения:/)).toBeNull();
});
