# R07-06A — persisted-data inventory and supported-metrics contract

Status: normative for issue #169.

This document is the boundary for the first Risk/Allocation backend slice. It
describes what the persisted Hermes data can support at the selected
`ReportingMonth.snapshot_date`. It does not add metadata, infer financial
meaning from names, or make an external provider request.

## Scope and common rules

- The API is read-only and deterministic.
- The selected reporting month is the only valuation scope. Only rows marked
  `include_in_capital` (or the existing equivalent on the persisted source)
  participate in liquid-asset allocation.
- Amounts are integer RUB kopecks at the persistence boundary and decimal
  strings for API percentages. No binary `float` or FX conversion is used.
- Liquid assets are `CashBalance` + `DepositSnapshot.balance_kopecks` + valid
  `PositionSnapshot.market_value_kopecks`. `PropertySnapshot` is never part of
  this portfolio scope; real estate and mortgage remain separate.
- `supported`, `unavailable`, and `unknown` are data states, not risk levels.
  No state is a risk score, probability, recommendation, or alarm.
- A missing field is never replaced with a value inferred from an instrument
  name, ticker, ISIN, account name, provider identity, payout date, or notes.

## Persisted-data inventory

| Data need | Persisted source and fields | What is authoritative now | Boundary / consequence |
| --- | --- | --- | --- |
| Instrument type / explicit asset class | `instruments.instrument_type`; constrained to `stock`, `bond`, `fund`, `currency`, `gold`, `other` | The stored enum value is an explicit classification. `fund`, `currency`, `gold`, and `other` stay distinct; `other` is not reclassified. | Supported for valid RUB position valuations. No sector, issuer, or “safe/risky” subclass is inferred. |
| Account identity | `accounts.id`, `name`, `account_type`, `status`, `include_in_capital`; positions and deposits carry `account_id` | Account-level grouping is supported for account-linked positions and deposits. | `external_code` is an opaque optional code. It is not a broker/bank identity. No broker or bank grouping is claimed. |
| Current position valuation | `position_snapshots.reporting_month_id`, `account_id`, `instrument_id`, `market_value_kopecks`; `instruments.currency` | `market_value_kopecks` is the stored snapshot valuation produced by the existing position service. | Only explicit `RUB` valuations are included. A missing currency is `unknown`; a non-RUB valuation is `unavailable` without FX. |
| Deposit valuation | `deposit_snapshots.reporting_month_id`, `account_id`, `balance_kopecks`, `deposit_type` | Existing deposit service/API contract treats the amount as RUB and the row is account-linked. | There is no per-row currency column, so deposits support liquid allocation under the existing RUB-only contract, but do not prove a standalone currency-exposure dimension. |
| Cash valuation | `cash_balances.reporting_month_id`, `amount_kopecks`, `currency`, `include_in_capital` | Amount and explicit currency are persisted. | There is no `account_id`; cash is included in asset-class allocation only when RUB and is reported as unassigned for account allocation. It is never assigned from `name`. |
| Issuer identity | No issuer column on `instruments`, positions, payouts, or mappings | None. | Issuer allocation/concentration is `unavailable` with `issuer_not_persisted`. Instrument name/ticker/ISIN are not issuer identity. |
| Currency identity | `instruments.currency`, `cash_balances.currency`; payout rows also carry currency | Explicit currency strings can be inspected. | Currency exposure is supported only for a complete RUB-only valuation scope. Missing currency is `unknown`; non-RUB valuation is `unavailable` because no FX/normalization contract exists. No currency is guessed from instrument type. |
| Maturity | No maturity field on `instruments` or position snapshots | None. | Maturity ladder/concentration is `unavailable` with `maturity_not_persisted`. A bond type, ISIN, payout date, or provider identity is not maturity metadata. |
| Expected payout/redemption | `expected_cash_flows` and active `applied_provider_payouts`, exposed through `merged_payout_calendar` / R07-05 ladder | #137 merged-calendar semantics: selected month `snapshot_date` to one year, manual/provider duplicate resolution, active provider lifecycle only, and explicit event dates. | Only dated ladder items are concentratable. Redemption remains capital cash flow and is excluded from passive payout totals. Deposit forecast has no dated account/instrument event and is not allocated to a recipient. |
| Real estate / mortgage | `property_snapshots.estimated_value_kopecks`, `mortgage_balance_kopecks` | Separate property-equity and mortgage contracts. | Not queried by risk/allocation metrics and never mixed into liquid capital. |

## Support-state contract

Each metric and each excluded metadata dimension exposes:

```text
status: supported | unavailable | unknown
reason_codes: stable, machine-readable strings
```

The meanings are:

- `supported`: the metric is computable for the declared scope from
  authoritative persisted data. An empty supported collection has zero rows;
  it does not invent a position.
- `unavailable`: the schema or current contract cannot provide the metric
  safely, or a value is in a currency that cannot be normalized under the
  RUB-only contract.
- `unknown`: the metric could be relevant, but a required persisted value is
  absent or unusable for the affected row. The service does not substitute a
  default.

When several row issues affect one metric, aggregate status is deterministic:
`unavailable` takes precedence over `unknown`, which takes precedence over
`supported`. All applicable reason codes remain present in sorted order.

Required reason codes for this slice include:

| Reason code | Meaning |
| --- | --- |
| `issuer_not_persisted` | No issuer field exists in the current schema. |
| `maturity_not_persisted` | No maturity field exists in the current schema. |
| `currency_not_persisted` | A valuation-bearing row has no usable currency value. |
| `currency_conversion_not_supported` | A non-RUB valuation/event cannot be compared without FX. |
| `cash_not_account_linked` | Cash is persisted without `account_id`; it remains unassigned. |
| `no_dated_payouts` | No dated payout/redemption event exists in the accepted 12-month scope. |
| `deposit_forecast_not_concentratable` | #137 deposit estimate has no dated account/instrument event. |
| `unsupported_position_valuation` | A position valuation cannot be safely included in the RUB scope. |
| `instrument_type_not_authoritative` | A position has no valid persisted instrument-type enum value. |
| `instrument_not_persisted` | A dated payout event has no instrument relation available for grouping. |
| `broker_identity_not_persisted` | No authoritative broker identity is persisted on the account. |
| `bank_identity_not_persisted` | No authoritative bank identity is persisted on the account. |

## Implemented metrics in this slice

### Allocation by explicit type / asset class

Rows use only these persisted, explicit buckets:

- `cash` from included RUB cash balances;
- `deposits` from included account-linked deposit snapshots;
- each `Instrument.instrument_type` value independently for included RUB
  positions.

The service does not collapse all non-stock/non-bond instruments into a
synthetic `gold_other` class for this contract. Percentages use the safe RUB
liquid-asset denominator; excluded non-RUB/unknown valuations are surfaced in
support metadata and are not added to a RUB total.

### Allocation by account

Account rows sum included RUB positions and deposits by `account_id`. Included
cash is exposed as an `unassigned_cash` row and in the unallocated amount
because the persisted cash row has no account relation. The service never maps
cash by account name, account type, or row order. Account shares use the safe
RUB liquid-asset denominator and therefore can sum to less than 100% when
unassigned cash or excluded valuations exist.

### Top-N positions and concentration

Top positions are individual persisted `(account_id, instrument_id)` position
snapshots, ranked by `market_value_kopecks` descending and then stable IDs
ascending. The response includes each position's amount/share and the sum/share
of the selected top N. This is descriptive concentration only; no threshold,
score, probability, or recommendation is produced.

### Future payout and redemption concentration

The service first consumes the accepted #137 merged 12-month ladder. It does
not independently reimplement duplicate handling or resurrect cancelled,
dismissed, unresolved, or out-of-window provider rows.

- `payout` concentration uses dated `coupon`, `dividend`, `interest`, and
  `other` ladder events only. The `interest` event type is the explicit
  persisted cash-flow type, not the undated deposit estimate.
- `redemption` concentration uses dated `redemption` events only.
- Redemption amount is never included in passive payout totals.
- Events are grouped by their persisted account/instrument scope and retain
  the ladder's approximation flag and deterministic event count.
- A deposit monthly estimate contributes to #137 monthly totals, but it has no
  dated instrument/account event and is therefore not assigned to a
  concentration bucket; the response states that limitation explicitly.
- Missing/non-RUB event currency fails closed with `unknown` or `unavailable`;
  no conversion is attempted.

## API shape

`GET /api/analytics/risk-allocation?month_id={id}&top_n=5&forecast_version=v1`
returns the deterministic read model. `month_id` selects the persisted
reporting-month snapshot; `top_n` is bounded to 1..100. Every money value is a
RUB `MoneyValue`. Percentages are nullable two-decimal decimal strings, so a
zero denominator is represented by `null`, not `0%`.

The response contains `allocation_by_asset_class`,
`allocation_by_account`, `top_positions`, `payout_concentration`, and
`redemption_concentration`. Each metric has `support`, exact denominator and
coverage fields, deterministic rows, and row-level `excluded` issues. The
top-level `support` map makes issuer, currency, maturity, broker, and bank
limitations explicit even when their corresponding metric is not computed.

## Explicitly not implemented / follow-up

The following remain outside issue #169:

1. Persisted issuer identity and issuer concentration.
2. A first-class maturity field and maturity ladder/concentration.
3. Complete currency exposure across mixed-currency valuations, including an
   accepted FX/source/as-of contract.
4. Broker/bank identity on accounts and account-linked cash balances.
5. Target allocations and drift against targets.
6. Frontend views/types and visualization of this contract.
7. Any risk score, default probability, recommendation, mark-to-market return,
   network refresh, schema change, or migration.
