# Historical source-backed ending endpoints — H1-A

Authority: [#723](https://github.com/LTstripes/hermes-finance/issues/723),
[accepted contract](https://github.com/LTstripes/hermes-finance/issues/721#issuecomment-6025311447)
and [frozen amendments](https://github.com/LTstripes/hermes-finance/issues/721#issuecomment-6025408148).
S1 and S2 retain their existing [source](MYBROKER_S1.md) and
[execution](MYBROKER_S2_A.md) meanings.

One accepted `mybroker-s1-v2` document supports one mapped account at its exact
`covered_to` EOD: RUB stocks and one separate complete RUB cash row. Each source
row is referenced by import, section, ordinal and fingerprint. Quantities and
source total values retain their canonical decimal strings. RUB money must be
exactly representable in signed 64-bit integer kopecks; fractional kopecks and
overflow block acceptance. No price, cost, P&L, NKD or FX is derived.

Migration `0050_historical_endpoints` adds two empty tables without backfill:
`historical_endpoint_revisions` and `historical_endpoint_applies`. Revisions and
receipts are append-only, with SQL triggers protecting migrated databases;
populated downgrade refuses loss. Supported whole-file backup/recovery preserves
both. The endpoint key is account + exact date + EOD + RUB; provider and source
side are provenance, never additional economic identities.

## API

1. `POST /api/historical-endpoints/preview` with operation `accept`, account ID,
   exact valuation date, accepted source import ID and `source_side=ending`.
   With missing claims it returns observations, sorted blockers and the backend
   source-set fingerprint for the explicit review.
2. Supply typed `owner_attestation` claims bound to account, date, ending side,
   complete source-set fingerprint and every position-row fingerprint.
   Required assertions are `inventory_complete`, `other_components_absent`,
   `rub_cash_complete_and_reconciled`, and `rub_stock_basis_confirmed`.
   The reference is a bounded label using letters, digits, underscore or hyphen;
   it is not a filename, path or free-form narrative. Defaults remain unconfirmed.
3. Apply the same intent with the reviewed `confirmation_digest` and a unique
   `request_id` to `POST /api/historical-endpoints/apply`. Existing targets require
   the exact `expected_revision`. No browser financial amounts or C1 fields are
   accepted. Apply obtains the writer reservation before rereading authoritative
   context and holds it until commit/rollback.
4. Independently `GET /api/historical-endpoints/{endpoint_key}`. Apply also returns
   readback from a new coherent DB session, plus the committed receipt revision.
   GET rederives the components from immutable S1 and compares the frozen envelope;
   only effective accepted evidence exposes `total_value_kopecks`.

Fresh identical requests write receipts without additional endpoint revisions.
Exact receipt replay returns the original committed revision identity plus current
readback, including later retirement/invalidation. Key reuse with different intent
or confirmation conflicts. Restoring authority requires reviewed `reaffirm`;
different economic quantity/value/cash remains reconciliation-required. Explicit
`revoke` targets the existing revision with `owner_withdrawal` or
`evidence_disputed`, without new source/claims.

## Evidence and lifecycle

Claims cannot override duplicates, missing/ambiguous cash, opaque source sections,
pending/forward exposure, canonical disputed settlement or incompatible recorded
components. Historical membership must be unambiguous; explicit exclusion stays
excluded. Stock admissibility is endpoint-only Owner evidence. It establishes no
C1 or class/return coverage; `endpoint_c1` remains null. Generic interval fee/cash
limitations remain separate from endpoint blockers.

Overlap compares exact snapshot dates, full instrument/quantity/value composition,
owned RUB cash and additional components, including DRAFT/CLOSED material and
archived provenance. Matching totals cannot conceal offsetting differences.
Identical overlap corroborates and never adds another amount. Unknown archive/date
or ownership relationships fail closed.
An archive's reporting label and quote date do not prove its original snapshot
date. Potentially relevant unresolved archival dates block acceptance. Earlier
source actual/forward disagreements remain unresolved across later cutoffs; a
later clean report alone cannot settle position-level exposure.

`retire` is dependency lifecycle loss of authority; `revoke` is a reviewed Owner
action. Frozen mapping/instrument identity, membership, canonical execution revision and month-owned
overlap changes append retirement transactionally with sanctioned writers.
Component-set additions/removals also retire the frozen account/month dependency;
removing a newly added conflicting component cannot silently revive acceptance.
Reopen/date-change/delete uses exact frozen month dependencies; an independent
endpoint inside a month's calendar dates is not retired merely by those dates.
Ordinary Close changes no acceptance. Dependency correction requires applicable
CLOSED periods to be reopened; contradictory newly accepted evidence can immediately
invalidate reads without rewriting CLOSED history. Restoring amounts or reclosing
does not reactivate retired authority.

No ReportingMonth, PositionSnapshot, CashBalance, DepositSnapshot, flow, coverage
or return-consumer writes are produced by H1 Apply. Beginning Apply, mixed assets,
multiple account/report assembly, conflicting replacement and historical monthly
materialization remain separate slices. Independent financial/data review,
exact-candidate CI and applicable Owner-local UAT remain separate gates.
