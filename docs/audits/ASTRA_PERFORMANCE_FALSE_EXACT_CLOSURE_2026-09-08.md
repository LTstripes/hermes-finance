# Performance false-exact closure audit — 2026-09-08

Status: IN PROGRESS. Verdict: pending.

Exact audited staging SHA: `ee35db2b58875914107d304d3537fdfb3661c67f`.
Repository: LTstripes/hermes-finance. `main` is the sole canonical release/source of truth; integration/performance-v1 is staging only.

## Normative sources
Read: AGENTS.md at the exact audited SHA.
Pending: docs/CONSOLIDATION_2026-09-06.md; docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md; docs/MASTER_SPEC.md; docs/VERIFICATION_POLICY.md; relevant accepted ADRs; issues #315, #320, #321, #316, #317, #318.

## Scope and method
Reviewer-only adversarial composition audit of H2a/H2b/H2c/H2d/H3 exact XIRR/TWRR prerequisites. Static inspection first, narrow synthetic reproduction where warranted. No production edits, PR, merge, private/runtime database access or live providers. Audit documentation and clearly marked regression evidence only.

## Checklist / open hypotheses
- Stable membership, cash coverage and start/end transitions.
- Transfer transit, required valuations and membership transitions.
- Transfer reconciliation evidence ownership, overlapping transfers and fee/tax reuse.
- Cash COMPLETE with in-kind UNKNOWN; movements at valuation boundaries.
- Direct payout, withholding, owner flows and economic-income double counting.
- Coverage interval endpoints and correction/replacement invalidation.
- Domain/service/API availability and reason propagation.

## Findings
None confirmed yet. This is not acceptance.

## Audit slices
Initial checkpoint: exact commit checked out in isolated audit worktree; AGENTS.md read. Remaining sources and all production hypotheses pending.

## Rejected hypotheses
None yet.

## Verification / next probes
No tests run. Read required sources, then trace persisted prerequisite facts to metric availability.

### Slice 1 checkpoint — normative and gate assembly
Read required reconciliation/consolidation documents, AGENTS, verification policy, relevant MASTER_SPEC sections (reporting month versus snapshot date, financial persistence), ADR 0003 income inclusion and ADR 0007 historical snapshot semantics; inspected ADR inventory/provenance references. GitHub issue bodies #315/#320/#321/#316/#317/#318 and available integration comments read. No formula re-review.

Static paths inspected: services/performance_availability.py (membership, cash-flow corroboration, transfer safety, metric assembly), domain/performance_availability.py, services/cash_boundary_coverage.py, services/in_kind_boundary_coverage.py, services/external_flows.py, services/transfer_reconciliation.py, services/valuation_points.py, portfolio_xirr.py and portfolio_twrr.py; H2c/H3 and R08-01C fixtures/tests.

Rejected at static level: later shared gates overwrite earlier unavailable (reason sets are unioned); cash COMPLETE substitutes for in-kind UNKNOWN (independent reason union); a known movement on an other/no-position account is filtered by coverage population (separate historically-in-scope movement query); transition at end is omitted (closed interval comparison); standalone same-day tax reconciles a withdrawal (H3 explicitly refuses it).

Open, not findings: (1) position history for in-kind population uses quote price_date rather than reporting/snapshot history, while valuation consumes those same rows without that predicate; (2) re-open/edit/delete can leave prior completeness attestation untouched; (3) same-day or reversed transfer legs bypass the strictly increasing transit-date check; (4) H3 legacy/income corroboration has no common evidence-consumption identity. Next: minimal synthetic probes, prioritizing (1) and (3). No tests run yet.

## Confirmed finding F1 — HIGH / reproduced
Scope: whole-portfolio XIRR and exact TWRR; account availability also uses the same gate. Confidence: confirmed synthetic service/API-adapter reproduction.

`services/in_kind_boundary_coverage.py::_required_account_ids` lines 434-470 (notably the PositionSnapshot.price_date <= end_date filter) uses the quote clock to establish position-history existence. `services/valuation_points.py::valuation_point_for_month` lines 259-293 consumes those same positions by reporting_month_id without that price-date predicate.

Minimal scenario: stable in-scope other account, January/February persisted positions plus cash/deposits, closed boundary snapshots worth 3,400 RUB each, cash coverage COMPLETE, in-kind explicitly UNKNOWN. Position quote dates are March 1 (later than February 28 requested end), accepted through update_position_snapshot. There is no affirmative in-kind evidence. The instrument-bearing account disappears from required_ids; UNKNOWN is never read.

Expected: NOT_COMPUTABLE with not_computable_in_kind_boundary_coverage_unknown (or an independent valuation evidence blocker). Actual: both metric services and API response adapters return available / exact / value 0 / empty reasons. An unrecorded in-kind crossing cannot be excluded from these persisted facts. Quote date is not evidence that the account held no instruments during its reporting snapshots.

Existing generic-position test uses ordinary quote dates and does not exercise disagreement between reporting/snapshot and quote clocks. Minimal reproducer: docs/audits/evidence/test_false_exact_closure.py::test_audit_quote_clock_hides_known_positions_from_in_kind_gate. `1 passed` asserts current defective behavior, not acceptance. Production remains unchanged.

Fix direction only: establish instrument-capable history from the canonical reporting/snapshot existence semantics; do not let a quote timestamp suppress already-consumed position evidence. Preserve UNKNOWN and optionally independently reject inadmissible valuation clocks. No fix implemented.

## Confirmed finding F2 — HIGH / reproduced
Scope: whole-portfolio XIRR and exact TWRR. Confidence: confirmed synthetic service reproduction; no assumptions about solver formulas.

Production: `services/performance_availability.py::_portfolio_transfer_safety` lines 1193-1199, 1253-1257 checks transit only for source.event_date < destination.event_date. Same-date linked legs are internal but produce no unsafe valuation dates. `services/valuation_points.py::_scope_membership_coverage` lines 195-210 records date-only boundary-order ambiguity; availability removes the TWRR-only reason from XIRR and TWRR subsequently inherits that filtered set. Internal transfers create no external-flow split to restore it.

Scenario: stable in-scope accounts A/B, positions total 2,000 RUB, A opening cash 1,000 RUB, both linked 1,000 RUB legs dated February 28. Closing cash observations are zero, consistent with observation after departure and before arrival on that date. Opening/closing totals are 3,000/2,000 RUB. All cash/in-kind coverage COMPLETE and transfer amounts reconcile. Missing: intraday ordering/continuity provenance proving transferred capital was in the aggregate closing valuation.

Expected: NOT_COMPUTABLE for the required ambiguous/unvalued transfer boundary. H1-A forbids assuming same-day order without explicit provenance. Actual: both production metric services AVAILABLE; TWRR reports a negative exact return from omitted transferred capital. Date equality does not prove instantaneous settlement or synchronized account observations.

Existing H2c tests cover strictly increasing leg dates, including interval endpoints, but not equal leg dates at a required valuation with missing order/continuity evidence. Reproducer: `test_audit_same_day_internal_transfer_boundary_has_no_order_proof` in the audit evidence file. Fix direction: keep same-day internal transfer valuation continuity/order as an independent financial prerequisite, so XIRR's external-flow date-order exemption cannot erase it. Do not synthesize transit valuation. No fix implemented.

## Confirmed finding F3 — HIGH / reproduced lifecycle, high-confidence proof failure
Scope: whole-portfolio XIRR and exact TWRR. Confidence: reproducible behavior; the financial defect applies to correction/replacement of a real event, not to an intentional assertion that an erroneous event never happened.

Production: `services/external_flows.py::delete_external_flow` lines 608-620 deletes a canonical flow after the editable-month guard, without invalidating the cash completeness assertion. `services/reporting_months.py::reopen_reporting_month` lines 202-208 and `close_reporting_month` lines 194-200 only toggle status. `services/cash_boundary_coverage.py::_account_is_covered` lines 302-329 accepts the old COMPLETE assertion solely from interval/state/provenance, with no relation to the represented event set or its revision.

Scenario: opening 3,400 RUB; actual contribution 100 RUB on February 15; closing 3,500 RUB. Persist canonical contribution then confirm COMPLETE coverage and close. XIRR is available at zero. Reopen February and delete the old contribution while correcting/replacing evidence; no replacement or renewed owner attestation is supplied. Close February. Old coverage remains COMPLETE. No legacy deposit row exists to rescue detection.

Expected: NOT_COMPUTABLE / not_computable_external_flows_incomplete until replacement is represented and completeness is reaffirmed. Actual: empty flow set, COMPLETE coverage, both exact metric services available with positive return. Closing a month is not an attestation that a previously confirmed crossing disappeared economically. The system retains no persisted fact establishing that the changed event set is complete.

Existing H2b tests guard editing/revoking the coverage row itself; they do not compose event deletion/replacement with an existing complete interval. Reproducer: `test_audit_deleted_flow_leaves_prior_cash_attestation_complete`. Fix direction: invalidate affected completeness or bind confirmation to evidence revision/set on financially material event mutation; require explicit reaffirmation when replacement is incomplete. No fix implemented.

### Stop checkpoint
Three HIGH false-exact paths recorded; stop broad search per owner instruction. Latest audit evidence run: 3 passed (assertions deliberately describe defects). Prior run: 2 passed / 1 fixture TypeError (missing kind argument); corrected audit fixture only and reran. No production modifications. Remaining work: tighten exact references, negative controls, narrow existing regression checks, final report/read-back. No new hypotheses will be investigated.
