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
