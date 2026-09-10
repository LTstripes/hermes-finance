# ASTRA follow-up false-exact review — 2026-09-10

> Reviewer-only audit. No production source, migration, existing test, PR,
> merge, tag, release, or owner/runtime state was changed. Verdict: **ACCEPT**
> within the bounded scope below.

## Scope and baseline

- Repository: `LTstripes/hermes-finance`
- Baseline under review: `354328055f97ce3bb7b055f8c0a5cbfa6cc5d315`
  (`fix(performance): invalidate observed TWRR boundary on material flow
  mutation (C2)`), on branch
  `audit/astra-performance-false-exact-followup-20260910` (this report only).
- Prior audit:
  `docs/audits/ASTRA_PERFORMANCE_FALSE_EXACT_CLOSURE_POST_HARDENING_2026-09-09.md`
  (BLOCK with confirmed HIGH C1 — reverse-date transfer transit — and HIGH
  C2 — stale observed TWRR boundary after flow correction).
- This review covers only the hypotheses left OPEN in that report, without
  re-proving the already closed F1/F2/F3/C1/C2:
  1. stale `ExternalTransferReconciliationEvidence` after material mutation
     of transfer legs (amount/date/currency/scope/link identity);
  2. direct payout / legacy withdrawal economic-event identity
     (double or erroneous identity);
  3. remaining unchecked interaction paths F1/F2/F3/C1/C2.
- Stop rule applied: stop after 2 confirmed HIGH, else ACCEPT if no new
  false-exact path is found in this bounded scope. No HIGH was confirmed.

## Method and boundary

Static reasoning was primary, over the availability assembly
(`portfolio_xirr` / `portfolio_twrr` via `performance_availability_for_interval`)
and the mutation services (`external_flows`, `transfer_reconciliation`,
`valuation_boundaries`, `cash_boundary_coverage`). No concrete suspected
false-exact path emerged, so no synthetic reproducer was written — per the
task rule, synthetic reproducers are reserved for concrete suspected paths.
Existing regression lanes were re-run on the exact baseline as the checkpoint
(see Checks). Synthetic fixtures, if any were needed, would have reused the
isolated R08 fixtures with no owner/runtime data, credentials, provider
calls, or production database access.

## H1 — transfer reconciliation evidence staleness: no false-exact path

`_transfer_reconciliation_complete`
(`services/performance_availability.py:1112-1146`) recomputes exclusively
from the **current** persisted leg state at every availability read; the
evidence row stores only `transfer_link_id` plus kind/amount/currency and
never snapshots leg identity. Walked mutation cases:

- amount change either direction (source up, destination up/down):
  `expected_difference` recomputes; a mismatch against the stored evidence
  sum yields `TRANSFER_RECONCILIATION_INCOMPLETE` (fail-closed). Converging
  to `difference == 0` returns complete with the stale row ignored —
  arithmetically identical to deleting it (harmless, not false-exact).
- currency change: same→cross-currency requires an `fx_conversion_spread`
  item, so a stale fee/commission item stops counting (fail-closed);
  cross→same-currency re-checks item currency against the current source
  currency; an FX-kind item can only satisfy a same-currency gap when its
  currency and amount tie out exactly (same verdict as a proper fee item).
- date change: reconciliation completeness never depended on dates; transit
  intersection is recomputed from current leg dates, including the C1
  reverse-chronology interval (fail-closed).
- scope change: current `scope_membership` is re-read both by the transit
  cross-check (`:1217-1239`) and by `classify_external_flow`; a leg that
  stops being `INTERNAL_TRANSFER` is either blocked via the membership /
  coverage gates or re-enters the external-flow path already guarded by
  F3 (cash invalidation) and C2 (boundary deletion).
- link change / leg deletion while evidence exists: blocked by
  `_require_no_transfer_reconciliation_evidence` in `stage_update_external_flow`
  and `delete_external_flow` (explicit-delete-first contract).
- evidence itself has no update API (create/delete only, both requiring
  editable legs); deleting it recomputes to incomplete wherever a gap
  remains (fail-closed).

Residual note (not a finding): stale rows linger where they are ignored
(e.g. equal legs). Availability-correct; cosmetic only.

## H2 — direct payout / legacy withdrawal identity: no false-exact path

- Return math never consumes income rows. XIRR builds cash flows only from
  `result.external_flows.flows` plus opening/closing valuations
  (`services/portfolio_xirr.py:82-119`); TWRR boundaries come only from
  classified explicit-flow evidence (`_boundaries_from_availability`).
  Calendar/provider rows are explicitly never converted into flows
  (`_calendar_payout_reason_codes` docstring). There is no path that books
  the same economic event twice into arithmetic.
- `_legacy_flow_ids` (`:466-502`) and `_direct_payout_reason_codes`
  (`:515-565`) recompute from current DB state at read time, keyed by
  (account, date, currency) with exact net-amount equality. Any material
  mutation of the corroborating external withdrawal (amount/date/currency/
  account/scope) breaks the 1:1 corroboration and yields
  `EXTERNAL_FLOWS_INCOMPLETE` (fail-closed), layered under F3/C2.
- Legacy `deposit` rows are unconditionally legacy (fail-closed direction).
- Shared-corroboration edge (two identical same-key withdrawals, one income
  row): both pass the corroboration check, but each withdrawal remains a
  distinct explicit owner boundary consumed once; corroboration gates payout
  provenance, it does not authorize withdrawals, and the second flow still
  had to pass F3 cash attestation. Owner-duplicate data, not a system
  inference — no false-exact availability created by the system.

## H3 — F1/F2/F3/C1/C2 interactions: no new false-exact path

- TWRR boundary targets admit only `EXTERNAL_CONTRIBUTION` /
  `EXTERNAL_WITHDRAWAL` classifications (`_external_flow_boundary_targets`,
  `:854-862`). Transfer legs (`INTERNAL_TRANSFER`) can never be targets;
  `UNRESOLVED` / `NOT_AUTHORITATIVE` flows add blocking reasons in
  `_external_flow_coverage` instead.
- Group date drift (member `event_date` mutated away from
  `boundary_date`): closed by C2, which deletes group-linked points on any
  member material mutation; without points the target resolves to
  `VALUATION_BOUNDARY_MISSING`. Standalone date drift was already gated by
  the observed-date/target-date mismatch (`VALUATION_BOUNDARY_ORDER_UNKNOWN`,
  TWRR-only by accepted contract).
- Reverse-date legs with `UNKNOWN` membership skip the transit gate via the
  non-`INTERNAL_TRANSFER` `continue` — but the same legs then carry
  `SCOPE_MEMBERSHIP_HISTORY_MISSING` through `_external_flow_coverage` into
  both metric reason sets, so both metrics stay `NOT_COMPUTABLE`. The skip
  is safe exactly because interval coverage blocks non-authoritative flows.
- `create_external_transfer_link` mutates `flow.transfer_link_id` directly,
  bypassing the F3/C2 mutation hooks. Traced: the reclassified flow drops
  out of both maths entirely (`INTERNAL_TRANSFER` is skipped in
  `_cash_flows_from_availability`; it cannot be a TWRR target), while the
  transit gate keeps evaluating current leg dates. Stale C2 points, if any,
  become unconsumed orphans. No exact metric consumes a stale combination.
  Single-leg (`UNRESOLVED`) links block via reasons. Closed-month legs
  block via `_require_editable_transfer_legs`.
- F1 (snapshot-clock in-kind population) shares no mutable state with C2
  (snapshots untouched) or C1 (transit date logic untouched); F1/F2
  targeted regressions remain green on this baseline.

## Checks actually run

- Existing regression lanes on the exact baseline, from `backend` with an
  external unique pytest basetemp
  (`--basetemp D:\Finance\pytest-followup-audit-20260910`):
  `test_r08_h2a_scope_membership_changed.py`,
  `test_r08_h2b_cash_boundary.py` (includes F3/C2),
  `test_r08_h2c_transfer_transit.py` (includes C1),
  `test_r08_h2d_in_kind_coverage.py` (F1 area),
  `test_r08_h3_tax_direct_payout.py` (H3 area),
  `test_r08_01c_performance_availability.py` — **75 passed**.
- `git diff --check` — **PASS**.
- `uv run --locked python scripts/privacy_check.py` — **PASS**.

No full backend suite, CI, owner UAT, provider call, or private runtime probe
is claimed; none was needed for this static/bounded-scope review.

## Verdict

**ACCEPT** for baseline `354328055f97ce3bb7b055f8c0a5cbfa6cc5d315` within
this bounded scope: the three remaining OPEN hypothesis areas contain no
false-exact availability path. Transfer reconciliation, payout/legacy
corroboration, and the F1/F2/F3/C1/C2 cross-product all recompute from
current persisted state at read time and fail closed on mutation. No PR or
merge was created; this audit branch carries only this report.
