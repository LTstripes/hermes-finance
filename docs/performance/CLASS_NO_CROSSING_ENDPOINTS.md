# Class no-crossing evidence and exact endpoints (C2/C3/C5 / #698)

This is Phase 1B under the accepted #534 amendment. It exposes endpoint
eligibility, never XIRR/TWRR. The first supported classes are `stock`, `bond`
and `gold`, portfolio-wide and RUB-only. Settlement cash is outside them.

## Evidence and write lifecycle

Migration 0046 creates `class_no_crossing_coverages` without defaults/backfill.
Each assertion stores one class, inclusive covered dates, state
(`complete`, `unknown`, `revoked`), `owner_attestation` provenance, an optional
reference label, revision and material signature. There is no statement-verified
source in this slice and no free-form notes. References must be privacy-safe
labels, never private payloads or credentials.

`POST /api/class-evidence/coverages` creates an explicit assertion.
`PUT /api/class-evidence/coverages/{id}` supplies its complete replacement,
including `unknown`/`revoked`, with required `If-Match` integer revision.
`GET /api/class-evidence/coverages` returns the evidence inventory.
Writes reserve SQLite's writer through commit/rollback, check both original
and proposed intervals against CLOSED periods/snapshot dates, reject overlapping
assertions of the same class and reject stale revisions. Reopen all intersecting
closed months before correcting/revoking/reaffirming evidence.

COMPLETE requires an explicit class-wide assertion against the current
persisted facts. Purchases/sales, distributions, principal, reclassification,
attributable fees/taxes, external in-kind and all other class entry/exit events
are covered by the assertion. Net-zero crossings remain crossings.
InvestmentCashFlow is a contradiction source, never complete trade history.
Known class-attributed cash facts reject the assertion; unattributed income/cost
facts block class completeness. Unattributed settlement deposits/withdrawals do
not alone assert security purchases or sales. Known events on either covered
date are checked; unknown ordering at the opening date is not inferred.

COMPLETE is bound to persisted membership, exact reporting identities, class
positions/quantities/values/currencies and relevant known flows/movements.
Current account flags, current instrument type, quotes and metadata are not
historical proof and cannot rewrite the binding. Reads compare this signature
to current committed material every time; there is no result cache.
Reopen retires intersecting COMPLETE assertions to UNKNOWN and increments their
revision, even if data is later restored unchanged. Explicit C1 correction
retires affected class assertions even if subsequently undone. A signature
mismatch is exposed as effective `invalidated` with the stored provenance/state
still visible; explicit reaffirmation replaces the binding in DRAFT.
Close never attests or repairs evidence. Whole-file backup/restore carries the
table; an old-schema recovery upgrade creates no assertions.

## Exact endpoint read

`GET /api/class-evidence/endpoints?asset_class=stock&start_date=...&end_date=...`
returns requested/actual dates, historical included account IDs, currency,
coverage state/provenance, status and sorted reason codes. Exact opening/closing
integer kopeck values appear only for `eligible`; otherwise both are NULL.

The whole historical portfolio universe uses existing
`AccountPerformanceScopeMembership` coverage, with gap/overlap/change checks
for catalogue accounts including historical exclusions. Current flags never
fill a gap. Endpoints must match exactly one reporting snapshot per requested
date. All observed interval snapshots must be CLOSED. Only persisted
`historical_instrument_type` class identity and `market_value_kopecks` are used;
NULL never falls back to today's catalogue. Stored bond value already carries
its existing accrued-interest basis; no recomputation/addition occurs here.

Unknown historical identities block completeness. Appearance/disappearance,
quantity changes, reclassification and relevant archived history fail closed.
Every historically included account must have a persisted position footprint
at both endpoints; an entirely missing account inventory cannot be interpreted
as an empty class. Cash/deposit rows do not repair this security-position gap.
All observed intermediate snapshots are checked as well as endpoints.
No trades/corporate actions are invented from deltas. The only accepted
quantity redistribution uses explicit existing `internal_transfer` markers
with instrument, positive quantity and Owner provenance, between continuously
included accounts, exactly reconciling per-account/per-instrument quantities
across adjacent snapshots. Unmatched/unknown markers block eligibility.
An exactly reconciled same-class internal movement is not itself a class crossing.

Exactly one evidence interval must match the request. This first slice does not
assemble unions, narrow larger assertions or produce empty-class zero values.
Clean rows never substitute for a whole requested class. Foreign components,
funds, FX/currency, deposits/savings and `gold_other` remain unsupported.

## Deterministic reasons

| Code | Meaning |
| --- | --- |
| `unsupported_class` | Outside stock/bond/gold capability. |
| `unsupported_currency` | Non-RUB setting or relevant instrument currency. |
| `membership_incomplete_or_changed` | Missing/overlapping/gapped/changing historical scope. |
| `historical_universe_empty` | No continuously included historical account universe. |
| `exact_endpoint_missing_or_ambiguous` | Requested snapshot date does not identify exactly one month. |
| `reporting_month_not_closed` | An observed interval month is DRAFT. |
| `historical_class_unknown` | A relevant historical position has NULL identity. |
| `historical_class_reclassified` | Observed instrument identities cross the requested class. |
| `archived_position_incomplete` | Relevant archived history cannot prove complete active endpoints. |
| `class_endpoint_empty` | No requested-class component at an exact endpoint. |
| `endpoint_account_positions_missing` | An included account lacks a persisted endpoint position inventory. |
| `position_set_changed` / `position_quantity_changed` | Quantities are not stable or exactly explained by accepted internal markers. |
| `known_cash_crossing` / `cash_flow_class_unknown` | Known class cash contradiction or unresolved class attribution. |
| `external_in_kind_crossing` / `in_kind_class_unknown` | Known external movement or missing historical movement identity. |
| `internal_transfer_ambiguous` | Internal evidence cannot reconcile the requested historical scope/quantities. |
| `no_crossing_coverage_missing_or_ambiguous` | No single exactly matching assertion. |
| `no_crossing_coverage_not_complete` | Stored assertion is unknown/revoked. |
| `no_crossing_material_changed` | Current authoritative material differs from the assertion's binding. |

No providers/background reads, return solvers, PRE/POST, execution ledger,
corporate-action engine, tax lots or portfolio/account-return changes are added.
