import { describe, expect, it } from "vitest";

import { comparedToLabel } from "./uiV2Copy";
import { moneyWholeDeltaText, moneyWholeText, percentText } from "./valueFormat";

const rub = (amount: string) => ({ amount, currency: "RUB" });
/** Formatters group digits with non-breaking spaces. */
const plain = (text: string) => text.replace(/ /g, " ");

describe("whole-ruble overview money", () => {
  it("rounds kopecks HALF_UP away from zero without binary floats", () => {
    expect(plain(moneyWholeText(rub("1234567.49")))).toBe("1 234 567 ₽");
    expect(plain(moneyWholeText(rub("1234567.50")))).toBe("1 234 568 ₽");
    expect(plain(moneyWholeText(rub("-499567.50")))).toBe("−499 568 ₽");
    expect(plain(moneyWholeText(rub("9876543210123.45")))).toBe("9 876 543 210 123 ₽");
    expect(plain(moneyWholeText(rub("-0.40")))).toBe("−0,40 ₽");
  });

  it("keeps unknown distinct from zero", () => {
    expect(plain(moneyWholeText(null))).toBe("Недоступно");
    expect(plain(moneyWholeText(undefined, "—"))).toBe("—");
  });

  it("signs a delta and leaves zero unsigned", () => {
    expect(plain(moneyWholeDeltaText(rub("28900.00")))).toBe("+28 900 ₽");
    expect(plain(moneyWholeDeltaText(rub("-203478.20")))).toBe("−203 478 ₽");
    expect(plain(moneyWholeDeltaText(rub("0.30")))).toBe("+0,30 ₽");
  });
});

describe("percent display rounding", () => {
  it("rounds a backend percentage string HALF_UP", () => {
    expect(percentText("-3.13", 1, { signed: true })).toBe("−3,1%");
    expect(percentText("0.79", 1, { signed: true })).toBe("+0,8%");
    expect(percentText("92.50", 0)).toBe("93%");
    expect(percentText("0.04", 1, { signed: true })).toBe("0,0%");
    expect(percentText("0.05", 1)).toBe("0,1%");
    expect(percentText(null)).toBe("—");
  });
});

describe("comparison base label", () => {
  it("uses the dative month and adds the year only across years", () => {
    expect(comparedToLabel({ year: 2031, month: 9 }, { year: 2031 })).toBe("к сентябрю");
    expect(comparedToLabel({ year: 2030, month: 12 }, { year: 2031 })).toBe("к декабрю 2030");
  });
});
