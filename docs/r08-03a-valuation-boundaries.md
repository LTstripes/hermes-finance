# R08-03A — observed valuation boundaries

This is the additive prerequisite for [issue #147](https://github.com/LTstripes/hermes-finance/issues/147),
implemented for [issue #213](https://github.com/LTstripes/hermes-finance/issues/213). It
provides persisted evidence for exact TWRR segmentation without calculating
TWRR, XIRR or any approximate return.

## Persisted evidence

`external_flow_boundary_groups` identifies an explicit same-date group at a
`portfolio` or `account` scope. Its members are persisted in
`external_flow_boundary_group_members`. The capture service sorts member IDs
and permits one explicit group per selected scope, reporting month and event
date; it never groups flows from a date implicitly.

`observed_valuation_points` stores one owner/provider-captured observation with:

- an exact non-negative minor-unit value and explicit `performance_currency`;
- `complete`/`unavailable`/`unknown` coverage and `exact`/`unavailable`/`unknown`
  quality;
- required provenance kind and optional provenance reference;
- an explicit `pre_external_flow` or `post_external_flow` relation;
- exactly one target: `external_flow_id` or `boundary_group_id`.

The capture services accept only draft reporting months. Existing monthly
snapshots, legacy investment cash flows, historical scope membership and
current account flags are not backfilled or reinterpreted. Portfolio-internal
transfers cannot create a boundary group.

## Read-only availability

`GET /api/performance/availability` exposes `external_flow_boundaries`. Each
entry contains the deterministic flow ID tuple, event date, availability,
both observed sides when present, exact values/provenance, and stable reason
codes. A side is usable only when its relation/date, coverage, quality and
performance currency are valid. For either explicit relation, `observed_date`
must equal the flow or group `boundary_date`; an earlier PRE or later POST is
not exact boundary evidence. Missing sides fail closed with
`not_computable_valuation_boundary_missing`; ambiguous or unproven same-day
ordering fails closed with
`not_computable_valuation_boundary_order_unknown`.

The response remains evidence-only: it contains no return factor, percentage,
TWRR/XIRR value, interpolation, provider refresh or inferred valuation. The
future #147 calculator may consume this contract without redefining flow,
transfer, currency or historical-scope semantics.
