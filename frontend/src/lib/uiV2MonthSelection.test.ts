import { describe, expect, it } from "vitest";

import { uiV2Months } from "../test/uiV2Fixtures";
import {
  dataAppPath,
  monthWorkspacePath,
  resolveMonthSelection,
  selectDiagnosticMonth,
  sortReportingMonths,
} from "../ui-v2/monthSelection";

describe("UI v2 reporting-period URL", () => {
  it("sorts calendar periods, not insertion IDs, without mutating shared cache", () => {
    expect(sortReportingMonths(uiV2Months).map((month) => month.id)).toEqual([12, 91, 90, 89, 88]);
    expect(uiV2Months.map((month) => month.id)).toEqual([91, 12, 90, 89, 88]);
  });
  it("leaves automatic entry distinct from an explicit selected period", () => {
    expect(resolveMonthSelection([], uiV2Months)).toEqual({ kind: "automatic" });
    expect(resolveMonthSelection(["91"], uiV2Months)).toEqual({
      kind: "selected",
      month: uiV2Months[0],
    });
  });
  it.each(["", "0", "-1", "1.0", "1e2", " 12", "12x", "012", "9007199254740992"])(
    "rejects ambiguous or invalid explicit ID %s",
    (value) => expect(resolveMonthSelection([value], uiV2Months)).toEqual({ kind: "invalid" }),
  );
  it("does not replace deleted IDs or conflicting query parameters with the latest month", () => {
    expect(resolveMonthSelection(["404"], uiV2Months)).toEqual({ kind: "missing" });
    expect(resolveMonthSelection(["12", "91"], uiV2Months)).toEqual({ kind: "invalid" });
  });
  it("encodes the complete period/step address without persistent financial state", () => {
    expect(monthWorkspacePath(12, "actual_payouts")).toBe("/v2?month=12&step=actual_payouts");
  });
});

describe("Data/App diagnostic month", () => {
  it("prefers the newest DRAFT when one exists", () => {
    expect(selectDiagnosticMonth(uiV2Months)?.id).toBe(12);
  });

  it("falls back to the latest CLOSED when no draft exists", () => {
    const closedOnly = uiV2Months.filter((month) => month.status === "closed");
    expect(selectDiagnosticMonth(closedOnly)?.id).toBe(91);
  });

  it("returns null when there are no months", () => {
    expect(selectDiagnosticMonth([])).toBeNull();
  });

  it("builds Data/App paths with optional month identity", () => {
    expect(dataAppPath("sources")).toBe("/v2/data");
    expect(dataAppPath("reconciliation", 12)).toBe("/v2/data/reconciliation?month=12");
    expect(dataAppPath("catalogs")).toBe("/v2/data/catalogs");
    expect(dataAppPath("files")).toBe("/v2/data/files");
    expect(dataAppPath("app", 91)).toBe("/v2/data/app?month=91");
  });
});
