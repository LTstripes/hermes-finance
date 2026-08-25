import { afterEach, describe, expect, it, vi } from "vitest";

import { updateDebt } from "./debts";
import { updateExpense } from "./expenses";
import { updateInvestmentFlow } from "./investmentFlows";
import { updateProperty } from "./properties";
import { updateSaving } from "./savings";

function jsonOk(data: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(data),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("month editor PATCH wrappers", () => {
  it("patches an investment flow without inventing a recreate path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk({ id: 41 }));
    vi.stubGlobal("fetch", fetchMock);
    await updateInvestmentFlow(41, {
      net_amount: { amount: "870.00", currency: "RUB" },
      event_date: "2031-01-15",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/investment-flows/41",
      expect.objectContaining({ method: "PATCH" }),
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(JSON.parse(String(init?.body))).toEqual({
      net_amount: { amount: "870.00", currency: "RUB" },
      event_date: "2031-01-15",
    });
  });

  it("patches expenses, savings, debts and properties", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonOk({ id: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    await updateExpense(11, { category: "Аренда" });
    await updateSaving(21, { destination: "Подушка" });
    await updateDebt(31, { name: "Карта" });
    await updateProperty(41, { name: "Квартира" });
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ["/api/expenses/11", "PATCH"],
      ["/api/savings/21", "PATCH"],
      ["/api/debts/31", "PATCH"],
      ["/api/properties/41", "PATCH"],
    ]);
  });
});
