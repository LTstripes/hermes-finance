import { describe, expect, it } from "vitest";

import {
  buildArchive,
  contextualHistoryWindow,
  GAP_ROW_LABEL,
  REPORTS_PATH,
  reportPath,
  resolveReportTarget,
  seriesPosition,
  SINGLE_REPORT_NOTE,
} from "./reportsArchive";
import {
  makeUiV2ArchiveHistory,
  makeUiV2LongHistory,
  uiV2ArchiveMonths,
  uiV2CapitalMonthId,
  uiV2LongHistoryFirstMonthId,
  uiV2Months,
  uiV2PriorYearClosedMonthId,
} from "../test/uiV2Fixtures";

const history = makeUiV2ArchiveHistory();

function archive(moneyConfirmed = true) {
  return buildArchive({
    months: uiV2ArchiveMonths,
    points: history.points,
    moneyConfirmed,
  });
}

describe("buildArchive", () => {
  it("groups closed reports by year and lists the newest month first", () => {
    const model = archive();

    expect(model.groups.map((group) => group.year)).toEqual([2031, 2030]);
    expect(model.closedCount).toBe(5);
    expect(model.groups[0].rows.map((row) => row.key)).toEqual([
      "report-91",
      "gap-2031-6",
      "report-90",
      "report-89",
      "gap-2031-3",
      "report-88",
    ]);
    expect(model.groups[1].rows.map((row) => row.key)).toEqual(["report-87"]);
  });

  it("marks only the latest closed report as the current report", () => {
    const model = archive();
    const rows = model.groups.flatMap((group) => group.rows).filter((row) => row.kind === "report");
    const current = rows.filter((row) => row.isCurrent);

    expect(current).toHaveLength(1);
    expect(current[0].month.id).toBe(uiV2CapitalMonthId);
    expect(current[0].statusLabel).toBe("Текущий отчёт");
    expect(current[0].actionPath).toBe("/v2");
    const older = rows.find((row) => row.month.id === 90);
    expect(older?.statusLabel).toBe("Утверждён");
    expect(older?.actionLabel).toBe("Открыть отчёт");
    expect(older?.actionPath).toBe(reportPath(90));
  });

  it("never renders a draft as a row and never marks a gap outside the closed span", () => {
    const model = archive();
    const rows = model.groups.flatMap((group) => group.rows);

    expect(rows.some((row) => row.kind === "report" && row.month.id === 12)).toBe(false);
    expect(rows.filter((row) => row.kind === "gap")).toHaveLength(2);
    // August 2031 is the newer draft, not a gap.
    expect(model.groups[0].rows.some((row) => row.kind === "gap" && row.month === 8)).toBe(false);
    // No marker after the latest or before the earliest closed report of a year.
    expect(model.groups[0].rows.some((row) => row.kind === "gap" && row.month === 1)).toBe(false);
    expect(model.groups[1].rows.some((row) => row.kind === "gap")).toBe(false);
    expect(model.newerDraft?.id).toBe(12);
    expect(GAP_ROW_LABEL).toBe("отчёта нет");
  });

  it("hides every money point when the composition series is not confirmed", () => {
    const model = archive(false);
    const rows = model.groups.flatMap((group) => group.rows).filter((row) => row.kind === "report");

    expect(rows.every((row) => row.point === null)).toBe(true);
    expect(
      model.groups.flatMap((group) => group.rows).filter((row) => row.kind === "gap"),
    ).toHaveLength(2);
  });

  it("uses the canonical point of each month without recomputing it", () => {
    const model = archive();
    const may = model.groups[0].rows.find((row) => row.kind === "report" && row.month.id === 90);
    if (may?.kind !== "report") throw new Error("May 2031 row is missing");

    expect(may.point?.liquid_capital_net.amount).toBe("2761300.00");
    expect(may.point?.liquid_assets_total.amount).toBe("3151300.00");
    expect(may.point?.included_debts.amount).toBe("390000.00");
  });

  it("notes that history starts with the second closed report", () => {
    const model = buildArchive({
      months: [uiV2Months[0], uiV2Months[1]],
      points: history.points,
      moneyConfirmed: true,
    });

    expect(model.closedCount).toBe(1);
    expect(model.singleReportNote).toBe(SINGLE_REPORT_NOTE);
    expect(model.groups.flatMap((group) => group.rows).map((row) => row.key)).toEqual([
      "report-91",
    ]);
  });
});

describe("resolveReportTarget", () => {
  it("rejects a malformed id with the accepted month regex", () => {
    for (const value of ["012", "0", "abc", "1.2", "-3", undefined]) {
      expect(resolveReportTarget(value, uiV2ArchiveMonths).kind).toBe("malformed");
    }
  });

  it("reports an unknown id as missing", () => {
    expect(resolveReportTarget("999", uiV2ArchiveMonths).kind).toBe("missing");
  });

  it("separates draft, current and historical targets", () => {
    expect(resolveReportTarget("12", uiV2ArchiveMonths).kind).toBe("draft");
    expect(resolveReportTarget(String(uiV2CapitalMonthId), uiV2ArchiveMonths).kind).toBe("current");
    expect(resolveReportTarget("90", uiV2ArchiveMonths).kind).toBe("older");
    expect(resolveReportTarget(String(uiV2PriorYearClosedMonthId), uiV2ArchiveMonths).kind).toBe(
      "older",
    );
  });
});

describe("seriesPosition", () => {
  it("resolves adjacent closed neighbours and never fabricates one", () => {
    const earliest = seriesPosition(history.points, uiV2PriorYearClosedMonthId);
    expect(earliest?.previous).toBeNull();
    expect(earliest?.next?.reporting_month_id).toBe(88);

    const may = seriesPosition(history.points, 90);
    expect(may?.previous?.reporting_month_id).toBe(89);
    expect(may?.next?.reporting_month_id).toBe(91);
    expect(may?.point.year).toBe(2031);
    expect(may?.point.month).toBe(5);

    expect(seriesPosition(history.points, 999)).toBeNull();
  });
});

describe("paths", () => {
  it("uses one contextual archive path", () => {
    expect(REPORTS_PATH).toBe("/v2/reports");
    expect(reportPath(90)).toBe("/v2/reports/90");
  });
});

describe("contextualHistoryWindow", () => {
  const long = makeUiV2LongHistory({ count: 24 });
  const points = long.history.points;
  // 2030-01 … 2031-12. The selected report is the twelfth-old month, so it is
  // outside the latest twelve CLOSED reports (2031-01 … 2031-12).
  const selectedId = uiV2LongHistoryFirstMonthId + 11;

  it("regression: keeps a historical report that is older than the latest 12 inside its own 3/12 window", () => {
    const naiveLatestTwelve = points.slice(-12).map((point) => point.reporting_month_id);
    expect(naiveLatestTwelve).not.toContain(selectedId);

    const twelve = contextualHistoryWindow(points, selectedId, 12);
    expect(twelve).toHaveLength(12);
    expect(twelve[0]?.reporting_month_id).toBe(uiV2LongHistoryFirstMonthId);
    expect(twelve.at(-1)?.reporting_month_id).toBe(selectedId);
    expect(twelve.map((point) => point.reporting_month_id)).toContain(selectedId);

    const three = contextualHistoryWindow(points, selectedId, 3);
    expect(three.map((point) => point.reporting_month_id)).toEqual([
      uiV2LongHistoryFirstMonthId + 9,
      uiV2LongHistoryFirstMonthId + 10,
      selectedId,
    ]);
    expect(three.at(-1)?.reporting_month_id).toBe(selectedId);
    expect(three.map((point) => point.reporting_month_id)).toContain(selectedId);
  });

  it("never starts before the first closed report and never drops the selected one", () => {
    const oldest = contextualHistoryWindow(points, uiV2LongHistoryFirstMonthId, 12);
    expect(oldest.map((point) => point.reporting_month_id)).toEqual([uiV2LongHistoryFirstMonthId]);

    const newest = uiV2LongHistoryFirstMonthId + 23;
    const newestTwelve = contextualHistoryWindow(points, newest, 12);
    expect(newestTwelve).toHaveLength(12);
    expect(newestTwelve[0]?.reporting_month_id).toBe(uiV2LongHistoryFirstMonthId + 12);
    expect(newestTwelve.at(-1)?.reporting_month_id).toBe(newest);

    const newestThree = contextualHistoryWindow(points, newest, 3);
    expect(newestThree.map((point) => point.reporting_month_id)).toEqual([
      uiV2LongHistoryFirstMonthId + 21,
      uiV2LongHistoryFirstMonthId + 22,
      newest,
    ]);
  });

  it("keeps the whole closed series for «Всё время» and for an unknown selection", () => {
    expect(contextualHistoryWindow(points, selectedId, "all")).toHaveLength(points.length);
    expect(contextualHistoryWindow(points, 9999, 12)).toHaveLength(points.length);
  });
});
