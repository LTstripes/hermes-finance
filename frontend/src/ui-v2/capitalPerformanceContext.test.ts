import { describe, expect, it } from "vitest";

import {
  intervalDays,
  isZeroPercent,
  needsAnnualizationWarning,
  parsePerformanceContext,
  performanceDetailHref,
  shiftCalendarBack,
} from "./capitalPerformanceContext";

function params(query: string): URLSearchParams {
  return new URLSearchParams(query);
}

describe("parsePerformanceContext", () => {
  it("accepts a portfolio interval", () => {
    const result = parsePerformanceContext(params("start=2031-05-31&end=2031-07-31"));
    expect(result.error).toBeNull();
    expect(result.context).toEqual({
      start: "2031-05-31",
      end: "2031-07-31",
      scope: "portfolio",
      accountId: null,
      view: "accounts",
    });
  });

  it("accepts an account drill-in and keeps the view", () => {
    const result = parsePerformanceContext(
      params("start=2031-05-31&end=2031-07-31&scope=account&account_id=3"),
      { accountExists: (id) => id === 3 },
    );
    expect(result.error).toBeNull();
    expect(result.context?.accountId).toBe(3);
  });

  it("rejects a missing interval without a silent default", () => {
    const result = parsePerformanceContext(params(""));
    expect(result.context).toBeNull();
    expect(result.error?.code).toBe("missing_interval");
  });

  it("rejects a partial interval", () => {
    const result = parsePerformanceContext(params("start=2031-05-31"));
    expect(result.error?.code).toBe("partial_interval");
  });

  it("rejects malformed, equal and reversed dates", () => {
    expect(parsePerformanceContext(params("start=nope&end=2031-07-31")).error?.code).toBe(
      "malformed_date",
    );
    expect(parsePerformanceContext(params("start=2031-07-31&end=2031-07-31")).error?.code).toBe(
      "equal_dates",
    );
    expect(parsePerformanceContext(params("start=2031-07-31&end=2031-05-31")).error?.code).toBe(
      "reversed_interval",
    );
  });

  it("rejects an impossible calendar date", () => {
    expect(parsePerformanceContext(params("start=2031-02-30&end=2031-07-31")).error?.code).toBe(
      "malformed_date",
    );
  });

  it("rejects repeated context parameters instead of collapsing them", () => {
    expect(
      parsePerformanceContext(params("start=2031-05-31&start=2031-06-30&end=2031-07-31")).error
        ?.code,
    ).toBe("repeated_param");
    expect(
      parsePerformanceContext(
        params("start=2031-05-31&end=2031-07-31&scope=portfolio&scope=account"),
      ).error?.code,
    ).toBe("repeated_param");
    expect(
      parsePerformanceContext(
        params("start=2031-05-31&end=2031-07-31&scope=account&account_id=3&account_id=3"),
      ).error?.code,
    ).toBe("repeated_param");
  });

  it("rejects invalid scope and view values instead of normalizing them", () => {
    expect(
      parsePerformanceContext(params("start=2031-05-31&end=2031-07-31&scope=banana")).error?.code,
    ).toBe("invalid_scope");
    expect(
      parsePerformanceContext(params("start=2031-05-31&end=2031-07-31&view=grid")).error?.code,
    ).toBe("invalid_view");
  });

  it("keeps the documented defaults for missing scope and view", () => {
    const result = parsePerformanceContext(params("start=2031-05-31&end=2031-07-31"));
    expect(result.context?.scope).toBe("portfolio");
    expect(result.context?.view).toBe("accounts");
  });

  it("requires an account for the account scope and never falls back to portfolio", () => {
    expect(
      parsePerformanceContext(params("start=2031-05-31&end=2031-07-31&scope=account")).error?.code,
    ).toBe("missing_account");
    expect(
      parsePerformanceContext(
        params("start=2031-05-31&end=2031-07-31&scope=account&account_id=9"),
        {
          accountExists: (id) => id === 3,
        },
      ).error?.code,
    ).toBe("unknown_account");
  });

  it("rejects a portfolio scope combined with an account", () => {
    expect(
      parsePerformanceContext(
        params("start=2031-05-31&end=2031-07-31&scope=portfolio&account_id=3"),
      ).error?.code,
    ).toBe("portfolio_account_mismatch");
  });
});

describe("performanceDetailHref", () => {
  it("preserves the full context for deep link, back and refresh", () => {
    expect(
      performanceDetailHref({
        start: "2031-05-31",
        end: "2031-07-31",
        scope: "account",
        accountId: 3,
        view: "accounts",
      }),
    ).toBe("/v2/capital/performance?start=2031-05-31&end=2031-07-31&scope=account&account_id=3");
  });
});

describe("interval helpers", () => {
  it("counts calendar days without financial math", () => {
    expect(intervalDays("2031-05-31", "2031-07-31")).toBe(61);
    expect(intervalDays("nope", "2031-07-31")).toBeNull();
  });

  it("warns about annualization only below 365 days", () => {
    expect(needsAnnualizationWarning("2031-05-31", "2031-07-31")).toBe(true);
    expect(needsAnnualizationWarning("2030-07-31", "2031-07-31")).toBe(false);
  });

  it("detects an exact zero in percentage points", () => {
    expect(isZeroPercent("0")).toBe(true);
    expect(isZeroPercent("0.00")).toBe(true);
    expect(isZeroPercent("-0.00")).toBe(true);
    expect(isZeroPercent("0.01")).toBe(false);
    expect(isZeroPercent("-3.5")).toBe(false);
    expect(isZeroPercent(null)).toBe(false);
  });

  it("shifts calendar presets without interpolation", () => {
    expect(shiftCalendarBack("2031-07-31", 1)).toBe("2031-06-30");
    expect(shiftCalendarBack("2031-03-31", 1)).toBe("2031-02-28");
    expect(shiftCalendarBack("2031-07-15", 3)).toBe("2031-04-15");
  });
});
