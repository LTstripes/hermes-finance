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
