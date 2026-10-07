# H2-B1 portfolio evidence API

Implementation reference for [#731](https://github.com/LTstripes/hermes-finance/issues/731),
under the [accepted #729 contract](https://github.com/LTstripes/hermes-finance/issues/729#issuecomment-6039216401).
This backend bridge binds one existing H2-A1 flow per Apply. It creates no cash
facts, source occurrence owners, ReportingMonths or performance consumer inputs.

## Review and apply

- `POST /api/historical-portfolio-flows/preview` accepts a `PortfolioFlowIntent`.
- `POST /api/historical-portfolio-flows/apply` adds `request_id` and `confirmation_digest`.
- `GET /api/historical-portfolio-flows/{flow_id}` independently returns current authority.

An intent specifies `flow_id`, `expected_flow_revision` and
`expected_portfolio_revision` (zero means no portfolio acceptance). Operations
are `accept`, `reaffirm` and `revoke`. No financial amount, source replacement,
membership write or transfer reconciliation is accepted in a request.

Preview without claims discloses the immutable core and server-discovered
catalogue, dated memberships, source/mapping material, source-flow revisions and
permanent occurrence ownership, relevant legacy legs with full counterparts,
reconciliation and coverage inventory. It remains blocked. Nothing is inferred
from current account flags, absence of a counterpart, dates or amounts.

Review all catalogue candidates, including hidden/closed accounts and other
providers. Supply `roster` with the exact date, catalogue ID set and one typed
entry per candidate. `tracked` entries form the dated tracked universe; each
requires exactly one inclusive effective membership row. Other dispositions
(`not_yet_opened`, `no_longer_tracked`, `not_investment_account`) need explicit
historical confirmation and a bounded opaque reference. A relevant accepted
source or affirmative inclusion contradicts an asserted irrelevant disposition.
All roster and outside-counterparty booleans default to unconfirmed.

Preview the chosen roster entries to obtain `review_context_digest`, then bind
both attestations to that digest. Roster completeness confirms no relevant
unregistered/omitted historical tracked account. `outside` additionally binds
the exact flow and accepted revision ID, source-set fingerprint, core and owned
occurrences through the review digest. It confirms identifiable original
movement/counterparty, outside the entire tracked universe, non-transfer routing
and the exact actual Owner boundary amount with no inseparable fee/tax/gross-net
component. Only opaque reference labels are accepted, without native counterparty
IDs, statements, paths or replacement financial values.

Run Preview with the complete attestations and use its confirmation digest for
Apply. Apply reserves the SQLite writer before rereading all evidence and
checking both expected revisions and the digest. Acceptance and its receipt
commit atomically. A fresh identical intent adds a receipt but no revision or
economic event. Reusing a request ID for a different intent/digest conflicts.
Receipt replay returns the original committed revision identity and a fresh
current readback, including retirement/revocation.

## Authority and loss of evidence

GET separates `account_scope` / `account_effective_state` from `portfolio_scope`
and portfolio acceptance/effectiveness. A portfolio amount is supplied only for
an effective EXTERNAL contribution/withdrawal using the unchanged exact H2-A1
core. Explicit unique historical exclusion reports `not_in_scope`; missing or
ambiguous membership stays `unknown`. `cash_coverage` always remains `unknown`.

Generic dated unsupported Money requires its existing effective row-specific
H2-A1 semantics. Potentially relevant opaque Transfers/UFSR and unresolved
source/mapping identities block promotion. Legacy link status cannot supply an
H2 source bridge: one-legged/unresolved relationships and relevant resolved
transfers remain blocked, with full explicitly linked legs and reconciliation
disclosed even outside the event date/report range. Demonstrably unrelated
source ranges and completed transfer spans are excluded from current evidence.
No pairing, netting, transfer residual, fee allocation or transit valuation is
performed.

Portfolio revisions and receipts are append-only. ORM dependency hooks retire
acceptances transactionally across the whole disclosed catalogue, including
another account's membership and H2-A1 retirement/revoke. GET reconstructs
current support without writes. Migration `0053_historical_portfolio_flows` also
installs an append-only structural SQL change journal (table/row keys and date
intervals only). Digest-bound relevant journal IDs prevent SQL bypass A→B→A
from reviving an old acceptance. No-op writer reservations add no change events.
Existing account authority is preserved unless its own H2-A1 lifecycle retires it.

Reviewed `reaffirm` can restore the same core with fresh dependencies/claims;
portfolio `revoke` works even with broken positive support. Revoke never removes
valid account evidence. Independent acceptance needs no ReportingMonth and
calendar overlap with CLOSED does not prohibit it. Existing protected dependency
corrections retain their explicit Reopen guards; close/reclose never restores
portfolio authority.

## Synthetic evidence

`backend/tests/test_statement_import_historical_portfolio_flows.py` covers
positive/negative exact cash, full/subset/disposed rosters, missing/overlapping
memberships, inclusion/exclusion and unsupported account types, every affirmative
claim, row/revision binding, other-account opaque/unsupported sources, explicit
legacy counterparts/transit/differences, dependency retirement and SQL bypass,
stale/concurrent Apply, rollback, replay/noop/revoke/reaffirm, strict HTTP requests,
empty-schema migration and append-only/loss guards, backup/restore, independent
CLOSED overlap and unchanged coverage. Fixtures contain fabricated data only.

Source-aware CashBoundaryCoverage is an independent compatible gate. Its projection
and revisions do not confer or retire portfolio authority; H2-B1 cash_coverage
remains UNKNOWN. Source-free COMPLETE coverage remains a blocking dependency.
