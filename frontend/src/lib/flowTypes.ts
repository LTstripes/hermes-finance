/** Mirrors backend InvestmentCashFlowType.counts_as_passive_income (classification, not money math). */
const PASSIVE_ACTUAL_TYPES = new Set(["interest", "coupon", "dividend", "other"]);

export function isPassiveInvestmentFlowType(flowType: string): boolean {
  return PASSIVE_ACTUAL_TYPES.has(flowType);
}

export function isRedemptionFlowType(flowType: string): boolean {
  return flowType === "redemption";
}

/** Expected flows: everything except redemption counts as passive (domain property). */
export function isPassiveExpectedFlowType(flowType: string): boolean {
  return flowType !== "redemption";
}

/** Owner-created rows only. Imported/provider/statement provenance stays read-only. */
export function isManuallyEditableInvestmentFlow(source: string): boolean {
  return source === "manual";
}
