import { describe, expect, it } from "vitest";

import {
  parseMonthlyCloseReturnContext,
  routeForGuidedAction,
  withSelectedReturnMonth,
} from "./navigation";

describe("monthly close navigation", () => {
  it("accepts only the enumerated return context", () => {
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close&step=market_quotes&monthId=42"),
      ),
    ).toEqual({ monthId: 42, origin: "monthly-close", step: "market_quotes" });
    expect(
      parseMonthlyCloseReturnContext(
        new URLSearchParams("from=monthly-close-v2&step=market_quotes&monthId=42"),
      ),
    ).toEqual({ monthId: 42, origin: "monthly-close-v2", step: "market_quotes" });
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
    expect(routeForGuidedAction("open_quote_preview", 42, "market_quotes")).toBe(
      "/months/42?section=positions&from=monthly-close&step=market_quotes&monthId=42",
    );
    expect(routeForGuidedAction("open_payout_batch_preview", 42, "future_payouts")).toBe(
      "/payouts?from=monthly-close&step=future_payouts&monthId=42",
    );
    expect(routeForGuidedAction("choose_statement_file", 42, "actual_payouts")).toBe(
      "/payouts?from=monthly-close&step=actual_payouts&monthId=42",
    );
    expect(routeForGuidedAction("open_final_review", 3, "readiness")).toBe(
      "/months/3/close?from=monthly-close&step=readiness&monthId=3#final_review_close",
    );
    expect(routeForGuidedAction("open_freshness", 7, "readiness", "monthly-close-v2")).toBe(
      "/v2/data?month=7&from=monthly-close-v2&step=readiness&monthId=7",
    );
    expect(
      routeForGuidedAction(
        "open_reconciliation_preview",
        7,
        "broker_reconciliation",
        "monthly-close-v2",
      ),
    ).toBe(
      "/v2/data/reconciliation?month=7&from=monthly-close-v2&step=broker_reconciliation&monthId=7",
    );
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
