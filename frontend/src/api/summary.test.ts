import { afterEach, describe, expect, it, vi } from "vitest";

import { getMonthSummary } from "./summary";

function errorResponse(code: string, message: string): Response {
  return new Response(
    JSON.stringify({
      error: { code, message, details: [] },
    }),
    { status: 422, headers: { "Content-Type": "application/json" } },
  );
}

describe("getMonthSummary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the editor loadable when salary-tax history is incomplete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        errorResponse(
          "salary_tax_history_incomplete",
          "salary tax history is incomplete before 2026-07; missing known month(s): 2026-01",
        ),
      ),
    );

    const summary = await getMonthSummary(7);

    expect(summary.month.id).toBe(7);
    expect(summary.salary_tax.tax.amount).toBe("");
    expect(summary.salary_tax.calculated_net.amount).toBe("");
  });

  it("does not hide unrelated summary failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errorResponse("unprocessable", "different failure")),
    );

    await expect(getMonthSummary(7)).rejects.toMatchObject({
      code: "unprocessable",
      message: "different failure",
    });
  });
});
