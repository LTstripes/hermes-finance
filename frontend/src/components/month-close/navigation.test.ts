import { describe, expect, it } from "vitest";

import { parseMonthlyCloseReturnContext, routeForGuidedAction } from "./navigation";

describe("monthly close navigation", () => {
  it("accepts only the enumerated return context", () => {
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close&step=market_quotes&monthId=42"),
      ),
    ).toEqual({ monthId: 42, step: "market_quotes" });
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=https://evil.example&step=market_quotes&monthId=42"),
      ),
    ).toBeNull();
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close&step=../../settings&monthId=42"),
      ),
    ).toBeNull();
  });

  it("maps action ids to fixed local routes with the requested month", () => {
    expect(routeForGuidedAction("open_freshness", 7, "readiness")).toBe(
      "/freshness?from=monthly-close&step=readiness&monthId=7",
    );
    expect(routeForGuidedAction("set_snapshot_date", 3, "month_setup")).toBe(
      "/months/3?section=general&from=monthly-close&step=month_setup&monthId=3",
    );
  });
});
