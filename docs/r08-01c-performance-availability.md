# R08-01C — performance availability contract

This document records the backend-only availability contract from issue #197.
It is an evidence contract for downstream exact XIRR/TWRR work; it does not
calculate either metric.

## Read-only API

```text
GET /api/performance/availability
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=portfolio|account
    [&account_id=<id>]
```

`start_date` and `end_date` are exact persisted valuation dates and
`start_date` must be before `end_date`. `account_id` is required for
`scope=account` and is forbidden for `scope=portfolio`.

The top-level `availability` is conservative: it is `available` only when
both downstream prerequisite assessments are available. Consumers should use
`xirr` and `twrr` separately because XIRR can be available when exact TWRR is
not.

The response contains:

- `opening_valuation` and `closing_valuation` with the selected reporting
  month, exact valuation date, total, component coverage and source
  provenance;
- `scope_membership` with effective-dated account evidence for the whole
  interval;
- `external_flows` with sanitized exact flow metadata, classification,
  transfer status, legacy unclassified row IDs and coverage reasons;
- `external_flow_boundaries` with deterministic pre/post observed valuation
  evidence for each selected-scope external flow or explicit same-date flow
  group;
- `xirr` and `twrr` prerequisite availability, each with stable reason codes.

No return value, return percentage, inferred valuation or converted foreign
currency amount is returned.

## Evidence rules

### Opening and closing valuations

Each boundary must resolve to exactly one persisted `reporting_months` row
whose `snapshot_date` equals the requested date. A missing or ambiguous match
is unavailable; a later or neighboring month is never substituted. The
selected month must be closed. The R08-01B valuation service must also report
all selected position, deposit and performance-cash components as authoritative
in the base currency. Missing components stay unknown and are not emitted as
zero.

Existing position and deposit snapshot amounts are base-currency values under
their persisted schema. A cash row without an explicit account identity is
unclassified for performance scope. Non-base-currency cash or flow requires an
accepted dated conversion, which is not available in this v1 slice.

### Historical scope membership

The service uses only `account_performance_scope_memberships` for historical
scope selection. Every account relevant to a portfolio request, or the
explicit account request, must have gap-free non-overlapping effective-dated
membership evidence over the requested interval. The present account flag is
never used to rewrite history.

### External-flow completeness

Explicit R08-01A flows are selected by their exact `event_date` over the
interval and classified at the requested scope. A linked two-leg transfer is
internal for portfolio scope and crosses the boundary for each affected
account scope. A one-sided or otherwise unresolved link blocks the affected
scope. An unknown persisted flow membership is non-authoritative.

Legacy `investment_cash_flows.deposit` and `withdrawal` rows remain legacy
evidence. When they affect the selected scope, they block exact external-flow
completeness; they are never automatically reclassified and no gross/net field
is guessed as the boundary amount. Forecast cash flows and provider payout
calendar rows do not become realised performance flows.

### XIRR and TWRR prerequisites

XIRR prerequisites require trusted opening and closing valuations, complete
historical membership, complete dated external-flow evidence, no unresolved
transfer identity and complete conversion into the performance currency.
Date-only same-day ordering is not an XIRR blocker under the accepted #145 v2
contract.

Exact TWRR additionally requires an explicit observed valuation boundary around
every external flow. R08-03A persists an observed point with an exact
performance-currency value, complete coverage, provenance and quality, and
relates it explicitly to one flow or same-date flow group as
`pre_external_flow` or `post_external_flow`. The read-only response exposes
both sides under `external_flow_boundaries`; a boundary is available only when
both sides are present, exact, complete and in the requested performance
currency.

An interior flow without an observed boundary is
`not_computable_valuation_boundary_missing`; an otherwise available same-day
observation without an explicit relation, or multiple ungrouped same-day
flows, is `not_computable_valuation_boundary_order_unknown`. No interpolation,
timestamp-only ordering assumption or start/end-of-day convention is exact.

## Stable reason codes

The contract preserves the accepted codes:

```text
not_computable_opening_valuation_missing
not_computable_closing_valuation_missing
not_computable_external_flows_incomplete
not_computable_scope_coverage_incomplete
not_computable_scope_cash_unclassified
not_computable_scope_membership_history_missing
not_computable_currency_conversion_incomplete
not_computable_transfer_identity_unresolved
not_computable_valuation_boundary_missing
not_computable_valuation_boundary_order_unknown
```

Existing valuation-point diagnostics such as
`not_computable_reporting_month_not_closed`,
`not_computable_snapshot_date_missing` and
`not_computable_unsupported_position_valuation` may accompany these codes.
