import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { AnnualReturn } from "./overall";
import { overallFixture } from "./overallFixtures";
import { ReturnsAnnualRate } from "./ReturnsAnnualRate";

test.each([89, 90, 253, 364, 365])("annual rate presentation at %s days", (days) => {
  const fixture = overallFixture();
  const provisional = days >= 90 && days < 365;
  const value: AnnualReturn = {
    pnl: fixture.overall.pnl,
    rate: {
      ...fixture.overall.rate,
      value: days < 90 ? null : "0.1515",
      estimate: provisional,
      reason_codes:
        days < 90
          ? ["overall_short_holding"]
          : provisional
            ? ["overall_short_holding_provisional"]
            : [],
    },
    first_operation_date: "2030-01-01",
    valuation_date: "2031-01-01",
    weighted_holding_days: String(days),
    eligibility_basis: "capital_weighted_holding_days",
  };
  const { container } = render(<ReturnsAnnualRate value={value} />);
  if (days < 90) {
    expect(screen.getByText(/средний срок вложения денег достигнет 90 дней/)).toBeVisible();
    expect(container).not.toHaveTextContent("%");
  } else {
    const region = screen.getByRole("region", { name: "Годовая доходность" });
    expect(region).toHaveTextContent(provisional ? "≈15,2%" : "15,2%");
    expect(region.textContent?.includes("≈")).toBe(provisional);
    expect(region.textContent?.includes("процент пока предварительный")).toBe(provisional);
    if (provisional)
      expect(region).toHaveTextContent(`деньги вложены в среднем ${Math.floor(days / 30.4)} мес.`);
  }
  expect(container).not.toHaveTextContent("overall_");
});
