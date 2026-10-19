# R08-03 — Portfolio TWRR contract/recon

**Decision: `BLOCK ON PREREQUISITE`**

This note is the contract/recon phase for [issue #147](https://github.com/LTstripes/hermes-finance/issues/147) at baseline `951d2ebe2a9b4ac865fa9d6196c740616385566`. It does not add a production TWRR calculator, approximate-return output, API, or UI.

Normative inputs are [accepted #145](https://github.com/LTstripes/hermes-finance/issues/145), [accepted #179](https://github.com/LTstripes/hermes-finance/issues/179), [accepted #190](https://github.com/LTstripes/hermes-finance/issues/190), [#197](https://github.com/LTstripes/hermes-finance/issues/197), and the implemented [R08-01B valuation coverage](r08-01b-valuation-coverage.md) / [R08-01C performance availability](r08-01c-performance-availability.md) contracts.

## Decision boundary

The current persisted model can establish an exact TWRR input interval only when there is no selected-scope external boundary flow that requires segmentation. A flow-free interval with trusted opening and closing valuations is one TWRR subperiod; a resolved transfer between two in-scope accounts is not an external portfolio flow and does not add a portfolio boundary.

Production TWRR is blocked for intervals containing an external contribution or withdrawal because current valuation points are monthly/date-only observations and have no explicit `pre_external_flow` / `post_external_flow` relation. A matching calendar date does not prove event order. An interior flow with no observed valuation on its date is missing a boundary; a same-day observation without an explicit relation has unknown order.

No approximate monthly TWRR is accepted as a fallback. It must be a separately labelled and separately accepted contract; it must never be emitted as exact TWRR.

## Persisted support matrix

| Evidence | Exact support now | Recon consequence |
| --- | --- | --- |
| Opening/closing valuation | `reporting_months.snapshot_date` is an unambiguous `date`; the month must be `closed`. R08-01B derives an exact RUB total only from complete persisted position, deposit, and performance-cash components. | Exact endpoint input is available only when the point is `available`/`exact`. Missing, ambiguous, draft, or incomplete points block with the existing opening/closing or point-coverage reason. |
| Positions | `position_snapshots.market_value_kopecks` is an exact persisted, backend-recomputed amount for a month/account/instrument. `price_date` is also date-only and is provenance, not an intra-period valuation boundary. | Authoritative for a complete selected account; it does not provide a pre/post-flow observation. |
| Deposits | `deposit_snapshots.balance_kopecks` is account-linked and currency-less under the existing schema. Accepted #145 v2 interprets it as `AppSettings.base_currency` (currently RUB). | Usable as a complete component under the existing schema; no foreign-currency rewrite or historical FX inference. |
| Performance cash | R08-01B may use an explicitly account-linked, base-currency `cash_balances` row. A legacy `NULL account_id` row cannot be assigned to a performance scope. | Unassigned cash is `not_computable_scope_cash_unclassified`; non-base-currency cash without an accepted dated conversion is `not_computable_currency_conversion_incomplete`. Neither is zero. |
| Historical membership | `account_performance_scope_memberships` is effective-dated evidence. The present `Account.include_in_returns` flag is not historical evidence. | A gap or overlap is `not_computable_scope_membership_history_missing`; changing the current flag must not heal it. |
| External flow | R08-01A persists exact `event_date`, non-negative `boundary_amount_kopecks`, explicit direction/kind, currency, scope-membership evidence, and durable transfer identity/status. | Amount and scope classification can be exact, but date-only flow evidence has no ordering relation to a valuation point. |
| Legacy investment flow | Existing `investment_cash_flows.deposit` / `withdrawal` rows do not prove boundary crossing or which amount is authoritative. | A relevant legacy row makes external-flow coverage `not_computable_external_flows_incomplete`; it is never backfilled or reclassified automatically. |
| Internal investment events | Coupons, dividends, redemptions, fees, taxes, and retained deposit interest remain internal while inside the selected scope. `deposit_snapshots.actual_interest_received_kopecks` remains the canonical actual deposit-interest source. | They affect complete valuations but are not injected a second time as external TWRR flows. Redemption is not passive income. |
| Forecast/provider calendar | `expected_cash_flows` and `applied_provider_payouts` are planning/calendar evidence, not proof of realised receipt. | A date passing does not create a realised performance flow or valuation adjustment. |
| Availability surface | R08-01C returns exact opening/closing evidence, flow evidence, and separate XIRR/TWRR prerequisite states; it returns no metric value. | TWRR must consume this evidence without redefining financial semantics. |

## Exact TWRR availability rule

For either `portfolio` or an explicit `account`, exact TWRR may be calculated only if all of the following hold:

1. The requested opening and closing dates resolve to exactly one closed, trusted valuation point each.
2. Every required selected-scope component is authoritative in the performance currency, including historical scope membership and performance cash classification.
3. External-flow coverage is complete: explicit boundary amounts are valid, relevant flow membership is authoritative, transfers are resolved when applicable, and conversion is complete.
4. There are no selected-scope external contribution/withdrawal boundaries requiring an unobserved or unordered split. At portfolio scope, a fully linked transfer between two in-scope accounts is internal and does not violate this condition.

With no selected-scope external boundary flow, the future calculator may use the single exact factor:

```text
TWRR = closing_value / opening_value - 1
```

The factor can be `0` for a flat period or negative for a loss period. Those outcomes are not `not_computable` by themselves. This phase does not expose the resulting percentage.

When external flows are supported by the prerequisite, the calculator must order explicit flow groups and use an observed valuation immediately before and immediately after each group. Contributions use positive boundary amount from the portfolio perspective; withdrawals use the same non-negative amount with withdrawal direction. The chained subperiod factors must use those observed boundaries and must not interpolate, assume start/end-of-day order, or turn a capital delta into return.

The following independent reference vector fixes the intended segmentation, without implementing it in production:

| Boundary | Observed value (RUB) | Signed boundary flow (RUB) | Factor |
| --- | ---: | ---: | ---: |
| Opening | 1,000.00 | — | — |
| Before contribution 1 | 1,100.00 | — | `1,100 / 1,000 = 1.10` |
| After contribution 1 | 1,200.00 | `+100.00` | `1,200 / (1,100 + 100) = 1.00` |
| Before withdrawal 2 | 1,320.00 | — | `1,320 / 1,200 = 1.10` |
| After withdrawal 2 | 1,270.00 | `-50.00` | `1,270 / (1,320 - 50) = 1.00` |
| Closing | 1,333.50 | — | `1,333.50 / 1,270 = 1.05` |

The chained factor is `1.10 × 1.00 × 1.10 × 1.00 × 1.05 = 1.2705`, so the reference TWRR is `27.05%`. The current persisted model cannot record the four flow-adjacent observations and their relations.

## Fail-closed rules

The following are `not_computable` for TWRR. Existing R08-01C reasons propagate to TWRR unless explicitly noted:

| Situation | TWRR reason | XIRR distinction |
| --- | --- | --- |
| Opening or closing point missing | `not_computable_opening_valuation_missing` or `not_computable_closing_valuation_missing` | Blocks both metrics. |
| Selected month is draft, has no snapshot date, or contains an invalid persisted valuation | `not_computable_reporting_month_not_closed`, `not_computable_snapshot_date_missing`, or `not_computable_unsupported_position_valuation` | Blocks both metrics. |
| Missing/unknown selected component, unclassified cash, or incomplete historical membership | `not_computable_scope_coverage_incomplete`, `not_computable_scope_cash_unclassified`, or `not_computable_scope_membership_history_missing` | Blocks both metrics; current account flags cannot repair history. |
| Relevant legacy deposit/withdrawal row | `not_computable_external_flows_incomplete` | Blocks both metrics; no legacy amount is guessed. |
| Unresolved or incomplete transfer identity | `not_computable_transfer_identity_unresolved` | Blocks both metrics for the affected scope. |
| Foreign flow/component without an accepted dated conversion | `not_computable_currency_conversion_incomplete` | Blocks both metrics. |
| Interior external flow has no trusted observed valuation on its date | `not_computable_valuation_boundary_missing` | XIRR may remain available when its own evidence is complete. |
| A date-only valuation exists on the flow date but no explicit pre/post-flow relation proves order | `not_computable_valuation_boundary_order_unknown` | XIRR may remain available; this is TWRR-specific. |
| More than one external flow | Every flow/group must satisfy the boundary rule; one missing or unordered boundary blocks the whole TWRR interval. | XIRR still needs only complete dated flow evidence. |
| Fully linked in-scope transfer at portfolio scope | No TWRR boundary reason from that transfer. | It is internal at portfolio scope, but external at each affected account scope. |
| Flat or negative return with otherwise valid evidence | No availability failure solely for a zero or negative return. | The future numerical implementation must preserve the value rather than downgrade it. |

`not_computable` means unavailable, never zero and never a silently downgraded approximate result.

## Required prerequisite

Before implementing production TWRR for issue #147, add and accept an additive valuation-boundary persistence/capture slice (an R08-01B follow-up or an explicitly named prerequisite). It must provide:

- additional observed intra-period valuation points for the selected scope/account;
- exact performance-currency value, complete component coverage, provenance, and quality for every point;
- an explicit relation from each point to one external flow or same-boundary flow group, at least `pre_external_flow` or `post_external_flow`;
- deterministic ordering/group semantics for same-date flows; timestamp precision alone is insufficient when the source cannot prove event order;
- read-only exposure through the availability contract, with the existing stable `not_computable_*` reasons when any relation or point is absent;
- sanitized tests for multiple flows, missing boundary, unknown same-day order, flat/loss periods, internal portfolio transfers, and all inherited R08-01C coverage failures.

Until that prerequisite exists, #147 production work must stop at this recon contract. The current implementation is sufficient to consume exact flow-free TWRR intervals, but not to satisfy the issue's multi-flow exact-TWRR acceptance without inventing observations.

## Scope of this change

This phase changes only this contract note and the synthetic contract tests in `backend/tests/test_r08_03_twrr_contract_recon.py`. No production calculator, migration, API, provider call, frontend code, approximate metric, or private fixture is in scope.
