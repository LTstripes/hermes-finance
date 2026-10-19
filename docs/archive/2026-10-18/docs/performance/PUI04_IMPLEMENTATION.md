# PUI-04 Owner preparation candidate

Issue #532; assigned baseline `ccee3902335e82b01215c455a9a64746f1b3c00a`.
Independent integrity review, Integrator acceptance and isolated Owner UAT remain
required. The [historical membership proposal](HISTORICAL_MEMBERSHIP_LIFECYCLE_PROPOSAL.md)
is pending review; no historical membership writer is implemented.

## Delivered boundary

Preparation is embedded in the accepted Capital Performance detail. This avoids
another global route/spine change. Existing `start/end/scope/account_id/view` stay
unchanged; `prepare_account` and `prepare_reason` retain the selected repair context
through deep link/back/refresh. Account scope cannot silently prepare another account.

The Owner sees canonical external-flow classifications, exact amounts/source,
transfer links and independent cash/in-kind records. Empty lists require explicit
zero-activity attestation; incomplete history can be saved as unknown. Existing
coverage is reaffirmed only for its exact displayed interval; overlapping/different
intervals cannot be silently merged or overwritten. Cash account binding is an
explicit action. Creating a transfer link does not infer its legs; each leg is
attached explicitly and canonical reconciliation rules may reject conflicts.

Flow corrections reuse canonical invalidation. Current include flags, legacy
flows/imports, capital delta and payouts are never historical evidence. Membership
and PRE/POST inputs remain unavailable. Saving and recomputing never calls a provider
or automatically opens/closes a report.

## Technical DTO and optimistic guard

`GET /api/performance/preparation?account_id=&start_date=&end_date=` returns one
coherent committed snapshot: context, canonical flow/coverage/movement/cash response
DTOs, transfer links, relevant reporting-period statuses and `evidence_token`.
Both interval endpoints are shown for source inspection; solver interval semantics
remain backend-owned. Snapshot-date matches include boundary reports even when their
reporting period is outside the requested dates.

The preparation client sends `X-Performance-Evidence` on existing canonical POST/PATCH
routes. Before any service reads/mutations, its request session reserves SQLite's
writer and compares a SHA-256 token of the complete preparation source tables:
accounts, historical membership, reporting months, cash balances, external flows,
transfer links/reconciliation evidence and cash/in-kind coverage/movements. Partner
legs and old intervals are included. Any mismatch returns 409 without mutation.
The lock remains through canonical commit/rollback, including CLOSED guards. This
is conservative conflict detection: even an unrelated preparation-source edit may
require rereading. It is neither a persisted revision nor financial evidence.
Existing clients without the optional header retain their contracts.

The token is captured with the displayed ledger and is never refreshed just before
POST to disguise an old attestation. Double-clicks have a synchronous client latch;
concurrent duplicate creates using the same token admit one changed state only.
No write retries occur automatically. On ambiguous outcomes the form locks until
explicit reread and inspection. On successful response, invalidate dependent queries,
read back the saved record and reread canonical readiness (including both final
XIRR/TWRR). Read failure or identity mismatch is not success. Unavailable metrics
remain unavailable, including while reports await explicit reclose.

## Evidence map

- API synthetic tests: empty ledger, separate attestations, stale form, concurrent
  duplicate create, CLOSED with fresh/stale token, correction invalidation,
  canonical transfer classification, rollback and zero-history/reclose/readiness.
- Component tests: explicit zero confirmation, incomplete history, CLOSED, context,
  exact decimal transport, transfer preservation and ambiguous-write lock.
- Browser synthetic checks: 390px and desktop, keyboard, overflow and screenshots.
- Final gates: affected backend/frontend tests, full backend/frontend suites,
  lint/format/build, exact-head CI and separate integrity review.

No Owner data, provider calls, migration, new financial formula, #533 or merge.
