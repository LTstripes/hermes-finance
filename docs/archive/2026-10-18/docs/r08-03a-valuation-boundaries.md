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
- a material signature of that flow, or of the group and every current member.

The signature uses the flow ID, reporting month, account, event date, exact
minor-unit amount, direction, kind, currency, scope membership and transfer
link. Group signatures also bind the group ID, month, scope, account, boundary
date and sorted member identities/signatures. Source, notes and timestamps are
metadata and do not change the signature. Every capture passes the signature
read when it began; persistence compares it with current state
under a SQLite writer reservation. Both PRE and POST must bind the same current
signature. Preexisting observations with no signature are unavailable until
freshly captured; migration does not infer their original event state. Once the
capture-start signature matches the current target under the writer reservation,
recapture retires older unbound or stale points for that same scope and boundary
before saving new evidence. A partial fresh pair remains unavailable.

The capture services accept only draft reporting months. Existing monthly
snapshots, legacy investment cash flows, historical scope membership and
current account flags are not backfilled or reinterpreted. Portfolio-internal
transfers cannot create a boundary group.

Boundary groups and observed points are scope-specific. Availability considers
only groups matching the requested scope and account; one external flow may
therefore have separate valid account- and portfolio-scope groups and evidence.

Group membership is immutable after creation. Both valuation capture and
performance availability revalidate every current member against the group's
reporting month, scope/account and boundary date. A group is unusable if a
member changes date or leaves the selected scope; it cannot accept new observed
points or make TWRR exact. To correct a stale date or membership, delete the
group in its editable reporting month, then explicitly create a replacement
with the chosen date and member IDs and capture fresh PRE/POST observations.
Deleting a group also deletes its members and observed points. The service does
not infer a replacement date or membership. Direct boundaries for flows that
are not members of a group keep their existing lifecycle.

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
