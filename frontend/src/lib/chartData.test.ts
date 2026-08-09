import { describe, expect, it } from "vitest";

import { formatMonth } from "./format";
import { buildGappedSeries } from "./chartData";

function point(year: number, month: number, amount: string) {
  return { year, month, amount };
}

describe("buildGappedSeries", () => {
  it("keeps contiguous months as one continuous series", () => {
    const data = buildGappedSeries([point(2031, 1, "100000.00"), point(2031, 2, "120000.00")]);
    expect(data).toHaveLength(2);
    expect(data.every((d) => d.rubles != null)).toBe(true);
    expect(data.map((d) => d.key)).toEqual(["2031-01", "2031-02"]);
  });

  it("breaks the line when a month is missing (no interpolation)", () => {
    const data = buildGappedSeries([point(2031, 1, "100000.00"), point(2031, 3, "140000.00")]);
    expect(data).toHaveLength(3);
    expect(data[1].rubles).toBeNull();
    expect(data[0].rubles).not.toBeNull();
    expect(data[2].rubles).not.toBeNull();
  });

  it("treats December→January of next year as contiguous", () => {
    const data = buildGappedSeries([point(2030, 12, "90000.00"), point(2031, 1, "100000.00")]);
    expect(data).toHaveLength(2);
    expect(data.every((d) => d.rubles != null)).toBe(true);
  });

  it("breaks December→February (January skipped)", () => {
    const data = buildGappedSeries([point(2030, 12, "90000.00"), point(2031, 2, "110000.00")]);
    expect(data).toHaveLength(3);
    expect(data[1].rubles).toBeNull();
  });

  it("returns an empty array for no points", () => {
    expect(buildGappedSeries([])).toEqual([]);
  });

  it("keeps the original decimal string for tooltip display", () => {
    const data = buildGappedSeries([point(2031, 1, "1234567.89")]);
    expect(data[0].amount).toBe("1234567.89");
    expect(data[0].label).toBe(formatMonth(2031, 1));
  });
});
