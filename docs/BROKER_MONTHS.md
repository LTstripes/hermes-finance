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
Affirmative zero holdings remain in source inventory without fabricated position
rows. Missing security inventory is unproven, not observed zero; fractional stock
quantities are explicit Preview conflicts. Balanced endpoints cannot clear an
unresolved canonical settlement principal, commission or cash ownership.

Accepted S1 trade settlement/commission patterns and canonical native trade keys
retain their authority. The #782 extension under accepted #781 adds only explicitly
reviewed actual net coupons and account funding to an existing source-owned DRAFT.
Coupons use InvestmentCashFlow; funding uses H2 v2 HistoricalOwnerFlow. Neither
creates ExternalFlow nor adds source cash again. Dividend, paid NKD, fees and opaque
Money remain visible scoped exceptions; #783 owns NKD/fees. Incomplete DRAFT is
allowed, but material unknown Money blocks the covered account at Close.

The Money Preview requires original bytes for the complete accepted overlapping
source union. Original observations guide specific instrument/payment/boundary
review; they do not mint payment identity from date, amount or narrative. The server
assigns coupon identity and retains permanent occurrence-to-target ownership,
including old H2/S2 owners and revoked evidence. Indistinguishable repetitions and
missing events in a covering report block acceptance. A typed PDF can explicitly
link the same ICF; it cannot invent missing gross, tax or commission components.

Money Apply reserves the writer, revalidates all dependencies and stages ICF, H2,
ownership links and proof in one transaction, followed by independent GET. Versioned
Money proof and monotonic retirement/dependency tokens use the existing append-only
BrokerMonthApply journal; legacy receipt JSON and S1 are unchanged. A → B → A cannot
revive stale review. Retired proof requires reviewed reaffirmation of the same core
targets. Replay returns current disputed/readiness state without adding money.

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
Supplied optional evidence remains attached to its receipt. Source/control and
authority failures are recomputed rather than frozen: successful compatible
canonical enrichment clears its temporary projection blocker. Preview and GET
also retain every applicable receipt's unresolved evidence at account level.
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
Migration 0058 adds only permanent Money occurrence links with ICF/H2 target and
receipt foreign keys; it performs no financial backfill and refuses downgrade when
links are populated. The desktop extension accepts the required original XML set.

Synthetic backend regressions cover exact values/missingness, replay, both overlap
orders, distinct native IDs, stale review, full rollback, conflicts and reserved
Close concurrency. Desktop tests verify explicit review, failed/mismatched GET,
CLOSED reading and real API Preview → Apply → GET → global Close at desktop widths,
including the incomplete Money path. Synthetic evidence is not Owner acceptance.
