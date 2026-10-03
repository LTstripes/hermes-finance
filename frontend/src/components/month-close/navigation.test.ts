import { describe, expect, it } from "vitest";

import {
  parseMonthlyCloseReturnContext,
  routeForGuidedAction,
  withSelectedReturnMonth,
} from "./navigation";

describe("monthly close navigation", () => {
  it("routes the v2 Alfa action to the exact native month with canonical return context", () => {
    expect(routeForGuidedAction("open_alfa_preview", 42, "alfa_baseline", "monthly-close-v2")).toBe(
      "/v2/data/alfa-baseline?month=42&from=monthly-close-v2&step=alfa_baseline&monthId=42",
    );
  });

  it("preserves the legacy Alfa action route", () => {
    expect(routeForGuidedAction("open_alfa_preview", 42, "alfa_baseline", "monthly-close")).toBe(
      "/accounts?from=monthly-close&step=alfa_baseline&monthId=42",
    );
  });

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
    expect(routeForGuidedAction("open_cash_flow_ladder", 42, "next_month_outlook")).toBe(
      "/payouts?from=monthly-close&step=next_month_outlook&monthId=42",
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

  it("routes the v2 payout actions to the exact native month with canonical return context", () => {
    expect(
      routeForGuidedAction("open_payout_batch_preview", 42, "future_payouts", "monthly-close-v2"),
    ).toBe("/v2/data/payouts?month=42&from=monthly-close-v2&step=future_payouts&monthId=42");
    expect(
      routeForGuidedAction("open_cash_flow_ladder", 42, "next_month_outlook", "monthly-close-v2"),
    ).toBe("/v2/data/payouts?month=42&from=monthly-close-v2&step=next_month_outlook&monthId=42");
  });

  it("routes the v2 statement action to the native statement-import anchor", () => {
    expect(
      routeForGuidedAction("choose_statement_file", 42, "actual_payouts", "monthly-close-v2"),
    ).toBe(
      "/v2/data/payouts?month=42&from=monthly-close-v2&step=actual_payouts&monthId=42#statement-import",
    );
    // The legacy monthly close keeps its own supported route.
    expect(
      routeForGuidedAction("choose_statement_file", 42, "actual_payouts", "monthly-close"),
    ).toBe("/payouts?from=monthly-close&step=actual_payouts&monthId=42");
  });

  it.each([
    ["open_month", "month_setup", "/v2/data/months/42"],
    ["set_snapshot_date", "month_setup", "/v2/data/months/42?section=general"],
    ["clone_next_month", "next_month_outlook", "/v2/data/months?month=42"],
  ] as const)("keeps the exact close return on native %s", (action, step, destination) => {
    const separator = destination.includes("?") ? "&" : "?";
    expect(routeForGuidedAction(action, 42, step, "monthly-close-v2")).toBe(
      `${destination}${separator}from=monthly-close-v2&step=${step}&monthId=42`,
    );
  });

  it("hands quotes off to the actual quote panel without requesting the provider", () => {
    expect(
      routeForGuidedAction("open_quote_preview", 42, "market_quotes", "monthly-close-v2"),
    ).toBe(
      "/v2/data/months/42?section=positions&from=monthly-close-v2&step=market_quotes&monthId=42#month-quotes",
    );
  });

  it("keeps final review and confirmation in native Close", () => {
    expect(routeForGuidedAction("open_final_review", 42, "readiness", "monthly-close-v2")).toBe(
      "/v2/close?month=42&step=final_review_close",
    );
    expect(
      routeForGuidedAction("confirm_close", 42, "final_review_close", "monthly-close-v2"),
    ).toBe("/v2/close?month=42&step=final_review_close");
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
