import { afterEach, describe, expect, it, vi } from "vitest";
import { isAtLeast, isWithinRange, normalizeDecimalInput, triggerDownload } from "./scenarioLab";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("scenario decimal input", () => {
  it("normalizes comma input and preserves decimal strings without rounding", () => {
    expect(normalizeDecimalInput(" 10,500000000000000001 ", false)).toBe("10.500000000000000001");
    expect(normalizeDecimalInput("-10,5", true)).toBe("-10.5");
    expect(normalizeDecimalInput("-10", false)).toBeNull();
    for (const raw of ["", "-", ".", "-.", "NaN", "1e2", "Infinity"]) {
      expect(normalizeDecimalInput(raw, true)).toBeNull();
    }
  });

  it("keeps inclusive bounds, zero and signed FX limits", () => {
    expect(isWithinRange("0", 100)).toBe(true);
    expect(isWithinRange("100", 100)).toBe(true);
    expect(isWithinRange("100.01", 100)).toBe(false);
    expect(isWithinRange("-1", 100)).toBe(false);
    expect(isWithinRange(null, 100)).toBe(false);
    expect(isAtLeast("-100", -100)).toBe(true);
    expect(isAtLeast("-100.01", -100)).toBe(false);
    expect(isAtLeast("150", -100)).toBe(true);
    expect(isAtLeast(null, -100)).toBe(false);
  });
});

it("downloads the supplied blob and filename and releases the temporary URL", () => {
  const blob = new Blob(["{}"]);
  const createObjectURL = vi.fn(() => "blob:scenario");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL, revokeObjectURL }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    expect(this).toHaveAttribute("download", "scenario.json");
    expect(this).toHaveAttribute("href", "blob:scenario");
    expect(this).toBeInTheDocument();
  });
  triggerDownload(blob, "scenario.json");
  expect(createObjectURL).toHaveBeenCalledWith(blob);
  expect(click).toHaveBeenCalledOnce();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:scenario");
  expect(document.querySelector("a[download]")).toBeNull();
});
