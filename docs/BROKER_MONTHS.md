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
creates ExternalFlow nor adds source cash again. Accepted #783 additionally handles
an individually proved settled RUB **bond BUY** with negative posted paid NKD and
a separately charged nonzero native-linked fee through the existing
ExecutedTradeRevision. No duplicate endpoint cash or inferred EOD NKD/cost arises.
Stock BUY separate commissions without paid NKD remain outside that bond proof
(#790 pending). Unknown dividends, opaque Money and unsupported source sections
remain visible scoped exceptions. An incomplete DRAFT is allowed; unresolved
evidence blocks its covered account at Close.

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
Journal revision order is assigned under the writer reservation, independently of
wall-clock timestamps. A compatible staged coupon addition preserves unchanged
earlier payouts. Legacy PDF technical tax zero is displayed as unknown when its
accepted provenance marks tax unavailable; stored legacy facts are not rewritten.
Claim-free coupon reuse is limited to the already proven complete occurrence set.
A distinguishable second coupon cannot be linked to that payout even with matching
amount/date and supplied claims. Money funding requires H2 v2; legacy v1 authority
needs explicit version-bound reaffirmation, retaining its original receipts.
Independent GET retains batch targets and also returns all current targets for the
source-owned account/month, so the desktop panel preserves earlier acceptances.
Compatible additive typed PDF LINK_EXISTING keeps the original Money authority:
the ICF facts and existing PDF support must remain identical, and each added
attachment must contain one matching initial link revision for that exact target.
Later PDF revisions, retractions or contradictions retain monotonic retirement.
Lifecycle retirement follows the affected target and reporting period (including
old scope when a row moves), so cash/payout/PDF changes in another month of the
same account do not retire independent accepted Money.

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

## Real September Owner-local Gate 0 — 2026-10-11, BLOCKED

This is a dated source-compatibility result, not another parser family or a
production UAT. [#787](https://github.com/LTstripes/hermes-finance/issues/787#issuecomment-6112959100)
reported a complete unmodified private MyBroker source with individually
compatible stock/bond identities, independently matching source/native cash and
quantity controls, and no scratch database or financial Apply. Original file
identifiers, source monetary amounts/hashes and machine targets are Owner-private.

Live `main@e512338b` still requires three distinct acceptance paths:

1. [#788](https://github.com/LTstripes/hermes-finance/issues/788):
   original native settlement/commission Money has the exact primary-ID text in
   `oper_type`, while accepted legacy S1 linkage reads `comment`.
   A safe versioned extension must preserve existing accepted S1 normalized
   rows, fingerprints and receipts. No guessing the second native trade ID.
   Draft PR #791 is **not accepted or merged** at this checkpoint.
2. [#789](https://github.com/LTstripes/hermes-finance/issues/789#issuecomment-6113268340)
   metadata contract: exact empty Transfers and UFSR connected-status-only trees
   may be classified as *no economic movement* only with strict complete
   namespace/attribute/child validation, preserving raw inventory. The
   corresponding bounded implementation is [#792](https://github.com/LTstripes/hermes-finance/issues/792)
   after #788. Populated daily Money `all_volume` and `debet_volume` have no
   proven independent per-date account/basis equation:
   [#793](https://github.com/LTstripes/hermes-finance/issues/793) is a separate
   read-only investigation. Control-only fields do not mint payments or daily
   valuations; even exact total cash arithmetic cannot clear this blocker.
3. [#790](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113269181):
   strictly proven two-leg settled RUB stock BUY separate fee is a future
   compatible **financial proof variant**, not a relaxation of #783 bond
   three-leg proof. A documented, independently reviewed fee-excluded native
   amount basis is required; equal numerical sums alone cannot provide it.
   New fee proof may reuse existing ExecutedTradeRevision and Money ownership,
   but never create an artificial `paid_nkd=0`, another cash ledger or
   a general exemption from commission blockers.

[#787](https://github.com/LTstripes/hermes-finance/issues/787) remains
**Gate 0 BLOCKED** even though private raw controls reconcile to zero residual.
Recheck the unchanged Owner original **read-only** only after integrated
compatible code and exact post-main CI. Creating an isolated scratch DB, DRAFT
Apply and eventual scratch Close each require separately explicit Owner GO.
Protected Test/Stable/CLOSED and actual historical data must remain untouched.
Bond reported EOD value can be retained as a **source-marked value** with
unknown accrued NKD; this does not authorize exact economic XIRR/TWRR.
