# PERF-04B — component attribution contract

> **Status:** normative candidate for issue [#396](https://github.com/LTstripes/hermes-finance/issues/396).
> **Verdict:** `PARTIAL GO`.
> **Canonical baseline:** `d7529a033a41b9098aa621fc2cb62c8e572df6a9` (current GitHub `main`).
>
> This document is a contract/design change only. It does not change
> production code, schema, migrations, API, frontend/UI, provider behavior or
> existing PERF04A/XIRR/TWRR semantics. Final project acceptance still requires
> Integrator review and independent senior financial-semantics review on the
> exact candidate SHA.

## 1. Decision and boundary

The only supported next grain is a narrow **portfolio decomposition of the
existing PERF04A value bridge**:

```text
B_portfolio = sum(B_account) + sum(T_internal_transfer)
```

This identity is exact only when every required parent, account and transfer
reconciliation input is exact. `B` is the existing PERF04A
`value_change_after_external_flows` money amount. It is a value-change bridge,
not a return, profit, XIRR, TWRR or causal investment attribution. XIRR and
TWRR remain separate non-additive parent metrics.

`PARTIAL GO` means that this one bounded decomposition may be implemented under
strict evidence. It does **not** authorize partial rows, estimated residuals or
an apparently complete portfolio split when any required row or reconciliation
effect is unavailable.

The contract is read with the accepted [PERF04A contract](PERF04_ATTRIBUTION_CONTRACT.md),
[PERF04 evidence matrix](PERF04_EVIDENCE_MATRIX.md), [R08 availability](../r08-01c-performance-availability.md),
[R08 XIRR](../r08-02-portfolio-xirr.md), [R08 TWRR](../r08-03-twrr-contract-recon.md),
[observed-boundary contract](../r08-03a-valuation-boundaries.md), and
[Performance v1 closeout](../PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

## 2. Parent quantity and row meaning

For any selected scope `s`, let:

- `V0_s` and `V1_s` be the exact opening and closing valuations;
- `C_s` be the signed external-flow total from that scope's perspective;
- contributions have positive `C` and withdrawals have negative `C`; and
- `B_s` be the existing PERF04A bridge:

```text
B_s = V1_s - V0_s - C_s
V0_s + C_s + B_s = V1_s
```

At account scope, a linked transfer leg crosses that account boundary: the
source leg is a negative withdrawal and the destination leg is a positive
contribution. At portfolio scope, a fully linked transfer between historically
in-scope accounts is internal and both legs are excluded from `C_portfolio`.
A transfer crossing the selected scope boundary is an ordinary external flow,
not an internal-transfer component.

An account row is therefore an exact **account-scope PERF04A value change**
when its own evidence passes. It is not automatically an additive portfolio
share, an account return or an account investment-profit attribution.

## 3. Capability matrix

| Grain or effect | Capability verdict | Normative limit |
| --- | --- | --- |
| Portfolio → account decomposition | **`PARTIAL GO`** | Exact only when the parent, every required account row, every in-scope internal transfer effect, endpoint sums and all inherited R08 gates pass. |
| Account | **Exact under strict evidence** | The selected account's PERF04A bridge is usable for a bounded interval under its own R08 evidence. It may be published as a portfolio component only inside a complete parent decomposition. |
| Instrument | **Unsupported** | Monthly snapshots identify stored positions but do not prove component pre/post boundary values, flow allocation, trade path or complete composition history. |
| Asset class | **Unsupported** | `instrument_type` and analytics `asset_class` are not interchangeable, and historical classification/flow allocation is not authoritative. |
| Price / FX effect | **Unsupported** | No exact price-vs-FX decomposition is selected. Currency labels or transfer reconciliation metadata do not create a performance-currency amount. |
| Realised / unrealised P&L | **Unsupported** | Existing fields remain bounded snapshot/reporting evidence, not exact trade, disposal or causal component attribution. |
| Cost basis, lots and trades | **Unsupported** | No complete execution, acquisition-lot, disposal-allocation or cost-basis history exists for this contract. |

No supported row may be inferred from a capital delta, current account flag,
instrument label, cost basis, percentage return or rounded residual.

## 4. Exact formula and transfer signs

### 4.1 Account and portfolio bridges

For account `a`:

```text
C_a = sum(account contributions) - sum(account withdrawal magnitudes)
B_account(a) = V1_a - V0_a - C_a
```

For the selected portfolio:

```text
C_portfolio = sum(external contributions) - sum(external withdrawal magnitudes)
B_portfolio = V1_portfolio - V0_portfolio - C_portfolio
```

`C_portfolio` excludes a resolved linked transfer only when both legs belong to
the historically in-scope portfolio. It includes a flow that crosses the
selected scope, including a transfer to or from an out-of-scope account.

### 4.2 Internal-transfer effect

For one fully linked internal transfer `t`, define non-negative magnitudes:

- `S_t`: exact source withdrawal leg;
- `D_t`: exact destination contribution leg; and
- `e_{t,i}`: exact non-negative transfer-specific reconciliation amounts.

`T_internal_transfer(t)` is defined only after eligibility is proven:

```text
if S_t = D_t:
    T_internal_transfer(t) = 0
elif S_t > D_t and sum(e_{t,i}) = S_t - D_t:
    T_internal_transfer(t) = D_t - S_t = -sum(e_{t,i})
else:
    T_internal_transfer(t) = unavailable
```

The second case requires accepted evidence tied exclusively to this transfer
that explains the entire difference as an internal fee, commission or tax.
The evidence and both legs must already be exact in the same accepted
performance currency. An `fx_conversion_spread` metadata row does not by itself
create an exact performance-currency amount; cross-currency conversion remains
unavailable unless a separate accepted currency contract supplies that amount.

The following are not valid transfer effects:

- `S_t > D_t` with no accepted reconciliation evidence: the decomposition is
  unavailable/null, not an exact negative residual;
- `D_t > S_t`: unavailable, because current evidence has no accepted exact
  gain primitive; and
- a one-sided, unresolved, duplicated or ambiguously scoped link: unavailable,
  even if the leg arithmetic happens to balance.

When all terms are eligible, the additive identity is:

```text
B_portfolio = sum_a B_account(a) + sum_t T_internal_transfer(t)
```

The transfer effect is a reconciliation component. It is never relabelled as
account investment performance and is never added a second time as a fee/tax
performance row.

## 5. Availability and fail-closed prerequisites

The decomposition is `available`/`exact` only when **all** of the following
hold:

1. The existing PERF04A parent bridge is exact/available from its dedicated
   `perf04a_bridge_prerequisites` projection. Do not substitute the top-level
   R08 union, an XIRR solver result or a TWRR result.
2. Opening and closing dates resolve to one closed, exact valuation point for
   the portfolio and for every historically required in-scope account.
3. Every required account row is exact under account-scope PERF04A semantics:
   complete historical membership, affirmative cash-boundary coverage,
   complete canonical external-flow evidence, accepted currency and valid
   valuation components. The current-state `include_in_returns` flag cannot
   repair history.
4. The set of account rows is complete. A subset of accounts is not a
   portfolio split, even when each displayed row is individually exact.
5. Every internal transfer pair is identity-resolved, opposite-direction and
   scoped correctly. Equal legs reconcile to exact zero; unequal legs satisfy
   the evidence rule in section 4.2. Evidence is linked one-to-one and is not
   reused across transfers.
6. Portfolio and account endpoint valuations reconcile in minor units:
   `V_portfolio,t = sum(V_account,t)` for `t` equal to opening and closing.
   Any mismatch is unavailable; no residual account or transfer row is made.
7. All terms are in one accepted performance currency. Missing dated FX,
   incomplete conversion provenance or a foreign-currency reconciliation
   metadata row without an exact converted amount fails closed.
8. No known unvalued in-kind movement, unknown in-kind coverage,
   unclassified cash, membership gap/change, legacy ambiguous flow, unresolved
   transfer, unvalued transit or endpoint order ambiguity remains.
9. The minor-unit parent identity and the additive decomposition identity both
   hold exactly before any display rounding.

The existing endpoint rule remains in force: a flow or transfer on the
consumed `start_date` or `end_date` needs accepted relation/order evidence.
Strictly interior TWRR-only observed-boundary gaps do not by themselves block
this value bridge; they do not authorize a TWRR contribution or an estimate.

Failure of any prerequisite returns no decomposition number or complete row
set. The parent PERF04A/XIRR/TWRR result may remain separately valid where its
own contract permits it, but a partial account list must not be published as a
complete portfolio split.

### Stable reason handling

Propagate the narrowest accepted R08/PERF04A reason without reclassifying it.
Applicable reasons include:

```text
not_computable_opening_valuation_missing
not_computable_closing_valuation_missing
not_computable_reporting_month_not_closed
not_computable_snapshot_date_missing
not_computable_unsupported_position_valuation
not_computable_scope_coverage_incomplete
not_computable_scope_cash_unclassified
not_computable_scope_membership_history_missing
not_computable_scope_membership_changed
not_computable_external_flows_incomplete
not_computable_currency_conversion_incomplete
not_computable_transfer_identity_unresolved
not_computable_transfer_in_transit_unvalued
not_computable_transfer_reconciliation_incomplete
not_computable_in_kind_boundary_coverage_unknown
not_computable_in_kind_movement_unvalued
not_computable_valuation_boundary_order_unknown
```

`not_computable_valuation_boundary_missing` remains a TWRR-only reason for a
strictly interior flow and is not converted into a bridge estimate. A missing
or ambiguous relation at a consumed endpoint remains bridge-blocking with
`not_computable_valuation_boundary_order_unknown`. No new catch-all reason or
residual bucket is introduced by this candidate.

## 6. Minor-unit reconciliation invariant

All valuations, flow totals, account bridge values and transfer effects are
integer minor units (`kopecks`) until presentation. The implementation must
verify all of these identities in integer arithmetic:

```text
V_portfolio,0 = sum(V_account,0)
V_portfolio,1 = sum(V_account,1)
sum(C_account) = C_portfolio + sum(D_t - S_t)
B_account(a) = V1_a - V0_a - C_a
B_portfolio = sum(B_account) + sum(T_internal_transfer)
```

For an unequal reconciled pair, also verify:

```text
S_t - D_t = sum(e_{t,i})
T_internal_transfer(t) = D_t - S_t
```

No intermediate term is rounded. A presentation residual is not assigned to
an account, instrument, asset class, transfer or unexplained cause.

## 7. Null versus zero

| Evidence state | Required result |
| --- | --- |
| All prerequisites pass and the exact arithmetic result is zero | Available exact numeric `0` in the performance currency. |
| No selected external flow, with affirmative complete coverage | Exact `C = 0`; this is not the same as unknown flow history. |
| Missing, unknown, incomplete or contradictory evidence | `not_computable`, `null`, and the applicable stable reason. |
| Source `100.00` → destination `99.00` without accepted reconciliation | `null`/unavailable; never exact `T = -1.00`. |
| Cross-currency metadata without accepted conversion | `null`/unavailable; never `0`, a foreign amount relabelled as RUB, or an estimate. |

Unknown stays unknown. An exact zero is evidence-backed, not a default for
absence of rows.

## 8. Double-count prohibition

The following are mandatory:

- Exclude a fully in-scope linked transfer from `C_portfolio`, include its
  selected legs in account-scope `C_account`, and add its exact `T` once.
- Do not add the transfer's internal fee/commission/tax again to an account
  bridge, portfolio bridge or separate residual.
- Retained coupon, dividend, interest and internal cost already reflected in
  the selected valuations are counted once through `B`; they are not injected
  again as external flows or transfer effects.
- Redemption principal is a position-to-in-scope-cash reclassification, not
  passive income.
- A direct outside-scope payout uses one proven net external boundary; gross
  income and withholding evidence are explanation data, not a second flow.
- Never use a missing reconciliation, transit amount, in-kind value, FX amount,
  membership change or valuation mismatch as a catch-all residual.

## 9. Required synthetic reference vectors

All vectors below are synthetic RUB examples unless stated otherwise. They are
hand-checkable contract vectors, not owner data or production fixtures. `B_A`
and `B_B` denote exact account bridges when the row is eligible.

| Required vector | Synthetic facts | Normative result |
| --- | --- | --- |
| Equal internal transfer | `A: 1000.00 → 900.00, C_A=-100.00`; `B: 500.00 → 600.00, C_B=+100.00`; `P: 1500.00 → 1500.00, C_P=0`. | `B_A=0`, `B_B=0`, `T=100-100=0`, `B_P=0`. The resolved equal pair is internal at portfolio scope. |
| Unequal reconciled transfer | `A: 1000.00 → 900.00, C_A=-100.00`; `B: 500.00 → 599.00, C_B=+99.00`; `P: 1500.00 → 1499.00, C_P=0`; accepted `internal_fee e=1.00`. | `B_A=0`, `B_B=0`, `T=99-100=-1.00=-e`, `B_P=-1.00`. The negative effect is exact only because the entire difference is accepted reconciliation evidence. |
| Unequal unreconciled transfer | Same `100.00 → 99.00` legs and endpoint values as above, but no accepted transfer-specific evidence. | The whole portfolio decomposition (and the affected PERF04A portfolio result under current fail-closed semantics) is unavailable/null with `not_computable_transfer_reconciliation_incomplete`; do not publish exact `-1.00`. |
| Destination-gain | `A: 1000.00 → 901.00, C_A=-99.00`; `B: 500.00 → 600.00, C_B=+100.00`; `P: 1500.00 → 1501.00, C_P=0`. | The arithmetic difference is `+1.00`, but `D>S` has no accepted exact gain primitive. Decomposition is unavailable/null with `not_computable_transfer_reconciliation_incomplete`; no positive `T` is emitted. |
| Cross-scope | `A` is in scope: `1000.00 → 900.00`, one `-100.00` withdrawal to out-of-scope `B`; `P` is `1000.00 → 900.00`. | `C_P=-100.00`, so `B_P=900-1000-(-100)=0`. The flow is external at the selected portfolio boundary; no internal `T` and no out-of-scope account row. |
| Unresolved / one-sided | One unresolved source leg `A: 1000.00 → 900.00, C_A=-100.00`; no resolved destination identity. | Account/decomposition result is unavailable/null with `not_computable_transfer_identity_unresolved`; balancing arithmetic does not repair identity. |
| Endpoint transit / order ambiguity | A linked `100.00` source leg occurs on `start_date` and the `100.00` destination leg later, without a trusted consumed-endpoint valuation through transit; same-day endpoint legs also lack explicit order. | Decomposition is unavailable/null with the applicable `not_computable_transfer_in_transit_unvalued` or `not_computable_valuation_boundary_order_unknown`. No synthetic transit value or day-order convention is used. |
| Interior equal transfer | The equal `100.00` pair is strictly interior to the interval and has no observed TWRR pre/post boundary. | PERF04B may still be exact under the other gates: `T=0` and the bridge identity above holds. TWRR may independently remain unavailable; its boundary gap is not a bridge estimate. |
| In-kind | One known in-scope security movement crosses the interval; endpoint portfolio totals happen to be `1000.00 → 1000.00`, but no accepted event-date monetary value exists. | Unavailable/null with `not_computable_in_kind_movement_unvalued`; no `C=0` inference, cash surrogate or `T=0` is created. |
| Membership change | Account `A` is in scope at opening and out of scope at closing (or has a gap/overlap in effective history); illustrative values are `1000.00 → 1100.00`. | Unavailable/null with `not_computable_scope_membership_changed` or the applicable membership-history reason. No partial account split is published. |
| Unclassified cash / valuation mismatch | (a) A `50.00` portfolio cash row has no account identity; or (b) `V_portfolio=1500.00` while the proposed account endpoint sum is `1499.00`. | (a) `not_computable_scope_cash_unclassified`, not an assigned account zero; (b) unavailable/null with `not_computable_scope_coverage_incomplete` (or a narrower accepted valuation reason), with no invented `1.00` residual. |
| Cross-currency incomplete | Source leg `100.00 EUR`, destination leg `99.00 USD`, and an `fx_conversion_spread` metadata item of `1.00 EUR`, but no accepted dated conversion into performance currency. | Unavailable/null with `not_computable_currency_conversion_incomplete`. Metadata does not become `-1.00 RUB`, `0`, or an exact performance-currency effect. |
| Double-count guard | Retained internal coupon: `V0=1000.00`, `V1=1020.00`, `C=0`; separately, the reconciled `100.00 → 99.00` transfer above has `T=-1.00`. | Coupon contributes `+20.00` once through `B`; transfer contributes `-1.00` once through `T`. Adding a second `+20.00` or `-1.00` cost would be invalid. |
| Parent unavailable / account exact | `A: V0=1000.00 → V1=1100.00, C_A=0`, so isolated `B_A=+100.00`; another required account has missing closing valuation. | The isolated account result may remain exact, but the portfolio parent/decomposition is `null`/unavailable (for example `not_computable_closing_valuation_missing`). `A` is not published as a complete portfolio split. |
| Minor-unit exact reconciliation | `A: 100000 → 89999` kopecks with `C_A=-10001`; `B: 50000 → 59998` with `C_B=+9998`; `P: 150000 → 149997`, `C_P=0`; accepted fee `e=3` kopecks. | `B_A=B_B=0`; `T=9998-10001=-3` kopecks (`-0.03 RUB`); `B_P=-3` kopecks. The identity holds without decimal rounding. |

## 10. Explicitly out of scope

This contract does not support or authorize:

- instrument or asset-class contribution rows;
- price, FX, carry, coupon, dividend, redemption, fee or tax decomposition as
  complete economic components;
- realised/unrealised P&L by account, instrument, trade or lot;
- trade, order, fill, acquisition-lot, disposal or cost-basis reconstruction;
- additive XIRR/TWRR contributions, Modified Dietz, Brinson, Shapley,
  Owen or another counterfactual/benchmark method;
- exact monetary attribution for a known in-kind movement without a separate
  accepted non-cash valuation contract;
- cross-currency conversion inferred from labels or reconciliation metadata;
- a positive destination-gain transfer effect;
- start/end-of-day, half-open interval, interpolation or in-transit
  assumptions;
- a catch-all residual, rounded residual or partial portfolio split;
- changes to PERF04A, XIRR, TWRR, availability, endpoint-order, membership,
  flow or in-kind semantics;
- production API, frontend/UI, schema, migration, provider/network,
  background-refresh, export or AI-bundle changes; or
- private owner data, provider payloads, credentials, databases, backups or
  reconstructive evidence.

## 11. Smallest next implementation slice

The smallest follow-on is one backend-owned, read-only decomposition read model
over the existing PERF04A account bridge and accepted transfer evidence:

1. enumerate the complete historically in-scope account set;
2. reuse the existing exact account-scope PERF04A calculation;
3. resolve each in-scope internal transfer once and compute only an eligible
   `T_internal_transfer` in integer minor units;
4. verify endpoint sums, flow-sign identity and the additive identity; and
5. return the complete decomposition or `null`/unavailable with inherited
   stable reasons. Never return a partial exact-looking split.

This slice must leave existing PERF04A, XIRR and TWRR calculations unchanged.
It needs sanitized tests for every vector in section 9, including exact zero,
null-versus-zero, destination gain, cross-currency incompleteness,
one-to-one evidence use and double-count prevention. API/UI/export exposure is
not part of this smallest slice and requires its own accepted surface contract.

Before implementation can start, the exact candidate needs Integrator review,
independent senior financial-semantics review, targeted contract tests, the
repository-required full relevant backend gate, privacy/diff checks and exact
candidate read-back. This Worker document alone is not project `ACCEPT` and is
not implementation authorization.
