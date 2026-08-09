import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatMoney } from "../../lib/format";
import { buildGappedSeries } from "../../lib/chartData";
import { MoneyTooltip } from "./MoneyTooltip";

function tooltipProps(
  points: { year: number; month: number; amount: string }[],
  active = true,
  index = 0,
) {
  return {
    active,
    accessibilityLayer: false,
    activeIndex: undefined,
    coordinate: undefined,
    payload: [{ payload: buildGappedSeries(points)[index] ?? null }],
  } as unknown as Parameters<typeof MoneyTooltip>[0];
}

describe("MoneyTooltip", () => {
  it("shows the month and the formatted RUB amount for an active datum", () => {
    render(<MoneyTooltip {...tooltipProps([{ year: 2031, month: 1, amount: "1234567.00" }])} />);
    expect(screen.getByText("Январь 2031")).toBeInTheDocument();
    const amount = screen.getByText(
      (_, el) => el?.classList.contains("chart-tooltip__amount") ?? false,
    );
    expect(amount.textContent).toBe(formatMoney("1234567.00"));
  });

  it("renders nothing when the tooltip is inactive", () => {
    const { container } = render(
      <MoneyTooltip {...tooltipProps([{ year: 2031, month: 1, amount: "100000.00" }], false)} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a gap point (missing month)", () => {
    const { container } = render(
      <MoneyTooltip
        {...tooltipProps(
          [
            { year: 2031, month: 1, amount: "100000.00" },
            { year: 2031, month: 3, amount: "140000.00" },
          ],
          true,
          1,
        )}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
