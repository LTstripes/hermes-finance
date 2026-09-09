# ASTRA post-hardening false-exact closure audit — 2026-09-09

> Reviewer-only audit. This report and its audit evidence are the only intended
> changes on the audit branch; production code is out of scope.

## Scope and exact candidate

- Repository: `LTstripes/hermes-finance`
- Workstream: `integration/performance-v1`
- Candidate under review: `d89830b11af32c2d10a1673e36a6a85d608ed7f2`
  (`fix(performance): invalidate cash attestation on flow mutation`)
- Candidate ancestry: `ee35db2b58875914107d304d3537fdfb3661c67f`
  (`origin/integration/performance-v1` after the local remote refresh), then
  F1 `2ef4ce1`, F1 regression test `cb78f03`, F2 `cc76824`, and F3 `d89830b`.
- Audit branch: `audit/astra-performance-false-exact-post-hardening-20260909`
- Baseline contract: `docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`
- Prior open-hypothesis register:
  `docs/audits/ASTRA_PERFORMANCE_FALSE_EXACT_CLOSURE_2026-09-08.md`

The remote integration ref currently resolves to the F1/F2/H3 staging merge
`ee35db2`; the F3 candidate above is reviewed as the current post-hardening
integrated candidate and is not merged or rewritten by this audit.

## Review boundary

The review covers only concrete availability paths for XIRR/TWRR: reverse-date
transfers; transfer mutation and reconciliation evidence identity; async
transfer plus membership transitions; direct payout and legacy withdrawal
economic-event identity; correction/replacement of observed TWRR boundary
evidence; coverage overlap/endpoints; and F1/F2/F3 interactions.

Static reasoning is primary. Synthetic reproducer tests are added only for
suspicious paths and use isolated temporary databases with synthetic values.
No private runtime, owner data, credentials, or production code is used.

## Checkpoints

| Checkpoint | Commit | Contents |
|---|---|---|
| Scope captured | pending | This report, exact candidate and baseline provenance |

## Findings

Pending targeted static review and reproducer execution.

## Checks

Pending. Commands and exact results will be recorded here after execution.

## Open hypotheses not yet dispositioned

Pending. The audit stops after two confirmed HIGH/BLOCKER findings, as required
by the review request; remaining hypotheses will be explicitly marked as
unconfirmed or out of the stopped scope.

## Verdict

Pending.
