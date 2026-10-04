# Asset-class returns — contract / evidence gate

Issue: #534. Historical parent: #528. Original decision: 2026-09-27; accepted amendment and Phase 1 delivery: 2026-10-04.

**Status: ACCEPTED.** Original BLOCK ON EVIDENCE independently accepted 2026-09-27 (#534 comment 5855432534). Owner accepted metric-specific sequencing on 2026-10-04; the bounded Phase 1 capability below is now integrated. This is not blanket support for all classes/histories.

## Decision

**Original baseline verdict (2026-09-27): BLOCK ON EVIDENCE for exact asset-class XIRR/TWRR for all requested classes: deposits, bonds, equities and gold.**

That decision described the evidence then available. It did not deny useful existing class analytics; the baseline could not prove the historical class scope and boundary cash/valuation evidence required for exact class returns. The original prohibition still applies to unsupported histories, but must not be read as a current global block after Phase 1 delivery.

Phase A portfolio/account Performance is unaffected.

## 0. Accepted 2026-10-04 sequencing amendment

The original evidence conclusion remains valid for its baseline. The amendment changes sequencing, not financial precision.

| Prerequisite | Exact class XIRR | Exact class TWRR |
| --- | --- | --- |
| C1 — historical class identity | Required for endpoint membership and relevant events | Required at endpoints and valuation boundaries |
| C2 — class-boundary events / coverage | Complete dated crossings **or affirmative no-crossing coverage** | Required with sufficient ordering/grouping |
| C3 — class valuation | Exact opening and closing values suffice | Endpoints plus exact class values at segmentation boundaries |
| C4 — class PRE/POST evidence | **Not required** | Required when crossings require segmentation; vacuous for a proven no-crossing interval |
| C5 — currency / corrections / lifecycle | Required; bounded RUB first capability permitted | Required, including invalidation of dependent observations |

Historical class identity + affirmative whole-interval no-crossing coverage + exact complete endpoint valuations + C5 permit both metrics without invented PRE/POST observations.

Transaction-lot/FIFO/average-cost reconstruction is **not** a prerequisite. Return inputs require complete boundary amounts, historical membership and valid valuations; tax-lot accounting is a separate problem.

Historical statements are the preferred durable automation route. A documented provider API may later supply equivalent evidence, but class returns must not depend on undocumented Alfa PRO token/handshake behaviour. Routine trades should be imported/normalised; Owner input is for mappings, ambiguity, unsupported off-platform facts and narrowly defined attestations.

Solver availability is separate from evidence availability. Current XIRR deliberately returns `not_computable_xirr_root_ambiguity` for more than one sign variation in the normalised dated series before root scanning. Complete evidence can therefore be solver-unsupported. UI/API must not describe numerical limitations as missing transactions.

Do not infer class rates from allocation, account returns or monetary-result grouping. Only explicitly accepted class/interval/evidence capabilities may calculate; unsupported cases remain unavailable.

### 0.1 Delivered Phase 1 capability

#696/#697 (C1), #698/#699 (C2/C3/C5), #535/#700 (API) and #540/#701 (UI) are integrated. Code milestone: `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4`; canonical CI `37226437369` SUCCESS. This development wave is not in published v1.2.0. Owner UAT remains pending.

- Whole-portfolio historical Performance universe, RUB `stock`, `bond`, `gold` only.
- Persisted snapshot C1 identity; legacy NULL stays unknown, no current-type fallback.
- Explicit Owner no-crossing assertion **and separate opening/closing whole-class inventory claims** at exact dates over all historically included accounts. A position footprint or successful selected import is not completeness proof.
- Persisted RUB `market_value_kopecks` is the accepted endpoint basis, retaining existing accrued-interest semantics; mutable current `Instrument.currency` is not historical currency evidence. This is not a new FX/conversion path.
- Revision/CLOSED/Reopen/correction/material invalidation stays fail-closed.
- Existing XIRR receives negative opening and positive closing only; existing TWRR receives endpoints with no boundaries. Metric availability remains independent.

Canonical implementation contracts: [historical identity](POSITION_CLASS_IDENTITY.md), [no-crossing and endpoint evidence](CLASS_NO_CROSSING_ENDPOINTS.md), [class return API](CLASS_RETURNS_API.md).

Deposits, statement-backed crossings, flow-bearing TWRR, FX and Owner-facing class-attestation entry are not delivered. The class screen is read-only; legacy evidence may remain unavailable. Backend/UI completion is not a universal personal-history return claim.

## 1. Three different quantities must stay separate

1. **Asset-class return** — XIRR/TWRR for one economic class over an interval.
2. **Account return** — existing portfolio/account Performance scope.
3. **#575 monthly monetary result** — cash income / realised result / unrealised snapshot grouped by current `instrument_type`.

They are not interchangeable. A specialised brokerage account does not prove class return. #575 numbers are not return inputs and must not be relabelled XIRR/TWRR.

`PerformanceScope` remains `portfolio|account` for the existing routes. #535 adds a separate bounded class-return API without changing that enum. PERF04B class/instrument additive attribution remains separately unsupported; Phase 1 rates do not implement it.

## 2. Capability matrix

This table retains the **original 2026-09-27 evidence inventory**, not current delivery status. Section 0.1 and the linked implementation contracts govern the delivered first subset.

| Class | Original authoritative evidence | Original blockers |
| --- | --- | --- |
| Deposits | Exact monthly deposit/savings balances; participation in portfolio/account valuations | No complete class-boundary principal history or dated opening/maturity transition contract; interest/empty rows do not prove no crossings |
| Bonds | Monthly quantities, persisted market value/cost/unrealised result, NKD and price provenance | Current catalogue type was not historical identity; buys/sells and coupon/redemption/fee facts did not form complete class history; missing holdings could not imply sale/zero |
| Equities | Same position envelope; dividend/realised cash facts could exist | No historical class or complete execution/class-crossing history; distribution needed explicit boundary treatment, without duplication |
| Gold | Position with persisted manual/known price and market value | Mixed `gold_other` presentation was not gold identity; no complete historical purchase/sale/fee/FX class ledger |

### 2.1 Historical classification is a hard blocker

The original baseline could relabel old position groupings via today's `Instrument.instrument_type`. #696 now provides persisted `historical_instrument_type` for the class-return path. Present-day catalogue edits must not rewrite it; legacy rows without evidence remain NULL/unavailable.

The governing requirement remains immutable snapshot identity, effective-dated membership with gap/overlap checks, or an equally strong accepted historical contract. A migration must never manufacture historical certainty from today's catalogue. Existing legacy analytics are not silently redefined by this new return surface.

Deposits already store `deposit_type` per snapshot, but that does not solve class-boundary cash evidence.

## 3. Class-boundary flows are not account/portfolio flows

A transaction can be internal to an account/portfolio but external to an asset class:

- Brokerage cash buying stock is a class contribution into equities.
- Selling stock into brokerage cash is a class withdrawal.
- Coupon/dividend into account cash is return leaving the security class and needs one accepted boundary treatment.
- Redemption principal crosses the bond-class boundary but is not passive income.
- Class reclassification cannot be modelled as a present-day label edit.

Canonical `ExternalFlow` is portfolio/account boundary evidence without class/instrument identity. `InvestmentCashFlow` contains useful income/cost facts, not a complete trade ledger. Phase 1 uses relevant facts as contradictions, not completeness proof.

Never derive class returns by filtering portfolio flows by current type, inferring flows from capital deltas, allocating unknown cash by current weights, counting distributions/principal twice, averaging/summing account returns, or substituting price change/YTM/coupon rate/#575 result for total return.

## 4. Endpoint valuations are necessary but insufficient

Exact class endpoints need every required component's historical identity and explicit completeness. #698 supplies this for the bounded Phase 1 contract, including both whole-class inventory claims. A single persisted position or other-class footprint does not establish complete requested-class inventory.

Settlement cash is outside the Phase 1 security classes. Deposits remain unsupported. Archived/sold/disappeared/quantity-changing holdings fail closed unless existing accepted same-class internal-transfer evidence exactly reconciles them. Values are persisted RUB endpoints, not today's quotes. Unknown/unclassified components are not allocated by weight.

These rules do not independently enable flow-bearing histories; those still require their own complete event/coverage contract.

## 5. Exact TWRR needs class-specific PRE/POST evidence

Current observed boundaries remain portfolio/account-scoped. Exact class TWRR with crossings requires actual class values before/after each required boundary/group or an accepted equivalent proving exact subperiod inputs. Monthly snapshots alone do not prove intra-period ordering.

Do not extend `ObservedValuationPoint` ad hoc inside the thin return adapter. Class identity, target binding, grouping and correction/CLOSED lifecycle must be frozen first. C4 is vacuous only for the affirmatively proven no-crossing path.

## 6. Evidence prerequisites

These are canonical capabilities, not a global all-or-nothing gate. Each metric/class/interval needs the prerequisites applicable to that capability.

### C1 — historical class identity

Immutable/effective class key for class-valued components; no current-catalogue rewrite, explicit unknown/gap/overlap states, correction invalidation and synthetic class-change regressions. The snapshot-scoped Phase 1 implementation is #696.

### C2 — class-boundary event ledger / coverage

Explicit dated class crossings with exact amount/direction/provenance, or accepted affirmative no-crossing coverage. Where applicable, cover purchases/sales, deposit principal, distributions, redemption principal separately from income, reclassification, attributable fees/taxes and in-kind movements.

Account-level external-cash attestation is not class-boundary completeness. Net-zero crossings are still crossings. Phase 1 #698 is an Owner-attested no-crossing path, not statement-verified execution history.

### C3 — class valuation

Exact opening/closing values with whole-class component coverage and historical identity. XIRR does not require a general daily valuation service; crossing TWRR additionally needs exact segmentation-boundary values. No current-weight backfill, survivor-only composition or partial-as-complete result.

### C4 — class PRE/POST boundary evidence for TWRR

Exact class-specific observations or an equally strong accepted transaction-aware valuation source for every crossing requiring segmentation. Not required for XIRR; vacuous for proven no-crossing intervals.

### C5 — currency / correction / lifecycle

Phase 1 consumes accepted already-RUB persisted PositionSnapshot values, not current catalogue currency or guessed conversion. Non-RUB application base currency is unsupported. A future foreign-amount path requires its own authoritative dated valuation/conversion evidence.

Material corrections invalidate dependent evidence; CLOSED rules stay fail-closed. No broadened FX architecture is implied.

## 7. Smaller exact subset

Snapshots, an empty query or an apparently flat holding chart alone never establish no crossings. The implemented first subset requires C1, affirmative C2 no-crossing, exact complete C3 endpoints and bounded C5. With all present, existing XIRR and no-boundary TWRR may run without C4.

No-crossing includes no purchases/sales, class reclassification, distributions leaving the class, redemption/maturity principal, attributable boundary fees/taxes or external in-kind movements. A fully reconciled same-class transfer entirely within continuously included accounts is not itself a portfolio-wide class crossing. Unknown/contradictory facts defeat the assertion; they do not become guessed events.

## 8. Reference vectors for future prerequisites

These remain construction/availability vectors; the existing numerical solvers govern rates after evidence is valid.

| Vector | Evidence | Required outcome |
| --- | --- | --- |
| R1 — current type edit | Closed historical bond, catalogue later stock | Persisted historical bond or legacy unknown; never silently equity |
| R2 — sold holding | Opening holding, missing closing row, no withdrawal proof | Unavailable, not -100%, zero or inferred proceeds |
| R3 — in-account purchase | Cash buys equity without portfolio ExternalFlow | Requires equity class contribution evidence |
| R4 — coupon + redemption | Income and principal paid separately | Distinct accepted treatment; no passive-income principal or double counting |
| R5 — gold bucket | Mixed `gold_other` allocation | Not a gold-return input |
| R6 — positive control | Exact historical identity, complete endpoint inventories, RUB 1000 to 1100 over 365 days, affirmative no-crossing | Existing solvers support approximately +10% annualized XIRR and +10% period TWRR |
| R7 — unknown crossing | Exact endpoints but unknown class coverage | Both class metrics unavailable |

## 9. Instrument-level drill-down

Do not add individual instrument XIRR/TWRR in this milestone. It needs at least the same trade/disposal/history evidence and more specific identity/flow provenance. Informational price/value history must not be called total return. A future instrument-return surface should be on-demand, not a permanently expanded all-instruments table.

## 10. Product sequencing

Phase A portfolio/account UX is complete. Phase B's accepted first capability is delivered:

1. **Phase 1A / #696 — COMPLETE:** historical class identity.
2. **Phase 1B / #698 — COMPLETE:** no-crossing and both endpoint inventory claims, exact RUB valuations and lifecycle.
3. **Phase 1C / #535 — COMPLETE:** bounded read-only class XIRR/TWRR API.
4. **Phase 1D / #540 — COMPLETE:** read-only class table and independent evidence/numerical states.
5. **Phase 2 / #702 — research selected:** source/coverage matrix and proposed minimal statement-backed class XIRR with crossings, one report family at a time. No implementation is authorized by the research report alone. Owner evidence-entry/legacy repair gaps must be addressed in the product path, not hidden as manual database work.
6. **Later:** flow-bearing exact class TWRR with C4/equivalent evidence; other classes/currencies/corporate actions need separately accepted contracts.

#575 remains monetary-result analytics, never a class-rate input. Alfa PRO is optional and must not block durable statement-backed history.

## 11. Review / completion

The original #534 block and October amendment are accepted. Phase 1 implementations passed independent reviews and exact-candidate/exact-main CI; detailed history is in [the session closeout](../SESSION_CLOSEOUT_2026-10-04.md). Real-history Owner UAT is pending. Neither publication of v1.2.0 nor synthetic success proves personal-data availability.

Future schema/import/evidence changes stay separately bounded. Existing portfolio/account semantics, no inferred trades/flows, no current-weight allocation, no P&L/YTM substitution, no incomplete-class promotion and honest solver reasons remain invariant. New capabilities require independent financial/data review and the applicable Owner gate.
