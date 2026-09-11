# PERF-04P2 — Attribution numerical models and reference vectors

> **Status:** research/discovery only; advisory evidence, not an accepted financial contract.
> **Issue:** [#348](https://github.com/LTstripes/hermes-finance/issues/348)
> **Baseline:** `858d64c4c6777c33cf21201095240536d258db7c`

This note studies candidate attribution/decomposition models against the
accepted Hermes performance boundaries. It deliberately does **not** choose a
normative PERF-04 method and does not add production code, schema, migrations,
API, UI, or tests.

All numbers below are synthetic, hand-checkable examples. Amounts are RUB with
exact two-decimal notation; persistence would represent them as integer
kopecks. No price, trade, cost basis, cash-in-transit, provider, or owner data
is implied. A percentage written as a fraction is exact; a displayed decimal
percentage is exact only where the fraction terminates.

## 1. Contract boundary and notation

The accepted R08 contracts remain the source of truth:

- `reporting_months.snapshot_date` and closed monthly component snapshots are
  historical valuation evidence, not a license to interpolate between dates.
- `ExternalFlow` is the only external-flow input. At portfolio scope, a proven
  in-scope transfer is internal; at account scope, its two legs cross the
  account boundary.
- Contributions are positive selected-scope capital entering the portfolio;
  withdrawals are negative. In the investor-perspective XIRR cash-flow series
  their signs are reversed, so XIRR must not be reused as additive attribution.
- Coupons, dividends, redemptions, fees, taxes, and retained deposit interest
  already inside the selected scope are internal events. They must not be
  injected a second time into total-return math. Redemption is principal, not
  passive income.
- Exact TWRR requires observed pre/post valuation evidence at every selected
  external-flow boundary. Missing, unordered, or unvalued evidence is
  unavailable, never zero and never estimated.

Notation used in the vectors:

| Symbol | Meaning |
| --- | --- |
| `V0`, `V1` | opening and closing selected-scope valuations |
| `C` | signed selected-scope external contribution (`+`) or withdrawal (`-`) |
| `V−`, `V+` | observed value immediately before/after one flow or flow group |
| `D` | flow-adjusted denominator, `V− + C` |
| `f` | one subperiod factor, `V+ / D` |
| `T` | chained TWRR, `product(f) - 1` |
| `I` | retained passive-income event, only when evidenced and in scope |
| `K` | internal cost, represented as a negative amount in a value bridge |

For a value bridge, the useful identity is:

```text
V1 - V0 - sum(C) = market/capital result + retained income + internal cost
```

The right-hand categories must be mutually exclusive and completely evidenced
before they can be reported. This identity is a value change, not a TWRR and
not an XIRR.

## 2. Candidate methods

### 2.1 Exact value-change bridge: strongest for explanation, not return

**Parent quantity.** Closing value minus opening value after signed external
flows. The bridge can separately show retained income, internal fees/taxes and
a residual market/capital result.

**Formula and assumptions.** For a period with complete event classification:

```text
bridge_result = V1 - V0 - sum(C)
market_or_capital = bridge_result - income - internal_cost
```

`income` must exclude redemption principal. `internal_cost` is negative. A
direct outside-scope payout uses the proven net boundary amount; its income
evidence is not added again. The bridge requires component totals and event
identity to cover the same scope and dates.

**Evidence status.** Hermes has monthly position/deposit/cash components and
typed investment cash-flow evidence, but legacy rows do not automatically prove
an external boundary. The accepted contracts also defer transaction/cost-basis
realised-vs-unrealised attribution. Therefore this bridge is viable only for a
bounded, fully evidenced interval; it cannot manufacture missing trade-time or
intra-period values.

**Additivity and rounding.** Dollar bridge terms are additive by construction.
Use integer kopecks or exact `Decimal` arithmetic; round only a presentation
column after the exact residual is calculated. A residual kopeck must not be
silently assigned to an instrument.

**Unavailable cases.** Missing scope component, unknown external-flow coverage,
ambiguous tax/fee identity, missing direct-payout proof, missing currency
conversion, or an unexplained composition change. Estimating a residual from a
capital delta would violate the accepted fail-closed boundary.

### 2.2 Boundary-aware linked TWRR attribution: strongest return candidate

**Parent quantity.** Exact selected-scope TWRR. For each observed subperiod:

```text
D_j = V−_j + C_j
f_j = V+_j / D_j
TWRR = product(f_j) - 1
```

For component `i`, if complete pre/post values and flow allocation exist, let
`g_ij = V+_ij - V−_ij - C_ij`. A simple linked contribution in percentage
points is:

```text
q_ij = g_ij / D_j
linked_i = sum(q_ij * product(f_k for k > j))
```

The exact sum property holds only if, for every subperiod, component coverage
is complete and `sum(g_ij) = V+_j - V−_j - C_j`. The weighting convention is
therefore explicit: each component's dollar result is divided by the selected
scope's flow-adjusted denominator, then linked through later subperiod factors.
Other linking conventions (for example Carino-style logarithmic linking) are
possible candidates, not a decision made here.

**Evidence status.** Current Hermes evidence supports exact scope/account
monthly values and explicit scope-level observed flow boundaries. It does not
by itself establish component-level pre/post values, component flow allocation,
or trade-time composition membership for every attribution row. Those missing
facts are blockers, not inputs to be inferred.

**Additivity and rounding.** With exact component coverage, linked percentage
point contributions sum to the portfolio TWRR before display rounding. Keep
exact factors and contributions at full precision; round the final displayed
rows with a documented policy. If a rounded table no longer sums, show an
explicit residual rather than altering one component.

**Unavailable cases.** Any missing or unordered external boundary, unknown
cash/in-kind coverage, unresolved transfer, missing membership, unvalued
transfer transit, or missing component-level evidence. No monthly-start/end
assumption or interpolation repairs such a gap.

### 2.3 Modified Dietz: useful comparison, not exact PERF-04 return

**Parent quantity.** A cash-flow-adjusted period return, not exact TWRR:

```text
r_MD = (V1 - V0 - sum(C_j)) / (V0 + sum(w_j * C_j))
```

`w_j` is a declared time-in-period weight for flow `j`; for example, a flow
exactly halfway through a synthetic interval might use `w = 0.5`. The date
convention, treatment of same-day flows, and negative denominator policy are
part of the method.

**Evidence status.** The required intra-period timing and valuation assumptions
are not an accepted Hermes exact-performance fallback. The performance roadmap
explicitly defers approximate/Modified-Dietz return.

**Additivity and rounding.** The numerator is additive in dollars, but the
percentage is not additive across components unless all rows share the same
explicit denominator. Different `w_j` or rounding choices change the result.

**Unavailable cases.** Missing exact flow dates, invalid/negative denominator,
unknown external-flow completeness, or a request for exact TWRR semantics.
Returning a Dietz estimate with an `exact` label would be a normative contract
change.

### 2.4 Brinson-Fachler / BHB: benchmark-relative attribution

**Parent quantity.** Active return relative to a benchmark, not absolute Hermes
portfolio return. A common arithmetic form is:

```text
allocation_i = (wP_i - wB_i) * rB_i
selection_i  = wB_i * (rP_i - rB_i)
interaction_i = (wP_i - wB_i) * (rP_i - rB_i)
active_return = sum(allocation_i + selection_i + interaction_i)
```

Other Brinson variants use different interaction placement. Selecting one is a
normative methodology decision.

**Evidence status.** Current accepted Hermes performance evidence does not
provide a canonical benchmark, benchmark weights/returns, instrument taxonomy,
or benchmark currency/valuation contract. These would be invented for current
data.

**Additivity and rounding.** Terms are additive to active return under one
declared variant and exact common weights. They do not reconcile to absolute
TWRR unless a separate benchmark contract is supplied.

**Unavailable cases.** Missing benchmark series, classifications, comparable
weights, or complete subperiod observations. Never substitute a risk-free rate,
an index chosen ad hoc, or current instrument labels.

### 2.5 Shapley/Owen counterfactual attribution: mathematically fair, data-heavy

**Parent quantity.** Any explicitly chosen scalar metric `M`, such as a linked
TWRR or value bridge, evaluated for every relevant component coalition. For
component `i`, Shapley contribution is:

```text
phi_i = sum over S not containing i of
        (|S|! * (n-|S|-1)! / n!) * (M(S union {i}) - M(S))
```

The contributions add to `M(all) - M(empty)` only when every counterfactual is
well-defined on the same dates, flows, scope and valuation rules. Owen values
add a declared group hierarchy but add another grouping assumption.

**Evidence status.** Hermes cannot derive a counterfactual portfolio valuation
for an omitted instrument, omitted flow, or changed composition without
inventing prices or event allocation. This is a research candidate for a future
contract, not a current computation.

**Additivity and rounding.** Additive after all coalition metrics are exact;
interaction is allocated by the selected permutation/group rule. Results are
method-dependent and can change when the component set changes. Exact
kopeck/Decimal calculations are required before any display rounding.

**Unavailable cases.** Any missing coalition valuation, missing flow allocation,
unresolved transfer, or metric that is itself unavailable. A counterfactual is
not permission to estimate a missing observed value.

### 2.6 XIRR: parent metric only, never additive attribution

XIRR solves the investor-perspective dated cash-flow equation:

```text
sum(CF_j / (1 + r)^((date_j - date_0) / 365)) = 0
```

It is money-weighted and nonlinear. A component's XIRR is not an additive
piece of portfolio XIRR, and an XIRR percentage cannot be relabelled as an
income, price, account, or instrument contribution. XIRR may remain available
when TWRR boundary ordering is unavailable; that distinction must be preserved.

## 3. Synthetic reference vectors

### Vector 1 — no-flow split across two accounts/instruments

| Component | Opening | Closing | Gain | Opening weight | Return contribution |
| --- | ---: | ---: | ---: | ---: | ---: |
| Account A / Instrument X | 600.00 | 720.00 | 120.00 | 0.60 | `0.60 × 20% = 12%` |
| Account B / Instrument Y | 400.00 | 440.00 | 40.00 | 0.40 | `0.40 × 10% = 4%` |
| **Portfolio** | **1,000.00** | **1,160.00** | **160.00** | **1.00** | **16%** |

There is no external flow, so `TWRR = 1,160 / 1,000 - 1 = 16%`. The exact
opening-weight contributions are `12% + 4% = 16%`. This is a clean baseline
for a no-flow linked attribution; it does not prove that the same weighting
works after flows or composition changes.

### Vector 2 — contribution and withdrawal require boundary segmentation

| Boundary | Observed value | Signed external flow | Factor |
| --- | ---: | ---: | ---: |
| Opening | 1,000.00 | — | — |
| Before contribution | 1,100.00 | — | `1,100 / 1,000 = 1.10` |
| After contribution | 1,200.00 | `+100.00` | `1,200 / (1,100 + 100) = 1.00` |
| Before withdrawal | 1,320.00 | — | `1,320 / 1,200 = 1.10` |
| After withdrawal | 1,270.00 | `-50.00` | `1,270 / (1,320 - 50) = 1.00` |
| Closing | 1,333.50 | — | `1,333.50 / 1,270 = 1.05` |

The chained factor is `1.10 × 1.00 × 1.10 × 1.00 × 1.05 = 1.2705`, hence
`TWRR = 27.05%`. The `+100.00` and `-50.00` are capital movements, not
attribution gains. If the contribution is not evidenced at component level,
its split among accounts/instruments is unavailable rather than guessed.

### Vector 3 — internal transfer A -> B

| State | Account A | Account B | Portfolio total |
| --- | ---: | ---: | ---: |
| Before transfer | 600.00 | 400.00 | 1,000.00 |
| After internal transfer `200.00` | 400.00 | 600.00 | 1,000.00 |
| Closing after 10% growth in each account | 440.00 | 660.00 | 1,100.00 |

At portfolio scope, the transfer is `C = 0` and `TWRR = 1,100 / 1,000 - 1
= 10%`. At account scope, A has a `-200.00` withdrawal and B a `+200.00`
contribution: `440 / (600 - 200) - 1 = 10%` and `660 / (400 + 200) - 1
= 10%`. The transfer itself contributes zero to the portfolio result. If the
legs settle on different dates and required valuation falls inside unvalued
transit, the exact metric is unavailable; no cash-in-transit line may be
invented.

### Vector 4 — retained coupon versus direct outside-scope payout

**Retained in scope.** Start with total `1,000.00`. A proven coupon of
`20.00` is retained in selected-scope cash, with no external flow, and the
closing total is `1,020.00`. Therefore `TWRR = 1,020 / 1,000 - 1 = 2%`,
`I = +20.00`, and no separate `+20.00` external flow is added.

**Paid outside scope.** A separate synthetic event has gross dividend `20.00`,
outside withholding `2.60`, and net payment `17.40` to the owner:

```text
20.00 - 2.60 = 17.40
```

The proven boundary amount is the net `17.40` withdrawal. Gross income
evidence remains an explanation and is not injected again into XIRR/TWRR;
`2.60` is not a second in-scope tax event. If the required observed pre/post
valuation boundary is absent, exact TWRR is unavailable even though the
payment arithmetic is exact. Expected/provider calendar evidence alone does
not prove the realised payout.

### Vector 5 — redemption remains principal, not passive income

| State/event | Position value | In-scope cash | Selected total |
| --- | ---: | ---: | ---: |
| Opening | 500.00 | 0.00 | 500.00 |
| Principal redemption | 400.00 | 100.00 | 500.00 |
| Closing | 400.00 | 100.00 | 500.00 |

The redemption reclassifies `100.00` from position to in-scope cash. There is
no external flow and `TWRR = 0%`; passive income is `0.00`, not `100.00`.
The amount belongs in principal/cash-flow explanation, not in the income
attribution bucket.

### Vector 6 — internal fee/tax cost versus owner boundary

**Standalone internal cost.** Opening total `1,000.00`, an evidenced in-scope
fee is `13.00`, and closing total is `987.00`:

```text
bridge_result = 987.00 - 1,000.00 - 0.00 = -13.00
TWRR = 987.00 / 1,000.00 - 1 = -1.30%
```

The fee is `K = -13.00`, not an owner withdrawal.

**Owner payment with withholding.** A synthetic scope debit of `100.00` pays
`87.00` outside scope and remits `13.00` as an in-scope tax:

```text
100.00 = 87.00 external withdrawal + 13.00 internal tax cost
```

The external boundary is `-87.00`; no synthetic `-100.00` boundary is valid.
Without transaction-specific evidence linking gross, tax and net, the
classification is unavailable rather than inferred from a field name.

### Vector 7 — changing instrument weights/composition

| State | Instrument A | Instrument B | Instrument C | Total |
| --- | ---: | ---: | ---: | ---: |
| Opening | 800.00 | 200.00 | 0.00 | 1,000.00 |
| Observed rebalance: A -> C `300.00` | 500.00 | 200.00 | 300.00 | 1,000.00 |
| Closing | 550.00 | 190.00 | 330.00 | 1,070.00 |

Assume the rebalance is an internal same-scope trade at an observed value, not
an owner flow. The pre-rebalance segment is flat. In the post-rebalance
segment the exact component gains are `+50.00`, `-10.00`, and `+30.00`, summing
to `+70.00`; the segment and whole-period TWRR are `1,070 / 1,000 - 1 = 7%`.
The new instrument C has no opening weight, so a whole-period opening-weight
attribution for C is undefined. A future component attribution needs an
observed trade/rebalance boundary and a declared treatment of the `300.00`
composition transfer. If that observation is missing, report the component
split as unavailable while preserving any separately valid portfolio metric.

### Vector 8 — missing intra-period valuation gives multiple valid answers

Observed evidence is only:

```text
opening V0 = 1,000.00
contribution C = +200.00 on an interior date
closing V1 = 1,300.00
```

Two unobserved paths satisfy exactly the same endpoints and flow:

| Path | Before flow `V−` | After flow `V+` | Chained factor | TWRR |
| --- | ---: | ---: | ---: | ---: |
| A | 1,000.00 | 1,200.00 | `1,300 / 1,200 = 13/12` | `1/12 = 8 1/3%` |
| B | 1,100.00 | 1,300.00 | `(1,100/1,000) × (1,300/1,300) = 11/10` | `10%` |

Because `8 1/3%` and `10%` are both compatible with the captured evidence,
the exact TWRR and any flow-adjacent component attribution are
`not_computable_valuation_boundary_missing`. An estimate, interpolated price,
or start/end-of-day convention would select a normative answer without
evidence.

## 4. Cross-case findings

### Strongest viable candidates

1. **Exact value bridge** is the most immediately explainable candidate when
   the requested parent is value change/income/cost and every event category is
   explicitly evidenced. It should remain distinct from return metrics.
2. **Boundary-aware linked TWRR attribution** is the strongest candidate for a
   future absolute performance attribution. It preserves accepted external
   flow and fail-closed semantics, but needs component-level observed
   pre/post values, flow allocation, and deterministic handling of composition
   boundaries.
3. **Brinson-family attribution** is viable only for a separately accepted
   benchmark-relative question. No current benchmark evidence makes it a
   candidate implementation today.
4. **Shapley/Owen** can be a later research option for interaction-heavy
   portfolios, but requires exact counterfactual valuations and an explicit
   coalition/group policy. It is not a safe missing-data fallback.

Modified Dietz is useful as a comparison point but remains approximate and
deferred. XIRR remains a parent money-weighted metric only; it is never an
additive attribution method.

### Mathematical blockers

- TWRR compounds factors, so dollar gains and percentage-point contributions
  need a declared linking rule; there is no unique decomposition in general.
- Income, redemption principal, capital value change, internal cost and
  external flow are different quantities. Combining them into one residual
  creates double counting or a false return.
- Component interactions and rebalancing create path dependence. A component
  with zero opening weight cannot receive a whole-period opening-weight return
  without a declared boundary rule.
- XIRR's dated nonlinear root has no additive component identity, even when a
  single total root is available.
- Rounding can break an otherwise exact sum. Exact minor-unit arithmetic and an
  explicit residual policy are prerequisites for an owner-facing table.

### Data blockers in current Hermes evidence

- Monthly per-account/per-instrument snapshots do not prove an intra-period
  trade, composition, or flow-adjacent component value.
- Scope-level observed pre/post boundary points do not automatically allocate a
  flow or return to instruments.
- Unknown cash-boundary or in-kind coverage is not evidence of zero activity.
- A linked transfer can be internal at portfolio scope but external at account
  scope; asynchronous transit cannot be represented by a synthetic asset.
- Standalone legacy tax/commission rows do not identify which owner transaction
  they reconcile to.
- Direct outside-scope payouts need actual payment, account/holding provenance,
  and the observed boundary evidence required by exact TWRR.
- Current accepted work explicitly defers approximate/Modified-Dietz return,
  full non-cash flow support, historical FX expansion, and transaction/
  cost-basis realised-vs-unrealised attribution.

## 5. Questions for the Integrator before any normative PERF-04A work

These are unresolved design questions, not decisions made by this study:

1. Which parent quantity is required for the first PERF-04A slice: exact TWRR,
   value bridge, passive income, benchmark-relative active return, or a
   separately labelled combination?
2. Is the intended reporting hierarchy portfolio -> account -> instrument,
   and must every level reconcile to the same parent metric?
3. What accepted evidence will provide component-level pre/post values and
   flow allocation at external boundaries and internal composition changes?
4. How should a future contract handle same-day ordering, asynchronous owned
   account transfers, in-kind movements, and missing cash-boundary coverage?
5. If benchmark-relative attribution is wanted, which benchmark, taxonomy,
   currency, weights, and Brinson variant are authoritative?
6. What exact linking, Decimal precision, display rounding, and residual
   allocation policy should be accepted? In particular, may any unavailable
   component remain null while a parent total is shown?

Until these questions are answered by an accepted contract, the safe result for
unsupported vectors is unavailable, not a zero, estimate, or invented
allocation.

## 6. Source boundary

This discovery note was checked against the current repository's:

- `AGENTS.md` and `docs/VERIFICATION_POLICY.md`;
- `docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`;
- `docs/r08-01b-valuation-coverage.md` and
  `docs/r08-01c-performance-availability.md`;
- `docs/r08-02-portfolio-xirr.md`, `docs/r08-03-twrr-contract-recon.md`, and
  `docs/r08-03a-valuation-boundaries.md`;
- `docs/MODEL_ROUTING.md`.

The issue is the task specification; this document is advisory evidence only.
