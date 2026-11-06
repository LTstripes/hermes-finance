import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { reasonCopy } from "../../lib/reasonCopy";
import { detailFixture, m } from "./fixtures";
import { ReturnsInstrumentResult } from "./ReturnsInstrumentResult";

const setup = (props: Parameters<typeof ReturnsInstrumentResult>[0]) =>
  render(
    <MemoryRouter>
      <ReturnsInstrumentResult {...props} />
    </MemoryRouter>,
  );

test("does not substitute legacy conditional cost estimates for an unknown clean result", () => {
  setup({
    result: {
      pnl: m(null),
      rate: m(null, "fraction"),
      conditional_pnl: { ...m("10000"), reason_codes: ["unallocated_costs_excluded"] },
      conditional_rate: m("0.1", "fraction", "modified_dietz"),
    },
  });
  expect(screen.queryByText("+100 ₽")).toBeNull();
  expect(screen.queryByText(/распределения расходов/)).toBeNull();
  expect(screen.getAllByText("—")).toHaveLength(2);
});

test("instrument card hides the account gift disclosure but keeps real missing-data reasons", () => {
  const detail = detailFixture();
  detail.pnl = { ...m(null), reason_codes: ["broker_gift_external_flow", "source_proof_stale"] };
  detail.rate = { ...m(null, "fraction"), reason_codes: ["broker_gift_external_flow"] };
  setup({
    result: detail,
    reasonCodes: ["broker_gift_external_flow", "source_proof_stale"],
  });
  expect(screen.queryByText(reasonCopy("broker_gift_external_flow").message)).toBeNull();
  expect(
    screen.getAllByText(
      (_, node) => node?.textContent?.includes(reasonCopy("source_proof_stale").message) ?? false,
    ).length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("—")).toHaveLength(2);
});

test("preserves exact large money and negative period rate from the server", () => {
  setup({
    result: { pnl: m("900719925474099312"), rate: m("-0.03125", "fraction", "modified_dietz") },
  });
  expect(screen.getByText("+9 007 199 254 740 993,12 ₽")).toBeVisible();
  expect(screen.getByText("−3,13%")).toBeVisible();
  expect(screen.getByText("Modified Dietz · за период, не годовая")).toBeVisible();
  expect(screen.queryByText("Не все показатели доступны")).toBeNull();
});
test("known zero remains numeric while a missing percentage has a visible explanation", () => {
  setup({ result: { pnl: m("0"), rate: m(null, "fraction", "modified_dietz") } });
  expect(screen.getByText("0 ₽")).toBeVisible();
  expect(screen.getByText("—")).toBeVisible();
  expect(screen.getByRole("note")).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent("Не хватает стоимости на границе периода.");
  const info = screen.getByLabelText("Подробнее: Доходность инструмента");
  expect(info.closest("details")).not.toHaveAttribute("open");
  info.click();
  const details = info.closest("details");
  if (!details) throw new Error("missing details");
  expect(within(details).getByText("Не хватает стоимости на границе периода.")).toBeVisible();
  expect(within(details).getByText("Подробности")).toBeVisible();
});
test("clean partial and a true clean zero remain distinct and visible", () => {
  const partial = {
    ...m("1200"),
    method: "clean_instrument_return_v1",
    reason_codes: ["clean_partial_result"],
  };
  const view = setup({ result: { pnl: partial, rate: m(null, "fraction") } });
  expect(screen.getByText("Сумма по доступным данным ₽")).toBeVisible();
  expect(screen.getByText("+12 ₽")).toBeVisible();
  view.rerender(
    <MemoryRouter>
      <ReturnsInstrumentResult
        result={{
          pnl: { ...partial, value: "0", reason_codes: [] },
          rate: m("0", "fraction", "modified_dietz"),
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("Результат ₽")).toBeVisible();
  expect(screen.getByText("0 ₽")).toBeVisible();
  expect(screen.queryByText("Сумма по доступным данным ₽")).toBeNull();
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

test("shows observed partial payouts without presenting them as total result", () => {
  const detail = detailFixture();
  detail.pnl = m(null);
  detail.rate = m(null, "fraction", "modified_dietz");
  detail.analysis.components.coupons = {
    ...detail.analysis.components.coupons,
    status: "partial",
    value: "12345",
  };
  detail.analysis.components.dividends.value = null;
  setup({ result: detail, analysis: detail.analysis });
  expect(screen.getByText("Найденные выплаты — данные могут быть неполными")).toBeVisible();
  expect(screen.getByText("123,45 ₽")).toBeVisible();
  expect(screen.getAllByText("—")).toHaveLength(2);
  expect(screen.queryByText("Дивиденды")).toBeNull();
});
test("assumptions on analysis, metrics and events remain visible and deduplicated", () => {
  const detail = detailFixture();
  detail.analysis.assumptions = ["face_value_assumed"];
  detail.analysis.pnl.assumptions = ["face_value_assumed"];
  detail.analysis.events[0].assumptions = ["income_assumed"];
  setup({ result: detail, analysis: detail.analysis });
  const notes = screen.getByText("Допущения");
  expect(notes).toBeVisible();
  expect(notes.closest("details")).not.toHaveAttribute("open");
  notes.click();
  expect(notes.closest("details")).toHaveTextContent("Номинал сделки принят с допущением");
  expect(notes.closest("details")).toHaveTextContent(
    "Классификация выплаты основана на правиле по умолчанию",
  );
  expect(notes.closest("details")?.textContent?.match(/Номинал сделки/g)).toHaveLength(1);
});
test("absent result shows dashes without repeating a status or inventing zero", () => {
  const { container } = setup({ result: null });
  expect(within(container).getAllByText("—")).toHaveLength(2);
  expect(screen.getByRole("note")).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent(
    "Нет подтверждённого значения для этого периода.",
  );
  expect(screen.queryByText("0 ₽")).toBeNull();
});

test("excluded or stale events do not label the result with unused assumptions", () => {
  const detail = detailFixture();
  detail.analysis.events[0].assumptions = ["income_assumed"];
  detail.analysis.events[0].current = false;
  setup({ result: detail, analysis: detail.analysis });
  expect(screen.queryByText("Допущения")).toBeNull();
});

test("missing metrics with equal translated reasons have one visible explanation", () => {
  setup({
    result: {
      pnl: { ...m(null), reason_codes: ["unknown_flow"] },
      rate: { ...m(null, "fraction"), reason_codes: ["unknown_flows"] },
    },
  });
  const note = screen.getByRole("note");
  expect(note).toBeVisible();
  expect(note).toHaveTextContent(/^Не все движения денег определены\.$/);
  expect(screen.getAllByText("—")).toHaveLength(2);
});

test("numeric zero and partial values do not acquire a missing-data note from reason codes", () => {
  setup({
    result: {
      pnl: { ...m("0"), reason_codes: ["clean_partial_result", "missing_endpoint"] },
      rate: { ...m("0", "fraction"), reason_codes: ["missing_endpoint"] },
    },
  });
  expect(screen.getByText("0 ₽")).toBeVisible();
  expect(screen.getByText("0,00%")).toBeVisible();
  expect(screen.getByText("Сумма по доступным данным ₽")).toBeVisible();
  expect(screen.queryByRole("note")).toBeNull();
});

test("a null metric without reasons receives a short visible fallback", () => {
  setup({ result: { pnl: { ...m(null), reason_codes: [] }, rate: m("0", "fraction") } });
  expect(screen.getByRole("note")).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent(
    "Нет подтверждённого значения для этого периода.",
  );
});
