import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { GoldResultSplit } from "./GoldResultSplit";
import type { Metric } from "./model";

test("shows the proved sale result independently of a missing valuation", () => {
  const metric = (value: string | null): Metric => ({
    value,
    reason_codes: value === null ? ["gold_saved_valuation_unavailable"] : [],
    method: "clean_gold_fifo",
    estimate: true,
    unit: "kopecks",
  });
  const { container } = render(
    <MemoryRouter>
      <dl>
        <GoldResultSplit
          value={{ realized_result: metric("12345"), unrealized_result: metric(null) }}
        />
      </dl>
    </MemoryRouter>,
  );
  expect(screen.getByText("Зафиксировано")).toBeVisible();
  expect(screen.getByText("В цене")).toBeVisible();
  expect(container.querySelectorAll("dd")[0]).toHaveTextContent("+123 ₽");
  expect(container.querySelectorAll("dd")[1]).toHaveTextContent("—");
});
