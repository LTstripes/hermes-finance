import { describe, expect, it } from "vitest";
import { legacyMonthPeriod, legacyReturnsHref } from "./ReturnsLegacyRedirect";

describe("retired Returns links", () => {
  it.each([
    ["", "", "/v2/returns"],
    ["?diagnostics=1", "", "/v2/returns"],
    [
      "?scope=account&account_id=7&start=2030-01-01&end=2030-02-01",
      "#details",
      "/v2/returns/account?start=2030-01-01&end=2030-02-01&scope=account%3A7#details",
    ],
    ["?month=7", "", "/v2/returns/account?month=7"],
    [
      "?source_account=SYNTH-A&bond_period=2030-02-01&bond_isin=RU000A000001",
      "#bond-slice",
      "/v2/returns/account?scope=source%3ASYNTH-A&isin=RU000A000001&start=2030-01-31&end=2030-02-28#returns-instruments",
    ],
    [
      "?source_account=SYNTH-A",
      "#bond-slice",
      "/v2/returns/account?scope=source%3ASYNTH-A&period=history#returns-instruments",
    ],
    [
      "?start=bad&start=other&scope=portfolio",
      "#keep",
      "/v2/returns/account?start=bad&start=other&scope=portfolio#keep",
    ],
    [
      "?scope=account&account_id=7&account_id=8",
      "",
      "/v2/returns/account?scope=account%3A7&scope=account%3A8",
    ],
  ])("maps %s without inventing financial context", (search, hash, expected) => {
    expect(legacyReturnsHref(search, hash)).toBe(expected);
  });

  it("uses exact calendar boundaries, including leap February", () => {
    expect(legacyMonthPeriod("2032-02")).toEqual({ start: "2032-01-31", end: "2032-02-29" });
    expect(legacyMonthPeriod("2030-13")).toBeNull();
    expect(legacyMonthPeriod("2030-02-12")).toBeNull();
  });
});
