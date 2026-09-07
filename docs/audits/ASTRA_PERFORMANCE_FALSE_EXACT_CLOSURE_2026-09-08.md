# Performance false-exact closure audit — 2026-09-08

Status: COMPLETE within the three-finding stop condition. Verdict: **BLOCK**.

Exact audited staging SHA: `ee35db2b58875914107d304d3537fdfb3661c67f`.
Repository: LTstripes/hermes-finance. `main` is the sole canonical release/source of truth; integration/performance-v1 is staging only.

## Normative sources
Read: AGENTS.md; docs/CONSOLIDATION_2026-09-06.md; docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md; relevant MASTER_SPEC sections on clocks, financial persistence and historical semantics; docs/VERIFICATION_POLICY.md; ADR 0003 (income inclusion), ADR 0007 (historical reporting snapshots), ADR 0016 sections 7-9 (current baseline versus historical provenance); issue bodies #315, #320, #321, #316, #317, #318. GitHub integration/review comments were also consulted. Repository sources refer to the audited SHA, not current main.

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
| ID | Severity / confidence | False-exact intersection |
|---|---|---|
| F1 | HIGH / reproduced | Position valuation consumes rows that the in-kind coverage population excludes by quote date; persisted UNKNOWN disappears. |
| F2 | HIGH / reproduced | Same-day internal transfer creates no transit date; valuation-order reason is dropped before TWRR assembly. |
| F3 | HIGH / reproduced lifecycle; high-confidence proof failure | Canonical flow deletion during replacement leaves prior COMPLETE attestation valid without renewed evidence. |

Detailed scenarios, missing/present evidence, locations, expected/actual availability, test gaps and fix directions follow below. No production fix is included.

## Audit slices
Initial checkpoint: exact commit checked out in isolated audit worktree; AGENTS.md read. Remaining sources and all production hypotheses pending.

## Rejected hypotheses
The initial no-overwrite hypothesis was narrowed by F2: shared financial reasons are unioned, but the deliberate boundary-order discard is unsafe for a same-day internal transfer. Other rejected hypotheses and limits are listed in the final coverage matrix.

## Verification / next probes
Initial checkpoint had no tests; final executed checks and bounded next task are recorded at the end.

### Slice 1 checkpoint — normative and gate assembly
Read required reconciliation/consolidation documents, AGENTS, verification policy, relevant MASTER_SPEC sections (reporting month versus snapshot date, financial persistence), ADR 0003 income inclusion and ADR 0007 historical snapshot semantics; inspected ADR inventory/provenance references. GitHub issue bodies #315/#320/#321/#316/#317/#318 and available integration comments read. No formula re-review.

Static paths inspected: services/performance_availability.py (membership, cash-flow corroboration, transfer safety, metric assembly), domain/performance_availability.py, services/cash_boundary_coverage.py, services/in_kind_boundary_coverage.py, services/external_flows.py, services/transfer_reconciliation.py, services/valuation_points.py, portfolio_xirr.py and portfolio_twrr.py; H2c/H3 and R08-01C fixtures/tests.

Rejected at static level: later shared gates overwrite earlier unavailable (reason sets are unioned); cash COMPLETE substitutes for in-kind UNKNOWN (independent reason union); a known movement on an other/no-position account is filtered by coverage population (separate historically-in-scope movement query); transition at end is omitted (closed interval comparison); standalone same-day tax reconciles a withdrawal (H3 explicitly refuses it).

Open, not findings: (1) position history for in-kind population uses quote price_date rather than reporting/snapshot history, while valuation consumes those same rows without that predicate; (2) re-open/edit/delete can leave prior completeness attestation untouched; (3) same-day or reversed transfer legs bypass the strictly increasing transit-date check; (4) H3 legacy/income corroboration has no common evidence-consumption identity. Next: minimal synthetic probes, prioritizing (1) and (3). No tests run yet.

## Confirmed finding F1 — HIGH / reproduced
Scope: whole-portfolio XIRR and exact TWRR; account availability also uses the same gate. Confidence: confirmed synthetic service/API-adapter reproduction.

All production paths below are relative to `backend/src/hermes_finance/` at the audited SHA. `services/in_kind_boundary_coverage.py::_required_account_ids` lines 428-465 (predicate at 443) uses the quote clock to establish position-history existence. `services/valuation_points.py::valuation_point_for_month` lines 259-293 consumes those same positions by reporting_month_id without that price-date predicate.

Minimal scenario: stable in-scope other account, January/February persisted positions plus cash/deposits, closed boundary snapshots worth 3,400 RUB each, cash coverage COMPLETE, in-kind explicitly UNKNOWN. Position quote dates are March 1 (later than February 28 requested end), accepted through update_position_snapshot. There is no affirmative in-kind evidence. The instrument-bearing account disappears from required_ids; UNKNOWN is never read.

Expected: NOT_COMPUTABLE with not_computable_in_kind_boundary_coverage_unknown (or an independent valuation evidence blocker). Actual: both metric services and API response adapters return available / exact / value 0 / empty reasons. An unrecorded in-kind crossing cannot be excluded from these persisted facts. Quote date is not evidence that the account held no instruments during its reporting snapshots.

Existing generic-position test uses ordinary quote dates and does not exercise disagreement between reporting/snapshot and quote clocks. Minimal reproducer: docs/audits/evidence/test_false_exact_closure.py::test_audit_quote_clock_hides_known_positions_from_in_kind_gate. `1 passed` asserts current defective behavior, not acceptance. Production remains unchanged.

Fix direction only: establish instrument-capable history from the canonical reporting/snapshot existence semantics; do not let a quote timestamp suppress already-consumed position evidence. Preserve UNKNOWN and optionally independently reject inadmissible valuation clocks. No fix implemented.

## Confirmed finding F2 — HIGH / reproduced
Scope: whole-portfolio XIRR and exact TWRR. Confidence: confirmed synthetic service reproduction; no assumptions about solver formulas.

Production: `services/performance_availability.py::_portfolio_transfer_safety` lines 1193-1199, 1253-1257 checks transit only for source.event_date < destination.event_date. Same-date linked legs are internal but produce no unsafe valuation dates. `services/valuation_points.py::_scope_membership_coverage` lines 195-210 records date-only boundary-order ambiguity; `performance_availability_for_interval` at line 1355 discards that reason from XIRR and at 1389 TWRR inherits the filtered set. `_external_flow_boundary_targets` at 845-863 excludes internal transfers, so no split restores the reason.

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

## Final coverage matrix and rejected hypotheses

| Intersection | Evidence actually checked | Outcome |
|---|---|---|
| Stable membership + cash coverage / transition at start or end | Static closed-interval comparisons and independent reason union; existing selected membership regressions | No bypass found in inspected path; no exhaustive transition/flow product generated. |
| Forward async transfer + required TWRR valuation | Static metric-specific required-date sets; existing unrelated TWRR boundary regression | Forward transit gate preserved; same-day variant is F2. |
| Overlapping transfers + reconciliation ownership | Transfer-id lookup and existing overlapping-transfer regression | One link's attached evidence does not automatically reconcile the other. No identity-alias mutation matrix run. |
| Standalone tax/commission + legacy withdrawal | H3 source path and existing unrelated same-day cost regression | Hypothesis rejected: unrelated cost cannot reconcile the withdrawal. |
| Cash COMPLETE + in-kind UNKNOWN | Independent reason sets and synthetic F1 control | Ordinary UNKNOWN blocks; population clock mismatch bypasses it (F1). |
| Explicit other-account in-kind movement + population filter | Static separate historically-in-scope movement query | Prior #317 defect not reopened: explicit movement detection is not limited to required_ids. |
| Coverage interval endpoints / correction | Inclusive coverage and membership comparisons; existing partial-interval and correction tests | Coverage-row revoke/update obeys reopen; represented-flow lifecycle is F3. |
| Domain/service/API propagation | Metric service entry guards, reason aggregation, production DTO adapters exercised by synthetic tests | F1/F2/F3 reach metric output; F2 specifically drops a reason already present on closing valuation. HTTP transport/frontend were not exercised. |
| Income + owner withdrawal / direct payout | Static H3 matching and XIRR/TWRR classified-flow consumers | Income rows are not separately fed to return math. Whether one canonical withdrawal can corroborate distinct economic events remains OPEN. |

The generic assertion that no late gate can remove an early blocker is **not** retained: F2 is the concrete exception. Missing membership does not become complete merely because cash required_ids is empty: membership reasons independently block the metric. Cash/in-kind COMPLETE defaults on explicit create are owner assertions, not automatic backfill; the defect is missing population/lifecycle validation, not merely the presence of a default argument.

## OPEN HYPOTHESES / untested areas

Stopped after three HIGH findings, per the requested limit; this is not an exhaustive proof of every evidence composition. Unresolved: reverse-date transfers; H3 shared economic-event identity across direct income and legacy withdrawal; transfer reconciliation amount/currency/date mutations and aliases; full async-transfer/membership-transition cross-product; all in-kind movement/start/end combinations; correction of observed TWRR boundary evidence; full coverage overlap/date.max matrix. No new scope was started after the stop checkpoint. No Scenario Lab, Monthly Close workflow or launcher audit, no provider calls, and no owner/runtime DB access.

## Executed checks

- Audit evidence: `python -m pytest ../docs/audits/evidence/test_false_exact_closure.py -q` with a unique external synthetic basetemp: **3 passed** in 4.54s on the final behavior assertions plus negative controls. Tests deliberately assert observed defects and must NOT be adopted unchanged as desired-behavior regressions.
- F1 negative control: changing only quote dates back into history restores the in-kind UNKNOWN block.
- F2 negative control: changing source leg to the previous day restores transfer-in-transit blocking. The defective same-day case explicitly verifies that the closing valuation contains the boundary-order reason while metrics are available.
- F3 negative control: explicit cash coverage revocation restores the external-flows-incomplete block; no automatic revocation occurred during deletion.
- Selected existing H2a/H2b/H2c/H2d/H3 tests, `-k "transition or partial_interval or correction or unrelated_same_day or overlapping or generic_account_with_position or unrelated_twrr_boundary"`: **10 passed, 43 deselected** in 7.51s.
- Setup: offline dependency sync could not find packages in an empty task-local cache; authorized online locked dependency sync then succeeded. This was package setup, not a live financial provider call.
- Earlier audit-test run had one fixture TypeError (missing required kind); fixed only the audit fixture. Subsequent runs passed. No full suite, CI, migration or owner UAT claims.

## Three permanent regressions to add

1. Generic in-scope account with persisted interval positions, quote dates outside requested interval, and UNKNOWN in-kind coverage: both metrics must be unavailable (F1).
2. Same-day internal transfer at required opening/closing or observed split valuation without ordering/continuity evidence: affected metrics must stay unavailable and retain a stable reason (F2).
3. Complete cash history followed by reopen + canonical flow delete/replacement + close without renewed completeness: metrics must stay unavailable until replacement/confirmation is complete (F3).

## Verdict and next bounded task

**BLOCK** for exact staging `ee35db2b58875914107d304d3537fdfb3661c67f`. Concrete false-exact paths exist even though the ordinary gates and their isolated regression tests pass. This is a staging audit only; canonical main remains the sole release/source of truth.

Next recommended bounded task (NOT STARTED): fix only F1's in-kind required-account history clock and add its fail-closed regression on a fresh implementation branch, with independent review. Track F2 and F3 as separate closure blockers; F3 needs an explicit narrow mutation/re-attestation policy. No exactness acceptance until all three are resolved and independently rechecked.

Delivery branch: `audit/astra-performance-false-exact-20260908`. First commit `58f251b` is skeleton only; progress checkpoints `3035eef`, `c109cfe`, `dfa6f5c`, `75fe3d7` were committed and pushed. Changed scope: this report and its synthetic evidence file only. No PR/merge/release or production changes.

Final local hygiene: `git diff --check` PASS; `scripts/privacy_check.py` PASS (814 tracked files). Diff from audited staging contains exactly two audit files; production source and existing tests unchanged. `.venv` and audit `__pycache__` are ignored. Synthetic databases stayed in the external task-specific pytest basetemps; sessions/engines were closed. Audit evidence formatted with Ruff; no full-suite rerun warranted by formatting-only changes.
