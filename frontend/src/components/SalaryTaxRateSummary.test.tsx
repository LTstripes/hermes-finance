import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SalaryTaxRateSummary } from "./SalaryTaxRateSummary";

describe("SalaryTaxRateSummary", () => {
  it("shows a single backend-derived marginal rate", () => {
    render(<SalaryTaxRateSummary parts={[{ rate_bps: 1500 }]} />);

    expect(screen.getByText("Текущая ставка НДФЛ")).toBeInTheDocument();
    expect(screen.getByText("15%")).toBeInTheDocument();
  });

  it("shows all applied rates when a payment crosses a threshold", () => {
    render(<SalaryTaxRateSummary parts={[{ rate_bps: 1300 }, { rate_bps: 1500 }]} />);

    expect(screen.getByText("Ставки НДФЛ в этой выплате")).toBeInTheDocument();
    expect(screen.getByText("13% + 15%")).toBeInTheDocument();
    expect(screen.getByText("Текущая ступень после выплаты: 15%.")).toBeInTheDocument();
  });

  it("does not invent a rate when tax calculation is unavailable", () => {
    render(<SalaryTaxRateSummary parts={[]} />);

    expect(screen.getByText("Ставка НДФЛ")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
