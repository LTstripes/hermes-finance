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
canonical revisions when relevant. Read blocking does not mutate CLOSED months,
coverage claims or endpoint facts, and source-only append-only promotion does
not authorize financial correction through CLOSED history.

Coverage remains `unknown`. No ReportingMonth, PositionSnapshot, CashBalance,
InvestmentCashFlow, ExternalFlow, payout, transfer or UFSR fact is created or
changed. No return consumer, historical reconstruction, realized P&L or bond
arithmetic is enabled. S2-B reconciliation/correction/retraction, #709 backfill,
financial/data candidate review and Integrator acceptance remain separate.
