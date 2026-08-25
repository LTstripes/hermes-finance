import { describe, expect, it } from "vitest";

import {
  isManuallyEditableInvestmentFlow,
  isPassiveExpectedFlowType,
  isPassiveInvestmentFlowType,
  isRedemptionFlowType,
  statementCorrectionKind,
} from "./flowTypes";

describe("flowTypes classification", () => {
  it("marks coupon/dividend/interest as passive actual income", () => {
    expect(isPassiveInvestmentFlowType("coupon")).toBe(true);
    expect(isPassiveInvestmentFlowType("dividend")).toBe(true);
    expect(isPassiveInvestmentFlowType("interest")).toBe(true);
    expect(isPassiveInvestmentFlowType("redemption")).toBe(false);
    expect(isPassiveInvestmentFlowType("deposit")).toBe(false);
  });

  it("flags redemption separately", () => {
    expect(isRedemptionFlowType("redemption")).toBe(true);
    expect(isRedemptionFlowType("coupon")).toBe(false);
  });

  it("expected: non-redemption counts as passive", () => {
    expect(isPassiveExpectedFlowType("coupon")).toBe(true);
    expect(isPassiveExpectedFlowType("redemption")).toBe(false);
  });

  it("protects imported and provider investment flows from manual edit", () => {
    expect(isManuallyEditableInvestmentFlow("manual")).toBe(true);
    expect(isManuallyEditableInvestmentFlow("alfa_depository_income_report")).toBe(false);
    expect(isManuallyEditableInvestmentFlow("excel_migration")).toBe(false);
    expect(isManuallyEditableInvestmentFlow("t_invest")).toBe(false);
  });

  it("does not treat a linked-existing manual row as editable until unlinked", () => {
    expect(
      isManuallyEditableInvestmentFlow("manual", {
        applied_statement_event_id: 9,
        link_mode: "linked_existing",
        status: "active",
      }),
    ).toBe(false);
    expect(
      statementCorrectionKind({
        applied_statement_event_id: 9,
        link_mode: "linked_existing",
        status: "active",
      }),
    ).toBe("unlink_statement");
    expect(
      statementCorrectionKind({
        applied_statement_event_id: 8,
        link_mode: "statement_created",
        status: "active",
      }),
    ).toBe("retract_import");
    expect(statementCorrectionKind(null)).toBeNull();
  });
});
