import type { ClassReturns } from "../api/types";

/** Synthetic API projection only; not a return calculator. */
export function classReturnsFixture(assetClass: string, start: string, end: string): ClassReturns {
  const unsupported = assetClass === "deposit";
  const reasons = unsupported ? ["unsupported_class"] : [];
  const metric = (value: string) => ({
    availability: unsupported ? ("not_computable" as const) : ("available" as const),
    quality: unsupported ? ("unavailable" as const) : ("exact" as const),
    value: unsupported ? null : value,
    value_unit: "percentage_points" as const,
    reason_codes: reasons,
    reason_source: unsupported ? ("evidence" as const) : null,
  });
  return {
    asset_class: assetClass,
    requested_period: { start_date: start, end_date: end },
    actual_covered_period: {
      start_date: unsupported ? null : start,
      end_date: unsupported ? null : end,
    },
    performance_currency: "RUB",
    valuation_basis: "persisted_rub_market_value_kopecks",
    historical_account_ids: [],
    coverage_state: unsupported ? "unknown" : "complete",
    coverage_provenance: unsupported
      ? []
      : [
          {
            id: 1,
            revision: 2,
            asset_class: assetClass as "stock" | "bond" | "gold",
            covered_from: start,
            covered_to: end,
            coverage_state: "complete",
            provenance_kind: "owner_attestation",
            provenance_reference: "synthetic-confirmation",
            opening_inventory_complete: true,
            closing_inventory_complete: true,
          },
        ],
    eligibility_status: unsupported ? "unsupported" : "eligible",
    evidence_reason_codes: reasons,
    xirr: { ...metric("10.125"), annualized: true },
    twrr: { ...metric("5.75"), annualized: false },
  };
}
