import { describe, expect, it } from "vitest";

import { goalForecastSupportLabel } from "./goals";

describe("goalForecastSupportLabel", () => {
  it("describes passive-income progress as closed-history actuals", () => {
    expect(goalForecastSupportLabel("passive_income", "monthly_net_passive_income")).toBe(
      "Прогресс считается по фактическому среднему чистому пассивному доходу закрытых месяцев.",
    );
  });
});
