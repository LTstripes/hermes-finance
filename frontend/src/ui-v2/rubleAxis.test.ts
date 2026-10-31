import { expect, test } from "vitest";
import { rubleAxisTick } from "./rubleAxis";

test("ruble chart ticks retain zero, negative and compact large values", () => {
  expect(rubleAxisTick(0)).toBe("0 ₽");
  expect(rubleAxisTick(0.25)).toBe("0,25 ₽");
  expect(rubleAxisTick(-1500)).toContain("-1,5");
  expect(rubleAxisTick(-1500)).toContain("тыс.");
  expect(rubleAxisTick(1250000)).toContain("1,3");
  expect(rubleAxisTick(1250000)).toContain("млн");
  expect(rubleAxisTick(Infinity)).toBe("");
});
