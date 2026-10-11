# Source-first MyBroker month (S2b supported slice)

Issue #773 adds original XML → zero-write whole-account Preview → reviewed atomic
DRAFT Apply → independent GET → existing global Close. The receipt joins existing
immutable S1, stage-only identities, canonical S2 trades and native finance rows;
it does not introduce another trade, cash or payout ledger.

The supported slice requires an existing exact-compatible RUB stock/bond catalogue,
one explicitly bound active broker/IIS account and the exact existing DRAFT month
with its final-day snapshot. New currency remains `instrument_currency_unproven`
under #777. Unsupported instruments cannot be skipped to make the account complete.
Position quantity and native total, beginning and ending values, separate RUB cash
and the full Money inventory remain distinct. Source cash is not incremented again
by settlement or payouts. Missing tax, cost and bond NKD stay null.

Only accepted S1 trade settlement/commission patterns and canonical native trade
keys are financial authority here. No accepted generic Money manifest exists yet:
#778 owns coupons, dividends, owner funding and unlinked paid trade NKD. These rows
are inventoried as visible exceptions, never inferred from text, sign, aggregate,
date/amount or source ordinal. Explicitly incomplete DRAFT is allowed, but material
unknown Money blocks the covered account at Close. #773 is not fully complete or
ready for Owner UAT until the accepted #778 integration.

Preview confirmation binds original bytes, selected account/month, identity/source
revisions, financial dependencies and supplied optional-document hashes. Apply
reserves the writer, revalidates and stages all changes in one transaction. Any
failure rolls back identity/source/trade/position/cash/receipt writes. Same-intent
request replay returns the original receipt with zero new economic rows, including
after Close; it cannot mutate CLOSED. Overlaps reuse canonical trade identity.
Manual or conflicting facts require explicit reconciliation rather than overwrite.

GET reads the accepted immutable S1 source and current authority/projection under
one snapshot. Readiness and reserved server Close share the same source checks:
all positions and cash must still match, mappings/source authority must remain
valid, intersecting evidence must have no material unresolved conflicts. Hard
guards apply only to accounts explicitly covered by source-owned receipts.
Unrelated active accounts retain `active_account_snapshot_missing` warnings;
ordinary months keep existing behavior. Account readiness does not attest whole
portfolio coverage: `coverage_state=unknown`, exact XIRR/TWRR remain unavailable.

Optional documents are absent by default. Supplied documents without an accepted
typed reader are hashed and disclosed as `optional_evidence_unsupported`, blocking
Close rather than producing guessed corroboration. Dedicated optional adapters
remain deferred. The desktop route currently accepts the original XML only.

Migration 0057 adds an empty append-only ownership receipt table with source/month/
account foreign keys. It neither backfills financial data nor reparses legacy S1.
Downgrade refuses populated source-owned receipts to prevent lost ownership.

Synthetic backend regressions cover exact values/missingness, replay, both overlap
orders, distinct native IDs, stale review, full rollback, conflicts and reserved
Close concurrency. Desktop tests verify explicit review, failed/mismatched GET,
CLOSED reading and real API Preview → Apply → GET → global Close at desktop widths,
including the incomplete Money path. Synthetic evidence is not Owner acceptance.
