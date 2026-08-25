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

import type { StatementLink } from "../api/types";

/** Owner-created rows only. Imported/provider/statement provenance stays read-only. */
export function isManuallyEditableInvestmentFlow(
  source: string,
  statementLink?: StatementLink | null,
): boolean {
  return source === "manual" && statementLink == null;
}

export function statementCorrectionKind(
  statementLink?: StatementLink | null,
): "retract_import" | "unlink_statement" | null {
  if (statementLink == null || statementLink.status !== "active") {
    return null;
  }
  if (statementLink.link_mode === "statement_created") {
    return "retract_import";
  }
  if (statementLink.link_mode === "linked_existing") {
    return "unlink_statement";
  }
  return null;
}
