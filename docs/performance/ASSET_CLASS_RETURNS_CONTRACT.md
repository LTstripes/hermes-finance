# Asset-class returns — contract / evidence gate

Issue: #534. Parent: #528. Date: 2026-09-27.

**Status: CANDIDATE / independent financial-semantics review required.**

## Decision

**Verdict: BLOCK ON EVIDENCE for exact asset-class XIRR/TWRR for all requested classes: deposits, bonds, equities and gold.**

This is not a statement that Hermes lacks useful class analytics. It means the current persisted model cannot prove the class-specific historical scope and class-boundary cash/valuation evidence required to call a class return exact.

Phase A portfolio/account Performance is unaffected and should not wait for this contract.

Do not start #535/#540 as implementation from this candidate until an independent review and an explicit Owner/Integrator decision accept the prerequisites below.

## 1. Three different quantities must stay separate

1. **Asset-class return** — XIRR/TWRR for one economic class over an interval.
2. **Account return** — already supported portfolio/account Performance scope.
3. **#575 monthly monetary result** — cash income / realised result / unrealised snapshot result grouped by current `instrument_type`.

They are not interchangeable. A specialised brokerage account is not proof of the return of one asset class. #575 numbers are not rate-of-return inputs and must not be relabelled as XIRR/TWRR.

Current `PerformanceScope` is only `portfolio|account`; all production XIRR/TWRR/availability surfaces follow that boundary. Existing PERF04B explicitly leaves asset-class/instrument attribution unsupported because classification, flow allocation and complete historical component evidence are not authoritative.

## 2. Capability matrix

| Class | What is authoritative now | Why exact class return is blocked |
| --- | --- | --- |
| **Deposits** | Monthly `deposit_snapshots` hold exact balance and deposit/savings type per reporting month; deposits contribute to normal portfolio/account valuations. | No class-boundary contribution/withdrawal ledger proves principal moving into/out of the deposit class; no dated open/close/maturity transition contract; interest facts do not provide complete class-boundary flow history. Absence of rows cannot prove a flow-free interval. |
| **Bonds** | Monthly position snapshots have quantity, exact persisted market value/cost basis/unrealised result, NKD and price provenance. | Instrument type is read from the current `instruments` row, not effective-dated history; buys/sells are not a complete transaction ledger; coupon/redemption/fees/taxes do not by themselves prove class-boundary flows; sold/closed holdings disappear from active monthly positions. |
| **Equities** | Same position snapshot envelope as bonds; dividend/realised cash rows may exist. | Same non-historical class identity; no complete buy/sell/execution/lot path; realised rows are not complete class crossings; dividends leaving the holding class need explicit boundary semantics rather than being injected twice. |
| **Gold** | Gold can exist as a position with persisted manual/known price and market value. | Historical capital composition groups non-stock/non-bond positions into `gold_other`; current type is not dated; there is no complete purchase/sale/fee/FX class-boundary ledger and no class-specific Performance scope. |

### 2.1 Historical classification is a hard blocker

For instrument-backed classes, closed historical position snapshots join the **current** `Instrument.instrument_type`. Editing the current instrument type can therefore re-label earlier months without reopening them.

A future class-return contract must not let a present-day catalogue edit rewrite historical class membership.

At minimum, accepted evidence needs one of:

- immutable class identity persisted with each closed position snapshot; or
- an effective-dated class-membership table with gap/overlap checks; or
- another equally strong historical identity contract.

A migration must not silently infer an old class solely from today's instrument type and call it historically exact.

Deposits are different: `deposit_type` is stored per snapshot, but that still does not solve class-boundary cash evidence.

## 3. Class-boundary flows are not account/portfolio flows

A transaction can be internal to an account/portfolio but external to an asset class.

Examples:

- buying stock with brokerage cash: portfolio-internal, **class contribution** into equities;
- selling stock to brokerage cash: portfolio-internal, **class withdrawal** from equities;
- coupon/dividend paid from a security into account cash: economic return that exits the security class and needs one explicit class-boundary treatment;
- bond redemption: principal crossing the bond-class boundary must not be relabelled passive income;
- moving one holding from one class identity to another cannot be represented as a current-label edit.

The current canonical `ExternalFlow` is account/portfolio boundary evidence and has no instrument/class identity. Current `InvestmentCashFlow` rows are useful income/cost evidence but are not a complete trade or class-boundary ledger.

Therefore class XIRR/TWRR cannot be produced by:

- filtering portfolio/account flows by current instrument type;
- treating capital deltas as contributions/withdrawals;
- using current class weights to allocate unknown cash;
- treating coupons/dividends/redemptions twice;
- summing/averaging account XIRR/TWRR;
- using price change, YTM, coupon rate or #575 monetary result as total return.

## 4. Endpoint valuations are necessary but insufficient

Future class return needs exact opening and closing values for the selected class and a proof that every required component belongs to that class at those dates.

Existing snapshots can be part of that evidence **after** historical class identity is fixed.

A class valuation contract must also decide explicitly:

- whether account cash is outside every security class (recommended default for a bounded first design);
- how deposit balances enter the deposit class;
- how archived/sold positions remain part of historical evidence;
- whether all first version values are RUB-only;
- what happens to unknown/unclassified positions or cash.

Unknown/unclassified components stay unavailable; they are never allocated by weight.

## 5. Exact TWRR needs class-specific PRE/POST evidence

Current observed valuation boundaries are persisted only for portfolio/account scope.

Exact class TWRR with a class-boundary contribution/withdrawal needs observed class value immediately before and after each required boundary/group, or another accepted source that proves the equivalent exact subperiod inputs.

Monthly endpoint snapshots alone cannot prove intra-period class PRE/POST ordering.

Do not extend `ObservedValuationPoint` to an asset-class scope ad hoc inside #535. The class identity, target signature, grouping, correction/invalidation and closed-month lifecycle must be frozen first.

## 6. Required prerequisites before any GO

A future implementation may proceed only after these evidence slices are accepted.

### C1 — historical class identity

Freeze an immutable/effective-dated class key for every class-valued component.

Required:
- no retroactive rewrite of closed history from current catalogue edits;
- gap/overlap/unknown states;
- correction lifecycle and invalidation;
- synthetic class-change regressions.

### C2 — class-boundary event ledger / coverage

Provide explicit dated class crossings with exact amount/direction and provenance.

Must cover, where applicable:
- purchase / sale;
- deposit principal in/out;
- coupon / dividend distribution;
- redemption principal separately from income;
- class transfer / reclassification;
- fees/taxes with an accepted allocation rule;
- in-kind movement;
- explicit affirmative coverage, including a valid no-crossing interval.

A missing trade ledger cannot be replaced by owner attestation that only covers account-level external cash.

### C3 — class valuation service

Provide exact opening/closing class values with complete component coverage and historical class identity.

No current-weight backfill, no survivor-only composition and no partial-as-complete result.

### C4 — class PRE/POST boundary evidence for TWRR

Provide exact class-specific pre/post observations or an equally strong accepted transaction-aware valuation source for every class crossing that requires segmentation.

### C5 — currency / correction / lifecycle

First version may remain RUB-only. Any foreign-currency component without accepted dated conversion remains unavailable.

All material corrections must invalidate dependent class evidence; closed-month rules remain fail-closed.

## 7. Can a smaller exact subset ship first?

**Not from current evidence alone.**

Even a visually “flow-free” interval cannot be called exact because the current model cannot affirmatively prove that no buy/sell/class crossing occurred inside the interval.

A future bounded subset could become possible only after C1 plus an affirmative class-boundary coverage contract. Example: stable historical class identity + exact endpoints + explicit “no class crossings in this interval” evidence. That is a new evidence feature, not a free calculation over today's monthly snapshots.

This contract therefore does **not** grant a current PARTIAL GO.

## 8. Reference vectors for future prerequisites

These are availability/construction vectors. Existing portfolio/account numerical XIRR/TWRR solvers remain the numerical reference after a class input series is valid.

| Vector | Evidence | Required outcome |
| --- | --- | --- |
| R1 — current type edit | Closed Jan position historically classified bond; current catalogue later changed to stock | Jan history must remain bond or become unavailable pending historical classification repair. It must never silently move into equity return. |
| R2 — sold holding | Equity has opening value; no closing position row; no dated sale/class withdrawal evidence | Class return unavailable, not -100%, zero, or inferred sale proceeds. |
| R3 — in-account purchase | Brokerage cash buys equity mid-period; no account/portfolio ExternalFlow | Equity class requires a class contribution. Portfolio/account flow semantics cannot prove it. |
| R4 — coupon + redemption | Bond pays coupon and later principal | Coupon and redemption must have distinct accepted class-boundary semantics; principal is not passive income and no row is double-counted. |
| R5 — gold bucket | Current allocation reports a `gold_other` bucket containing gold and/or other liquid positions | No “gold return” may be produced from that mixed presentation bucket. |
| R6 — future positive control | Historical class identity exact; RUB opening 1000 on 2026-01-01, closing 1100 on 2027-01-01; explicit complete no-crossing coverage | Class input may reuse existing solver semantics; XIRR = +10% annualised and TWRR = +10% for the one-year flow-free interval. |
| R7 — unknown crossing | Exact endpoints but class-boundary coverage unknown | Both exact class metrics unavailable; endpoints alone do not prove return. |

## 9. Instrument-level drill-down

Do **not** add a table of individual instrument XIRR/TWRR in this milestone.

Instrument return requires at least the same trade/disposal/history evidence and generally stricter identity/cost/flow provenance. Existing monthly price/value facts may support a future informational price/value history, but that must not be labelled total return.

If instrument returns are revisited, use on-demand drill-down from a supported class/holding page, not a permanently expanded table.

## 10. Product sequencing

Recommended sequence:

1. finish Phase A portfolio/account UX (#529–#533 / #541 A);
2. keep #575 monthly monetary result as the useful class-style breakdown already supported by current evidence;
3. leave #535/#540 blocked;
4. only create C1–C5 implementation issues if the Owner explicitly chooses to invest in exact class-return evidence.

This keeps the new Performance UI useful without turning an interface task into an unplanned transaction-ledger rewrite.

## 11. Review / completion

This candidate changes documentation only.

Independent financial-semantics review must verify:
- historical-classification reasoning;
- class-boundary flow semantics;
- no conflict with PERF04A/B, #575 or existing account/portfolio returns;
- prerequisite sufficiency and whether any smaller exact subset is actually supportable.

No production code/schema/API/provider call or Owner data is changed by this contract candidate.
