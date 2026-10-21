import { describe, expect, it } from "vitest";

import { selectPlaywrightProjects } from "./playwrightProjects";

describe("selectPlaywrightProjects", () => {
  it("fails clearly when a requested project is unknown", () => {
    expect(() =>
      selectPlaywrightProjects(["chromium", "statement", "what-if"], ["missing"]),
    ).toThrow(
      'Unknown Playwright project name(s): "missing". Valid project names: chromium, statement, what-if',
    );
  });

  it("rejects an unknown project even when another requested project is valid", () => {
    expect(() =>
      selectPlaywrightProjects(["chromium", "statement"], ["chromium", "missing"]),
    ).toThrow('Unknown Playwright project name(s): "missing"');
  });

  it("preserves case-insensitive glob selection", () => {
    expect(
      selectPlaywrightProjects(
        ["chromium", "instrument-uat", "instrument-trades"],
        ["INSTRUMENT-*"],
      ),
    ).toEqual(["instrument-uat", "instrument-trades"]);
  });
});
