import { describe, expect, it } from "vitest";

import { defaultCloneTarget, lastDayOfMonth, nextPeriod } from "./period";

describe("period helpers", () => {
  it("computes last day of month", () => {
    expect(lastDayOfMonth(2026, 2)).toBe("2026-02-28");
    expect(lastDayOfMonth(2024, 2)).toBe("2024-02-29");
    expect(lastDayOfMonth(2026, 7)).toBe("2026-07-31");
  });

  it("advances to next period across year boundary", () => {
    expect(nextPeriod(2026, 7)).toEqual({ year: 2026, month: 8 });
    expect(nextPeriod(2026, 12)).toEqual({ year: 2027, month: 1 });
  });

  it("builds default clone target", () => {
    expect(defaultCloneTarget({ year: 2026, month: 7 })).toEqual({
      year: 2026,
      month: 8,
      snapshot_date: "2026-08-31",
    });
  });
});
