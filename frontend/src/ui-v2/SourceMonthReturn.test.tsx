import { expect, it } from "vitest";
import { formatSourceReturnRate as sourceReturnRate } from "../lib/sourceReturnFormat";
import { sourceReturnMoney } from "./SourceMonthReturn";

it("keeps exact kopecks at MAX_SAFE_INTEGER and refuses an already imprecise JSON integer", () => {
  expect(sourceReturnMoney(Number.MAX_SAFE_INTEGER)).toBe(
    "90\u00a0071\u00a0992\u00a0547\u00a0409,91\u00a0₽",
  );
  expect(sourceReturnMoney(-Number.MAX_SAFE_INTEGER)).toBe(
    "−90\u00a0071\u00a0992\u00a0547\u00a0409,91\u00a0₽",
  );
  expect(sourceReturnMoney(Number.MAX_SAFE_INTEGER + 1)).toContain("вне точного диапазона");
  expect(sourceReturnMoney(null)).toBe("—");
});

it("converts the Decimal fraction to percentage text without binary financial arithmetic", () => {
  expect(sourceReturnRate("0.002309773164046106")).toBe("0,23%");
  expect(sourceReturnRate("-0.007720534510707254")).toBe("−0,77%");
  expect(sourceReturnRate("0E-60")).toBe("0,00%");
  expect(sourceReturnRate(null)).toBe("—");
});
