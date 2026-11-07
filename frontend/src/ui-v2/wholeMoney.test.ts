import { describe, expect, it } from "vitest";

import { wholeMoneyDeltaText, wholeMoneyText } from "./wholeMoney";

const rub = (amount: string) => ({ amount, currency: "RUB" });
const plain = (text: string) => text.replaceAll("\u00a0", " ");

describe("whole-ruble overview money", () => {
  it("rounds exact kopecks HALF_UP away from zero", () => {
    expect(plain(wholeMoneyText(rub("1234.49")))).toBe("1 234 ₽");
    expect(plain(wholeMoneyText(rub("1234.50")))).toBe("1 235 ₽");
    expect(plain(wholeMoneyText(rub("-1.50")))).toBe("−2 ₽");
    expect(plain(wholeMoneyText(rub("9876543210123.45")))).toBe("9 876 543 210 123 ₽");
    expect(plain(wholeMoneyDeltaText(rub("42600.00")))).toBe("+42 600 ₽");
    expect(plain(wholeMoneyDeltaText(rub("-10000.50")))).toBe("−10 001 ₽");
  });

  it("keeps a genuine zero and never turns a small non-zero amount into zero", () => {
    expect(plain(wholeMoneyText(rub("0.00")))).toBe("0 ₽");
    expect(plain(wholeMoneyText(rub("0.40")))).toBe("0,40 ₽");
    expect(plain(wholeMoneyDeltaText(rub("-0.40")))).toBe("−0,40 ₽");
  });

  it("keeps an unknown amount unknown", () => {
    expect(wholeMoneyText(null)).toBe("Недоступно");
    expect(wholeMoneyText(rub("not-a-number"), "—")).toBe("—");
  });
});
