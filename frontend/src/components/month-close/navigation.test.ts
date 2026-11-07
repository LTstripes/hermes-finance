import { describe, expect, it } from "vitest";

import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withMonthlyCloseReturn,
  withSelectedReturnMonth,
} from "./navigation";

describe("monthly close navigation", () => {
  it.each([
    [
      "/v2/data/months/42",
      "readiness",
      "/v2/data/months/42?from=monthly-close-v2&step=readiness&monthId=42",
    ],
    [
      "/v2/data/months/42?section=payouts",
      "future_payouts",
      "/v2/data/months/42?section=payouts&from=monthly-close-v2&step=future_payouts&monthId=42",
    ],
    [
      "/v2/data/months?month=42",
      "month_setup",
      "/v2/data/months?month=42&from=monthly-close-v2&step=month_setup&monthId=42",
    ],
  ] as const)(
    "preserves live editor and list return context for %s",
    (destination, step, expected) => {
      const href = withMonthlyCloseReturn(destination, 42, step);
      expect(href).toBe(expected);
      const context = parseMonthlyCloseReturnContext(
        new URL(href, "http://synthetic").searchParams,
      );
      expect(context).toEqual({
        monthId: 42,
        origin: "monthly-close-v2",
        step,
      });
      if (context === null) throw new Error("Expected a valid monthly close return context");
      expect(monthlyCloseReturnPath(context)).toBe(`/v2/close?month=42&step=${step}`);
    },
  );

  it("accepts only the enumerated v2 return context", () => {
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close-v2&step=market_quotes&monthId=42"),
      ),
    ).toEqual({ monthId: 42, origin: "monthly-close-v2", step: "market_quotes" });
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close&step=market_quotes&monthId=42"),
      ),
    ).toBeNull();
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=https://evil.example&step=market_quotes&monthId=42"),
      ),
    ).toBeNull();
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close-v2&step=../../settings&monthId=42"),
      ),
    ).toBeNull();
  });

  it("updates the selected month and bounded close return together", () => {
    expect(
      withSelectedReturnMonth(
        new URLSearchParams("month=12&from=monthly-close-v2&step=readiness&monthId=12"),
        91,
      ).toString(),
    ).toBe("month=91&from=monthly-close-v2&step=readiness&monthId=91");
    expect(
      withSelectedReturnMonth(
        new URLSearchParams("month=0&from=https://evil.test&monthId=12"),
        91,
      ).toString(),
    ).toBe("month=91&from=https%3A%2F%2Fevil.test&monthId=12");
  });
});
