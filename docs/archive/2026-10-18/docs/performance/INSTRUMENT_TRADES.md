# Known executions and cash-leg evidence

Bounded read-only [#862](https://github.com/LTstripes/hermes-finance/issues/862)
slice, based on canonical main `8faa8fb9940dc03a13b674ec6e5100389d103d99` after
[#860 exact post-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/39020641994)
completed successfully.

`GET /api/instruments/{instrument_id}/known-trades?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one brokerage/IIS account, one historical instrument and explicit `(t0,t1]`.
It uses one query-only committed snapshot for source union, canonical executions,
revisions, mappings, receipts, Money ownership and currentness. Invalid interval
is 422, missing references 404, other HTTP methods 405. There is no writer/schema,
provider request, Apply/Close, cash-flow creation or new ledger.

Canonical `ExecutedTrade.source_identity` owns event identity. The existing
`executed_trades._context` / `_read` revalidate the accepted revision against native
sources/dispositions/corrections. Ordered native IDs remain separate. Overlapping
originals and repeated occurrences corroborate one canonical trade; distinct ID
pairs remain separate even with equal dates and amounts. Only exact account and
instrument rows enter the response. Inactive/exited instruments remain selectable.

`observed_native_execution` is distinct from `effective_cash_leg_authority`.
The former exposes signed Decimal quantity, BUY/SELL from native quantity sign,
native IDs, revision, lifecycle, separately observed execution/settlement/depository
dates, source occurrences and conflict reasons. It confers no cash authority.
Conflicted observations remain labelled unavailable currentness. Missing date/side
has NULL and a reason; a pending planned date is explicitly separate from actual.
Selection uses the union of execution, actual/planned settlement and source cash
dates, retaining boundary crossings and not treating a date outside `(t0,t1]` as
part of that date's interval. Frozen and current candidate settlement dates both
retain an unresolved crossing for review.

Accepted cash uses only existing `broker_trade_money.effective_proof` and its
Money ownership/retirement/currentness guards plus the current canonical revision.
Stock BUY supports settlement and nonzero separately reviewed commission; bond
BUY supports settlement, paid NKD and commission from the existing three-leg
independently reviewed basis. Each role has signed exact RUB and kopeck strings,
effective date/interval placement, basis, Money receipt and source occurrence
identifiers. Unsupported/ineffective/missing proof gives NULL values and explicit
reasons; no raw Money date/amount matching, SELL proceeds, inferred zero NKD/fee/tax,
cost allocation or accepted cash total is introduced. No financial amount is
summed across roles or combined with payouts/EOD values.

Historical RUB identity reuses accepted native SOURCE identity and exact mappings,
including prior observations of an exited holding. A SOURCE receipt from a later
reporting interval cannot establish an earlier execution's identity. A genuinely
effective, exact native/source-bound Money stock/bond BUY proof can supply its
existing narrow exact-RUB type link, including a prior-month execution with later
cash settlement; without that proof the identity remains NULL.

`known_count` is the canonical count within this bounded response, never full
history. A 250-event cap returns `capacity_exceeded`, no list and NULL count,
without silent truncation. Source gaps, unsupported/unparsed sections and
unaccepted native executions remain explicit markers. Empty inventory does not
prove absence of trades. `trade_history_completeness` and `financial_coverage`
are always `unknown`; endpoint quantities, flat EOD values and payout observations
do not change that.

`dependency_digest` describes only the current snapshot: exact scope, scoped
retained sources, account receipts, executions/revisions/occurrences, Money owners,
correction/disposition history and retained absence reasons. It contains no source
text in API/UI/logs and is **not** a reusable currentness token. Existing journals
do not completely protect the S2-only inventory/absence set against every ABA;
therefore `dependency_fingerprint=NULL` and token `currentness=unavailable` always.
Individual current source/proof checks still occur on each GET. No synthetic token
substitutes for the missing journal and no new journal writer is added.

The on-demand Capital → Performance instrument selector reads this independent
section beside #858 payouts / #860 EOD. They may have separate response snapshots;
no joined rate or result is computed. New request generations, exact outer/event
scope validation, selector invalidation and hidden results during errors/refresh
prevent a late account/instrument/date response appearing as current selection.

Focused evidence belongs to `test_instrument_trades_service.py`,
`InstrumentTrades.test.tsx` and the existing payout/EOD regressions. Disposable
source-backed desktop journey, production dist at 1440 and 1280 with 125% zoom:

```text
npm run build
npm run test:e2e -- --config=playwright.instrument-trades.config.ts
```

The fixtures/DB/screenshots are synthetic. They do not replace Owner-real UAT.
Full instrument P&L/RUB/%/XIRR/TWRR, #814 settlement/NKD evidence, #774 S3,
#839 WHAT-IF, #856 export, Owner DB and Stable remain outside this slice.
