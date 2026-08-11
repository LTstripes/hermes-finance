import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTaxBrackets, updateTaxBrackets, type TaxBracketYearConfig } from "../api/taxBrackets";
import { TaxBracketsPanel } from "./TaxBracketsPanel";

vi.mock("../api/taxBrackets", () => ({
  getTaxBrackets: vi.fn(),
  updateTaxBrackets: vi.fn(),
}));

const getTaxBracketsMock = vi.mocked(getTaxBrackets);
const updateTaxBracketsMock = vi.mocked(updateTaxBrackets);

function config(overrides: Partial<TaxBracketYearConfig> = {}): TaxBracketYearConfig {
  return {
    year: new Date().getFullYear(),
    effective_from: `${new Date().getFullYear()}-01-01`,
    effective_to: `${new Date().getFullYear()}-12-31`,
    source: "official_default",
    contract_version: "tax_brackets_year_v1",
    mutable: true,
    closed_months: [],
    brackets: [
      {
        threshold_from: { amount: "0.00", currency: "RUB" },
        threshold_to: { amount: "100000.00", currency: "RUB" },
        rate_bps: 1300,
      },
      {
        threshold_from: { amount: "100000.00", currency: "RUB" },
        threshold_to: null,
        rate_bps: 1500,
      },
    ],
    ...overrides,
  };
}

describe("TaxBracketsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTaxBracketsMock.mockResolvedValue(config());
    updateTaxBracketsMock.mockImplementation(async (_year, payload) => ({
      ...config({ source: "manual_configuration" }),
      brackets: payload.brackets,
    }));
  });

  it("shows effective/source metadata and saves one exact contiguous set", async () => {
    const user = userEvent.setup();
    render(<TaxBracketsPanel />);

    expect(await screen.findByText("Официальная шкала")).toBeInTheDocument();
    expect(screen.getByText("Можно редактировать")).toBeInTheDocument();
    expect(screen.queryByText("tax_brackets_year_v1")).toBeNull();

    const upper = screen.getByLabelText("Верхняя граница ступени 1");
    await user.clear(upper);
    await user.type(upper, "125000,50");
    const firstRate = screen.getByLabelText("Ставка ступени 1");
    await user.clear(firstRate);
    await user.type(firstRate, "13,25");

    await user.click(screen.getByRole("button", { name: "Сохранить налоговые ступени" }));

    await waitFor(() =>
      expect(updateTaxBracketsMock).toHaveBeenCalledWith(new Date().getFullYear(), {
        brackets: [
          {
            threshold_from: { amount: "0.00", currency: "RUB" },
            threshold_to: { amount: "125000.50", currency: "RUB" },
            rate_bps: 1325,
          },
          {
            threshold_from: { amount: "125000.50", currency: "RUB" },
            threshold_to: null,
            rate_bps: 1500,
          },
        ],
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Налоговые ступени сохранены");
    expect(screen.getByText("Пользовательская шкала")).toBeInTheDocument();
  });

  it("locks editing when the year contains closed months", async () => {
    const year = new Date().getFullYear();
    getTaxBracketsMock.mockResolvedValue(
      config({ mutable: false, closed_months: [`${year}-01`, `${year}-02`] }),
    );
    const user = userEvent.setup();
    render(<TaxBracketsPanel />);

    expect(await screen.findByText("Год зафиксирован")).toBeInTheDocument();
    expect(screen.getByText(/январь/)).toBeInTheDocument();
    expect(screen.getByText(/февраль/)).toBeInTheDocument();
    expect(screen.getByLabelText("Ставка ступени 1")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Сохранить налоговые ступени" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Открыть год" }));
    expect(updateTaxBracketsMock).not.toHaveBeenCalled();
  });
});
