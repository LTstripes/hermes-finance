# PERF-04A — Performance Attribution v1 contract

> **Status:** normative contract candidate for issue [#346](https://github.com/LTstripes/hermes-finance/issues/346); implementation is blocked until strong Integrator review and an independent senior financial-semantics review complete.
>
> **Contract baseline:** `d5729741f8ffda7cc492efa470b7f350e41c06b5`
>
> **Scope of this document:** contract and financial semantics only. This task does not add production code, API routes, DTO models, UI, schema, migrations, provider calls, exports, or private fixtures.

## 1. Purpose and source-of-truth boundary

PERF-04A defines the first truthful attribution surface that can be supported
by the accepted Hermes evidence. It is deliberately narrower than a general
investment-performance decomposition.

The accepted R08 contracts remain authoritative for:

- exact opening and closing valuation points;
- effective-dated performance-scope membership;
- affirmative cash-boundary and in-kind coverage;
- canonical `ExternalFlow` identity, direction, amount, date, currency and
  transfer classification;
- tax, fee, retained-income, redemption and direct-payout treatment;
- performance-currency conversion gates; and
- exact XIRR/TWRR availability and calculation semantics.

The contract is read together with:

- [the PERF-04 evidence matrix](PERF04_EVIDENCE_MATRIX.md);
- [the PERF-04 reference vectors](PERF04_REFERENCE_VECTORS.md);
- [the PERF-04 surface map](PERF04_SURFACE_MAP.md);
- [the R08 performance availability contract](../r08-01c-performance-availability.md);
- [the R08 XIRR contract](../r08-02-portfolio-xirr.md);
- [the R08 TWRR contract](../r08-03-twrr-contract-recon.md);
- [the observed-boundary contract](../r08-03a-valuation-boundaries.md); and
- [the reconciled Performance v1 roadmap](../PERFORMANCE_V1_RECONCILIATION_2026-09-06.md).

The three discovery documents retain their historical `858d64c...` baseline
labels. Issue #346 states that they were accepted and integrated at the
`d572974...` synthesis baseline; their discovery status remains non-normative.
This document is the normative PERF-04A synthesis candidate.

The governing safety rule is:

> unavailable or unknown evidence is never converted to zero, estimated,
> interpolated, or labelled exact.

## 2. Chosen Attribution v1 semantics

### 2.1 Primary metric: selected-scope value change after external flows

Attribution v1 is a **signed contribution to value change**, not a return
decomposition. The only normative v1 measure is:

`value_change_after_external_flows`

It answers:

> How much did the selected performance scope's exact closing value change
> after removing the selected-scope external boundary flows recorded for the
> interval?

It does **not** answer:

- what the annualized or time-weighted return was;
- which instrument, asset class, trade, lot or price movement caused the
  change;
- how much was realized versus unrealized P/L;
- how much was FX, carry, coupon, dividend, redemption, fee or tax; or
- how a component would have performed under a counterfactual portfolio.

The result is an exact money amount. It is not a percentage, a percentage-point
contribution, XIRR, TWRR, Modified Dietz, benchmark-relative active return, or
an estimate of any of those metrics.

### 2.2 V1 grain and supported dimensions

The v1 grain is one aggregate row for the **selected scope and exact interval**:

| Dimension | V1 decision |
| --- | --- |
| Scope | `portfolio` or one explicit `account`; follows the existing R08 scope contract. |
| Period | Exact `start_date` and `end_date` persisted valuation dates; both selected months must be closed. |
| Currency | The accepted R08 performance currency only; v1 does not add FX conversion. |
| Portfolio account rows | Not emitted. An account can be queried as its own selected scope, but that is not a portfolio decomposition. |
| Instrument rows | Not supported in v1. |
| Asset-class rows | Not supported in v1. `instrument_type` and analytics `asset_class` are not interchangeable. |
| Flow/event rows | Not attribution contributions in v1. They may be exposed only as sanitized evidence/context, not as a second performance result. |

The account-scope form is useful and exact when its own R08 prerequisites are
complete. It must not be described as an account's additive share of the
portfolio unless a future contract proves cross-scope reconciliation.

This deliberately chooses a **separate set of metrics**: one exact value-change
metric now, with income/cost/principal evidence kept conceptually separate.
The contract does not force unsupported account/instrument/asset-class
decomposition into the first slice.

### 2.3 Why v1 is not a TWRR attribution

The accepted exact TWRR is a parent return metric with explicit observed
pre/post valuation boundaries around each selected external-flow boundary.
The discovery evidence does not provide complete component-level pre/post
values, component flow allocation, trade-time composition membership, or
intra-period valuation for every candidate attribution row.

Therefore v1 does not apply a component-linking formula such as:

```text
g_ij = V+_ij - V-_ij - C_ij
q_ij = g_ij / D_j
linked_i = sum(q_ij * later_subperiod_factors)
```

That formula remains a possible future TWRR-attribution method only after its
component evidence and linking convention are separately accepted. XIRR is
nonlinear and remains a parent money-weighted metric; it is never an additive
attribution method.

## 3. Exact numerical contract

### 3.1 Inputs and signs

Let:

- `V0` be the exact opening valuation of the selected scope;
- `V1` be the exact closing valuation of the selected scope;
- `C_j` be one canonical selected-scope external-flow amount, signed from the
  selected-scope perspective;
- a contribution have `C_j > 0`;
- a withdrawal have `C_j < 0`; and
- `C = sum(C_j)` be the signed external-flow total.

The normative value bridge is:

```text
value_change_after_external_flows = V1 - V0 - C
```

Equivalently:

```text
V0 + C + value_change_after_external_flows = V1
```

The bridge is a value-change identity. It is not a TWRR factor and has no
denominator or annualization rule. A zero or negative bridge amount is valid
when all evidence is otherwise exact.

### 3.2 Money, precision and rounding

- Persisted and internal arithmetic uses integer minor units (`kopecks`) under
  the existing Hermes money contract.
- Any future calculation layer must preserve exact integer arithmetic for the
  bridge and must not use binary floating-point financial semantics.
- API money values use the existing exact decimal-string plus three-letter
  currency representation.
- No intermediate bridge term is rounded before the identity is checked.
- Display formatting may round only at the presentation boundary; a display
  residual must not be silently assigned to an account, instrument or event.
- Explicit zero remains an available zero. Missing or unknown evidence remains
  `null`/unavailable.

### 3.3 Scope treatment of flows and transfers

At portfolio scope:

- a fully linked transfer between historically in-scope accounts is internal;
- its two legs do not enter `C` as an owner contribution or withdrawal; and
- no cash-in-transit value is synthesized for asynchronous settlement.

At account scope:

- a source-account transfer leg is a withdrawal from that account;
- a destination-account transfer leg is a contribution to that account; and
- the legs use their actual dates and exact canonical amounts.

An unresolved, partially linked or unreconciled transfer fails closed under
the existing R08 transfer reasons. A difference between linked legs is not
silently treated as performance.

## 4. Income, principal, costs, direct payouts and FX

These rules define what may affect or explain the value bridge. They do not
create an income/fee/price decomposition in v1.

| Evidence or event | PERF-04A treatment |
| --- | --- |
| Retained coupon, dividend or interest inside the selected scope | Internal event. It is already reflected in the exact valuation change and is not added as an external flow or added a second time to the bridge. |
| Deposit/savings interest | Use the existing `DepositSnapshot.actual_interest_received_kopecks` meaning. It must not be duplicated with an `InvestmentCashFlow.interest` row; the existing service rejects that duplicate for deposit/savings accounts. |
| Redemption retained inside the selected scope | Principal reclassification between position and in-scope cash, not passive income and not an external flow. The redemption amount is not emitted as an attribution gain. |
| Fee, commission or tax charged inside the selected scope | Internal cost reflected in the selected valuations; it is not an owner withdrawal merely because investment cash decreased. A standalone cost is not attached to an owner flow by account/date/currency alone. |
| Owner payment with internal withholding | The canonical external boundary is the proven net amount that crossed outside the selected scope. Any separately proven internal tax/fee remains an internal cost; gross debit is not substituted for the boundary. |
| Direct coupon/dividend payout outside brokerage cash | Requires actual payment evidence plus accepted account/holding provenance. The proven net payment is one external withdrawal; gross income is explanatory evidence only and is not injected again into return or bridge math. Expected/provider calendar rows are insufficient. |
| Realized profit/loss or unrealized result | Existing fields may support bounded snapshot/reporting views, but v1 does not claim transaction, lot, disposal, price-path or realized/unrealized attribution. |
| Foreign-currency amount | No conversion is inferred from a currency label. A non-performance-currency flow/component, missing dated conversion, or incomplete conversion provenance is unavailable under the existing R08 currency reason. |

The v1 parent bridge therefore never adds a separate `income`, `redemption`,
`tax`, `commission`, `fee`, `FX`, `realized`, or `unrealized` amount to the
formula. A future explanation slice may expose such evidence as separate
labelled facts only when its own identity, scope, currency and completeness
contract is accepted.

## 5. Availability and fail-closed gates

### 5.1 Request and boundary gates

An implementation may calculate the v1 bridge only when all of the following
are true:

1. `start_date` and `end_date` are exact persisted valuation dates and
   `start_date < end_date`.
2. Opening and closing reporting months are closed and each date resolves to
   exactly one authoritative valuation point for the requested scope.
3. Every selected valuation component is complete, valid and in the accepted
   performance currency. Missing components are not zero.
4. Effective-dated historical scope membership is complete, non-overlapping
   and consistent with the selected scope for the full interval. A whole-
   portfolio membership transition inside the interval remains unavailable
   under the accepted R08 gate.
5. Affirmative cash-boundary coverage is complete for every historically
   included account. A closed month or an empty flow table is not proof of
   complete owner-boundary history.
6. Required in-kind boundary coverage is complete, and any known in-kind
   movement has accepted event-date valuation evidence. No cash is synthesized
   for an unvalued non-cash movement.
7. Every selected external flow is a valid canonical `ExternalFlow` with exact
   date, non-negative boundary amount, explicit direction, authoritative scope
   membership and accepted performance currency.
8. Transfer identity, transfer transit and any permitted transfer-leg
   reconciliation satisfy the existing R08 rules.
9. No legacy or ambiguous cash-flow evidence remains an unclassified blocker.
10. The bridge identity is evaluated in one scope and one performance currency;
    no cross-currency aggregation is performed.

### 5.2 TWRR-specific evidence is not a v1 bridge gate

Observed `pre_external_flow`/`post_external_flow` boundaries are required by
exact TWRR, not by this additive endpoint-value bridge. Consequently:

- `not_computable_valuation_boundary_missing` and
  `not_computable_valuation_boundary_order_unknown` may make TWRR unavailable
  while leaving the v1 bridge available, provided every v1 gate above passes;
- v1 does not call the TWRR solver and does not emit a TWRR value; and
- a future return-attribution slice must inherit the full exact TWRR boundary
  gate rather than weakening it.

Likewise, XIRR solver outcomes such as root ambiguity or convergence failure do
not change the value identity. XIRR remains available or unavailable according
to its own contract and is not used as a bridge contribution.

### 5.3 Result states and reason codes

The v1 response uses the existing performance state vocabulary:

| Field | Available result | Failed result |
| --- | --- | --- |
| `availability` | `available` | `not_computable` |
| `quality` | `exact` | `unavailable` |
| `value` | exact money | `null` |
| `reason_codes` | empty | sorted, stable R08 reason codes |

The parent bridge propagates the applicable existing R08 reasons, including:

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
```

The implementation must not introduce a new reason by reclassifying an
existing R08 condition. Future component/event decomposition slices may add
PERF-04-specific reason codes for missing component evidence, missing flow
allocation or failed component reconciliation, but those codes are not a
license to emit partial exact decomposition in v1.

An unavailable parent is never represented as a zero bridge. Evidence detail
may retain `unknown`/`unavailable` sub-states from R08, but the top-level v1
value is null unless the complete bridge is exact.

## 6. Normative API/DTO boundary

The first implementation should use a dedicated backend-owned read model and
endpoint, not extend the strict XIRR/TWRR response DTOs or current dashboard
result fields. The contract selects:

```text
GET /api/performance/attribution
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=portfolio|account
    [&account_id=<id>]
```

This endpoint is a future implementation seam, not part of the current task's
production change.

### 6.1 Response shape

The normative response fields are:

| Field | Contract |
| --- | --- |
| `contract` | Constant `PERF04A`. |
| `contract_version` | Integer `1`. |
| `metric` | Constant `value_change_after_external_flows`. |
| `grain` | Constant `selected_scope`. |
| `scope` | `portfolio` or `account`. |
| `account_id` | `null` for portfolio scope; required account identity for account scope. |
| `period` | Exact requested `start_date` and `end_date`. |
| `performance_currency` | The R08 performance currency. |
| `availability` | `available` or `not_computable`. |
| `quality` | `exact` only for an available result; otherwise `unavailable`. |
| `opening_value` | Exact opening valuation money or `null`. |
| `closing_value` | Exact closing valuation money or `null`. |
| `value` | Exact money `{amount: "...", currency: "..."}` or `null`; this is the bridge result, not a return. |
| `external_flow_summary` | `{contributions, withdrawals, signed_total}` with exact money values or `null`; contribution/withdrawal amounts are non-negative magnitudes and `signed_total = contributions - withdrawals`. Explicit zero is allowed when coverage is complete and no selected external flow exists. |
| `evidence` | Sanitized projections of opening/closing valuation, scope membership, cash/in-kind coverage and external-flow coverage; it must preserve R08 statuses and reasons rather than redefine them. |
| `reason_codes` | Empty for an exact result, otherwise stable sorted reason codes. |

The response contains no `return_rate`, `annualized`, `twrr_contribution`,
`xirr_contribution`, `instrument_rows`, `asset_class_rows`, `realized_pnl`,
`unrealized_pnl`, `price_effect`, `income_effect`, `fx_effect`, or
`counterfactual` field in v1. Omitting unsupported fields is intentional;
clients must not infer them from `value`.

An available response satisfies:

```json
{
  "contract": "PERF04A",
  "contract_version": 1,
  "metric": "value_change_after_external_flows",
  "grain": "selected_scope",
  "scope": "portfolio",
  "account_id": null,
  "period": {"start_date": "2026-01-01", "end_date": "2026-02-01"},
  "performance_currency": "RUB",
  "availability": "available",
  "quality": "exact",
  "opening_value": {"amount": "1000.00", "currency": "RUB"},
  "closing_value": {"amount": "1333.50", "currency": "RUB"},
  "value": {"amount": "283.50", "currency": "RUB"},
  "external_flow_summary": {
    "contributions": {"amount": "100.00", "currency": "RUB"},
    "withdrawals": {"amount": "50.00", "currency": "RUB"},
    "signed_total": {"amount": "50.00", "currency": "RUB"}
  },
  "evidence": {
    "opening_valuation": {"availability": "available", "reason_codes": []},
    "closing_valuation": {"availability": "available", "reason_codes": []},
    "scope_membership": {"status": "complete", "reason_codes": []},
    "cash_boundary_coverage": {"status": "complete", "reason_codes": []},
    "in_kind_boundary_coverage": {"status": "complete", "reason_codes": []},
    "external_flows": {"status": "complete", "reason_codes": []}
  },
  "reason_codes": []
}
```

The example is synthetic and illustrates the shape only. It is not owner data
or a fixture. The future DTO must use strict fields (`extra="forbid"` in the
existing backend convention) and exact money strings; a frontend must render
backend values and must not group, sum, allocate, interpolate or infer them.

### 6.2 Owner-facing labels

The canonical owner-facing label for the v1 metric is:

> **Изменение стоимости после внешних потоков**

The UI must append or otherwise visibly preserve:

> **Это изменение стоимости, а не доходность.**

The label must not use “доходность”, “return”, “profit”, “market return”,
“realized”, or “unrealized” for the v1 parent value. Availability and reason
codes follow existing Analytics/Freshness presentation patterns: backend owns
the state and stable code; frontend maps it to safe explanatory text and does
not display an opaque code as the primary label.

## 7. Reference-vector reconciliation

The accepted synthetic vectors are discovery evidence, not production fixtures.
The following behavior is normative for the v1 bridge:

| Discovery vector | V1 bridge consequence |
| --- | --- |
| No-flow split: `1,000.00 -> 1,160.00` | Selected-scope bridge is `+160.00`. The two account/instrument rows remain discovery-only; v1 does not emit them. |
| Contribution and withdrawal: `V0=1,000.00`, `C=+100.00-50.00`, `V1=1,333.50` | Bridge is `+283.50`. The reference TWRR `27.05%` is a separate parent return and is not emitted by v1. |
| Internal portfolio transfer | The transfer contributes `C=0` at portfolio scope; `1,000.00 -> 1,100.00` gives bridge `+100.00`. Account-scope queries use the two actual leg signs. |
| Retained coupon | The `+20.00` retained in-scope value is reflected once in the bridge; it is not an additional external flow or second income injection. |
| Redemption principal | A position-to-cash reclassification with unchanged selected total gives bridge `0.00`; redemption is not passive income. |
| Internal fee/tax cost | A complete opening `1,000.00`, internal cost `13.00`, closing `987.00` gives bridge `-13.00`; it is not an owner withdrawal. |
| Composition change or rebalance | Aggregate bridge may be exact if all v1 gates pass, but no instrument-level contribution is emitted without component boundary evidence and allocation. |
| Missing interior valuation around a contribution | If endpoint and external-flow evidence satisfy v1 gates, the bridge is the exact value identity; exact TWRR and any return attribution remain unavailable with `not_computable_valuation_boundary_missing`. V1 must not choose between the multiple compatible TWRR paths. |

All vector arithmetic uses the same signed-flow convention as the accepted
R08 contracts. No vector authorizes a new trade, lot, price, FX or transit
assumption.

## 8. Reconciliation invariants

An implementation must verify these invariants before returning an exact v1
result:

1. **Parent identity:**
   `V0 + signed_external_flow_total + value_change_after_external_flows = V1`.
2. **Flow sign identity:** contribution totals are positive, withdrawal totals
   are negative, and the signed total is their exact sum at the selected scope.
3. **Scope identity:** every value and flow belongs to the same requested
   portfolio/account scope; no current-state account flag rewrites history.
4. **Currency identity:** all terms use one accepted performance currency; a
   currency label is not a conversion rate.
5. **Transfer identity:** portfolio-internal linked transfers are excluded from
   the portfolio external-flow total; account-scope legs retain their actual
   signs and dates.
6. **No double count:** retained income, redemption principal, internal cost,
   direct payout gross amounts and external boundary amounts are not injected
   twice.
7. **No false allocation:** no amount is assigned to an instrument, asset
   class, account row, trade, lot or residual cause without exact evidence at
   that grain.
8. **Null-versus-zero:** an exact zero is returned only when evidence proves
   zero; missing or unknown evidence produces unavailable/null.
9. **No return substitution:** a v1 value bridge never substitutes XIRR,
   TWRR, Modified Dietz, a benchmark result or a capital delta labelled as a
   return.

If a future dimensioned implementation cannot prove the corresponding
component identity and flow allocation, it must return the component result as
unavailable and preserve any separately valid parent value/return metric. It
must not force a rounded residual into one row.

## 9. Deliberately excluded decompositions

The following are explicitly outside PERF04A v1:

- linked component TWRR contribution or any other percentage-point return
  attribution;
- XIRR contribution, component XIRR, or any additive annualized attribution;
- realized versus unrealized P/L by trade, lot, instrument or account;
- price, carry, coupon, dividend, redemption, fee, tax or FX contribution
  totals that claim a complete value bridge;
- Brinson/Fachler/BHB benchmark-relative attribution;
- Modified Dietz or another approximate return presented as exact;
- Shapley/Owen or another counterfactual allocation;
- inferred trades, fills, orders, acquisition lots, disposal matching or cost
  basis history;
- interpolated, start-of-day, end-of-day or synthetic in-transit valuations;
- historical asset-class remapping or FX conversion without accepted evidence;
- client-side grouping, aggregation, allocation, formula calculation or
  reclassification; and
- export/AI-bundle or portfolio-review-package projection in the first slice.

The existing dashboard `cash_income`, realized/unrealized result fields,
capital-composition buckets and XIRR/TWRR DTOs retain their existing meanings.
PERF-04A must not relabel or widen them.

## 10. Proposed implementation slices

These are bounded follow-on slices, not authorization to implement them in this
task and not a request to create implementation issues.

### Slice A — aggregate bridge read model

Add one backend-owned, read-only calculation that consumes the accepted R08
availability/evidence path, applies the v1 formula, returns the strict DTO,
and preserves existing XIRR/TWRR endpoints unchanged. No new ledger, schema or
migration is needed for the aggregate bridge if the existing evidence is
reused.

### Slice B — contract tests and exact vectors

Add sanitized contract tests for no-flow, contribution/withdrawal, internal
portfolio transfer, account-scope transfer legs, retained income, redemption,
internal cost, unavailable coverage, missing boundary, unknown order and
missing FX. Tests must assert exact money, null-versus-zero, reason propagation
and that TWRR-only boundary failures do not become a bridge estimate.

### Slice C — owner-facing selected-scope presentation

Add a thin Analytics projection only after Slice A is accepted. It may render
the selected-scope value and evidence state using the owner label above. It
must not create account/instrument/asset-class rows or calculate anything in
the browser.

### Slice D — separately accepted component evidence

Before any portfolio account/instrument/asset-class attribution, accept a new
evidence contract for component-level pre/post values, boundary grouping,
component flow allocation, composition changes and deterministic linking.
Only then choose whether the parent is exact TWRR, a value bridge, or a
separately labelled metric set.

### Slice E — event explanations and exports

If owner need justifies it, accept a separate event-evidence contract for
income, redemption, fees/taxes and direct payouts, including duplicate-source
precedence and completeness. Add AI/export sections only as additive,
versioned projections of one backend-owned fact set; never fill existing
unavailable investment-return fields speculatively.

## 11. Unresolved blockers and Integrator questions

These questions do not block the conservative aggregate bridge contract, but
they block any broader decomposition implementation:

1. Is the owner-facing first implementation explicitly willing to call the v1
   metric a value-change explanation rather than a return attribution, or is a
   separate component-boundary evidence task required before any PERF-04
   implementation?
2. What authoritative source will provide component-level pre/post values and
   flow allocation at each external-flow and internal-composition boundary?
3. Is a trade/order/fill/lot and cost-basis model required for realized versus
   unrealized attribution, or must that decomposition remain unavailable?
4. What dated FX source, conversion provenance and historical currency policy
   will be accepted for cross-currency attribution?
5. What historical classification contract would make `instrument_type` and
   analytics `asset_class` safe, stable attribution dimensions?
6. For a future exact-return attribution, which linking convention and
   residual policy will be accepted once component evidence exists?
7. Which actual income and direct-payout sources may be combined without
   double-counting, and how will completeness be proven over an interval?

Until these are answered by accepted evidence/contracts, unsupported rows stay
unavailable and the v1 scope remains the exact selected-scope value bridge.

## 12. Review gate and non-acceptance statement

This document intentionally leaves production behavior unchanged. Before any
implementation slice is unblocked, the Integrator must review the financial
meaning, exact formula, scope/transfer treatment, evidence gates, labels and
privacy boundary. An independent senior financial-semantics reviewer must
separately validate the candidate because this is a high-risk financial
contract.

Completion of this Worker task, a commit, or a pushed branch is not project
`ACCEPT` and does not authorize integration into `integration/performance-v1`
or `main`.
