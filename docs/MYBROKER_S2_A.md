# Canonical executed trades — S2-A

Authority: [#715 accepted contract](https://github.com/LTstripes/hermes-finance/issues/715#issuecomment-6020840994),
[independent contract review](https://github.com/LTstripes/hermes-finance/issues/715#issuecomment-6021132369),
[Integrator acceptance](https://github.com/LTstripes/hermes-finance/issues/715#issuecomment-6021303144)
and [#717 sequencing](https://github.com/LTstripes/hermes-finance/issues/717#issuecomment-6023408545).

S2-A consumes accepted [S1 lineage](MYBROKER_S1.md) without reparsing or rewriting
documents. The `mybroker-s1-v2` endpoint fields and legacy absent endpoint keys
retain their meaning. This slice exposes an API; it adds no reconciliation UI.

## Persistence and source linkage

Migration `0049_executed_trade_truth` adds four empty tables without backfill:

- `executed_trades`: stable Hermes ID, unique provider/source account/ordered
  native-ID pair, frozen economic core and exact accepted mapping IDs/targets;
- `executed_trade_occurrences`: unique S1 import/section/ordinal references and
  source fingerprints, separate from economic execution identity;
- `executed_trade_revisions`: append-only accepted lifecycle/evidence snapshots,
  revision/material fingerprint, reviewed confirmation digest and acceptance time;
- `executed_trade_applies`: idempotency receipts for entire selected sets.

Core quantity/price and source amounts are lossless canonical decimal strings.
RUB money additionally uses integer minor units with `ROUND_HALF_UP`; a minor-unit
value for an unsupported currency stays null, with the original source amount
and currency retained. No quantity × price, FX, bond/NKD or cash projection is
performed. A populated ledger/receipt refuses destructive downgrade.

The alias requires both native IDs. Overlapping documents add provenance, never
another execution or cash leg. Distinct native pairs with identical economics
stay distinct. Exact settlement/commission material has one canonical leg with
all supporting S1 money-row references. Multiple differing legs and ambiguous
primary-only linkage remain conflicts; split/refund cases are not aggregated.
Identical repeated money rows within a single document retain observed
multiplicity and all row references; they never prove a single settlement or
single economic cost. Cross-document repetition remains occurrence lineage.
Money-row ownership is recomputed from source account and primary native ID
across the full accepted union before using any stored linkage, including null
links. An incomplete-ID observation competing with a full identity is ambiguous.

## Lifecycle and evidence

`pending` stores prospective observation and planned dates, without actual dates
or actual cash legs. Monotonic pending → settled enrichment preserves the economic
core and earlier revision. `settled` can still lack actual cash/depo dates, usable
money evidence, fee basis or historical event-C1. These are separate readiness
dimensions; source settlement-money rows remain authority, while trade amount
only checks consistency. Nothing becomes financially ready in S2-A.

Fee basis supports `zero / separate / embedded / unknown` in persistence. S2-A
can establish only an explicitly observed zero with no commission leg, or
`unknown`. Nonzero linked fee rows remain attributable source evidence, without
accepting separation/embedding or another economic cost. S2-B owns those explicit
reconciliations. Event-C1 remains nullable and is never filled from the current
catalogue, an account name or a neighbouring snapshot. Source lifecycle is
distinct from active/superseded/retracted acceptance; S2-A writes only active
source acceptance and cannot correct/retract a previous acceptance.

## API and authoritative acceptance

Use identities returned by `/api/mybroker-import/lineage`:

1. `POST /api/executed-trades/preview` with `{"identities": ["<source digest>"]}`.
   Candidates disclose `create / enrich / noop`, frozen bindings, source
   occurrences, actual/planned dates, cash evidence and conflicts/readiness.
2. `POST /api/executed-trades/apply` with the same selected identities,
   `confirmation_digest` and a caller-generated `request_id`. No normalized
   browser rows, arbitrary fee/C1 facts or target corrections are accepted.
3. Independently `GET /api/executed-trades/{trade_id}` (or the collection) and
   compare the committed aggregate, revision, evidence and conflicts.

Preview binds the full accepted source union/document hashes/ranges/parsers,
mapping lifecycle, canonical revisions/occurrences, month states, historical
memberships, legacy reconciliation facts and dependent coverage. Apply reserves
SQLite's writer before authoritative reread; changed state refuses the entire
set. Any selected conflict or write failure rolls back all aggregate, occurrence,
revision and receipt writes. Identical fresh material is a revision no-op.

An exact request replay returns current committed readback without writing; a
reused key with different selected identities/confirmation is an idempotency
conflict. A replay does not reaccept or repair newer source/mapping changes.
Every read reports current conflicts separately from the frozen accepted core
and exposes prior revisions. New S1 evidence requires another reviewed enrichment;
changed core/bindings or withdrawn/disputed support cannot overwrite acceptance.

## Dependencies and boundaries

Accepted COMPLETE no-crossing contradictions block acceptance; source/class
guards remain in place. Canonical accepted or disputed executions independently
block affected historical account intervals for all potentially affected classes
while event-C1 is unresolved. Pending persists through later cutoffs; actual
cash/depo/fee dates remain distinct. Missing/changed source support cannot restore
no-crossing by disappearance. Class material signatures additionally bind
canonical revisions when relevant. Dependency guards remain anchored to the
latest accepted canonical revision; newer S1 evidence can strengthen blocking
but cannot relax it until S2 Apply explicitly accepts the enrichment.
Read blocking does not mutate CLOSED months, coverage claims or endpoint facts,
and source-only append-only promotion does not authorize financial correction
through CLOSED history.

Coverage remains `unknown`. No ReportingMonth, PositionSnapshot, CashBalance,
InvestmentCashFlow, ExternalFlow, payout, transfer or UFSR fact is created or
changed. No return consumer, historical reconstruction, realized P&L or bond
arithmetic is enabled. S2-B reconciliation/correction/retraction, #709 backfill,
financial/data candidate review and Integrator acceptance remain separate.

## Reviewed paid-buy cash extension

[#781 accepted contract](https://github.com/LTstripes/hermes-finance/issues/781#issuecomment-6109886284)
and #783 extend an existing source-owned DRAFT through the `broker_money_v1`
batch. A `trade` decision selects one original negative paid-NKD Money occurrence,
the existing canonical `trade_id` and its exact `expected_trade_revision`.
`TradeCashClaims` binds a specific review to the server's context digest and
separately confirms the settled RUB bond BUY link, the complete occurrence set,
separately posted NKD, separately charged nonzero native-ID commission and an
independently proved native-total basis. The desktop form discloses the ordered
native IDs, posted S/N/F, native T/summ_nkd/bank_tax and actual cash/custody dates.

`includes_paid_nkd` checks `-(S+N)=T`; `excludes_paid_nkd` checks `-S=T`, using
signed debits. Neither equality discovers the basis. Native NKD and fee must
agree exactly in kopecks with the separate negative Money legs. The actual
cash debit remains `S+N+F` once. Fractional kopecks, missing/multiple cash legs,
unsupported pending/REPO/FX, ambiguous primary linkage, changed mappings and
target reassignment refuse the entire batch.

Apply appends the existing `ExecutedTradeRevision` with `fee_basis=separate`,
three cash legs and the accepted reconciliation. Money occurrence ownership
uses existing `ExecutedTradeOccurrence` entries, the same cross-writer mutex
as coupon/H2 ownership, and the existing immutable month receipt journal.
No migration, second cash ledger, payout/owner event for NKD, endpoint cash
increment or inferred EOD NKD/cost basis is introduced. Accepted S1 JSON and
earlier revisions stay immutable.

Candidate rebuild, canonical GET, source-account readiness and reserved Close
revalidate the same receipt and reconciliation. A source union/target/catalogue
change or reopening retires authority monotonically; restoring old values or
replaying an old request cannot reaffirm it. New explicit review is required.
One supported trade does not clear opaque Money, unparsed UFSR/REPO/transfer
sections or other source gaps. C1, portfolio scope and exact returns remain
unavailable. Synthetic Close evidence does not establish real-account Close.

## Stock BUY separate commission — typed code integrated; real-source basis BLOCKED

[Independent #790 financial/source contract](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113136761)
received [Integrator conditional ACCEPT](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113269181).
The 2026-10-11 contract was design GO only. On 2026-10-12, exact
[#790 PR #796](https://github.com/LTstripes/hermes-finance/pull/796)
implemented the bounded typed source-owned proof and desktop review; **no real
Owner stock fee has been independently source-accepted**. Its exact merged
commit is `fee94e4fd4c77db3e50500a6fc3b6d103af2b498`; refer to
[post-main CI 38212066232](https://github.com/LTstripes/hermes-finance/actions/runs/38212066232)
for the final integration check.
The existing #783 path is exclusively a settled RUB **bond BUY** with
separate negative settlement, paid NKD and fee legs, and an explicitly reviewed
native total NKD inclusion basis. It cannot be reused for a stock commission
by supplying a synthetic zero NKD event.

The implemented two-leg stock variant must prove an existing settled RUB
**stock BUY** by provider + account + **ordered two native IDs**, one exact
negative settlement `S` and separately charged negative commission `F`
bound to the unique native primary. It requires an **independently established**
native fee-excluded `summ_trade=T`, matching source `bank_tax=B` and verified
`-S=T` / `-F=B` at exact kopecks. Merely matching these equations, matching
monthly cash or checking a generic confirmation is **not** proof of the
accounting convention. For the current real source that independent fee-basis
referent is still unaccepted: it may require one specific Owner-local evidence
reference; without it the execution's `commission_basis_unresolved` must remain.

The implementation follows accepted [#788](https://github.com/LTstripes/hermes-finance/issues/788)
and reuses the existing Money batch,
`ExecutedTradeRevision`, `ExecutedTradeOccurrence` and immutable receipts;
strictly discriminate a new typed stock proof from the bond three-leg proof.
The dedicated `stock_buy_separate_fee_v1` claims and Money commission seed
are validated separately from legacy three-leg bond proofs. Literal pre-change
coupon/H2/bond/zero-fee JSON fingerprints and receipts stay compatible;
stock fees deduplicate by provider/source account/ordered native execution IDs
and role, not by matching narrative/date/amount. A specific basis-reference
identifier is stored in the review context, but **cannot by itself establish
the broker's fee-exclusion convention**. An independent Owner-local source proof
is mandatory before real September acceptance.

There must be **two** cash roles and **no** paid-NKD role, extra CashBalance,
InvestmentCashFlow, H2, ExternalFlow, cost-basis or EOD accrual.
NULL accrued remains NULL, observed source zero stays observed zero.
Unknown fee inclusion, embedded/multiple fee, SELL, FX, REPO, pending,
native-primary ambiguity and contradictory receipt evidence remain BLOCKED.
Preview, Apply, canonical trade GET, broker-month GET and reserved Close must
consume the **same** proof, scoped per affected trade and source account.
[#787](https://github.com/LTstripes/hermes-finance/issues/787)
real-original Gate 0 remains BLOCKED until all its independently validated
source compatibility gates pass.

See the [11 October dated closeout](SESSION_CLOSEOUT_2026-10-11.md) for
source-specific sequencing without duplicating private Owner financial data.
