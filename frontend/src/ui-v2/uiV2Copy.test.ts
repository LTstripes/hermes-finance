import { describe, expect, it } from "vitest";

import { eventLabel, sourceLabel } from "./uiV2Copy";

describe("uiV2Copy", () => {
  it("keeps known event and source labels owner-facing", () => {
    expect(eventLabel("redemption_principal")).toBe("Возврат основной суммы");
    expect(sourceLabel("provider")).toBe("внешний источник");
  });

  it("does not misclassify unknown event or source kinds", () => {
    expect(eventLabel("future_component")).toBe("Тип события не распознан");
    expect(sourceLabel("future_source")).toBe("Источник не распознан");
  });
});
