import { expect, it } from "vitest";
import { shortInstrumentName } from "./instrumentName";

it("removes known identity suffixes and preserves meaningful parentheses", () => {
  expect(
    shortInstrumentName({
      name: "Synthetic (series 2) (SYN) (RU000SYN0001)",
      ticker: "SYN",
      isin: "RU000SYN0001",
    }),
  ).toBe("Synthetic (series 2)");
  expect(shortInstrumentName({ name: "", ticker: null, isin: "RU000SYN0001" })).toBe(
    "RU000SYN0001",
  );
});
