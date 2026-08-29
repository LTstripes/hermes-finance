# R08-01B — valuation-point discovery and support matrix

This note records the required discovery performed from the exact `r07`
baseline `67118caf2305c8820b9ebfe22dcfa2c6346e2c41` before implementation.
It is limited to the valuation-point and performance-coverage foundation in
issue #190. It does not define or implement XIRR, TWRR, or R08-01C.

## Authoritative interpretation

The accepted #145 v2 contract is normative, including its explicit
`not_computable_*` outcomes. Accepted #179 semantics are preserved:
`ExternalFlow.scope_membership=unknown` is not evidence, and the present
`Account.include_in_returns` flag must not reclassify a historical flow.

The valuation service derives a point from one persisted reporting-month
snapshot. It never fills a missing component from another month, a month
label, a provider observation, or a capital delta. A point can expose a
persisted total only when its selected account components are authoritative.

## Discovery/support matrix

| Component | Persisted source and existing meaning | Portfolio scope | Account scope | Support outcome |
| --- | --- | --- | --- | --- |
| Valuation boundary | `reporting_months.snapshot_date` is a non-null `Date`; `status` is `draft` or `closed`. | The date is authoritative only for a closed month and is never reduced to `YYYY-MM`. | Same. | Missing date is handled defensively as unavailable; draft data is not a trusted valuation point. |
| Position value | `position_snapshots.market_value_kopecks`, backend-recomputed per month/account/instrument. | Authoritative for selected `include_in_returns` accounts when rows are present and values are valid. | Authoritative for the explicit in-scope account when rows are present and values are valid. | Missing account component is `unknown`; invalid persisted value is unavailable. The stored value is the existing RUB valuation; no FX is invented from `Instrument.currency`. |
| Deposit value | `deposit_snapshots.balance_kopecks`, account-linked and base-currency-denominated by the existing schema. | Authoritative for selected accounts when rows are present and valid. | Authoritative for the explicit account when rows are present and valid. | Missing account component is `unknown`; values are treated as base currency under #145 v2. |
| Performance cash | `cash_balances.amount_kopecks` and explicit `currency`; baseline has no account identity. | A legacy `NULL account_id` row cannot be assigned to the portfolio without guessing. | A legacy `NULL account_id` row cannot be assigned to an account. | Existing unlinked rows are `not_computable_scope_cash_unclassified`. The additive nullable account linkage introduced by R08-01B is authoritative only when populated; non-RUB rows are unavailable without an accepted conversion. |
| Scope membership evidence | `external_flows.scope_membership` from accepted #179; transfer identity/status comes from R08-01A. | `unknown` is non-authoritative; unresolved transfer identity remains unresolved. | Same, with account boundary classification from explicit account identity. | These states are reported in coverage metadata and never converted to zero. Current `include_in_returns` is not used to rewrite historical flow classification. |
| Quote/provenance/freshness | `PositionSnapshot.price_date`/`price_source`, optional immutable `PositionQuoteProvenance`, and read-only R07 freshness service. | Provenance is attached to position components. | Same. | No refresh/network call. Existing persisted valuation remains the source; freshness/quality is metadata, not a replacement value. |
| Excluded sources | `expected_cash_flows`/provider payout rows are forecast/calendar data; legacy `investment_cash_flows` are not boundary proof. Debts and property are outside gross performance valuation. | Never added to the valuation total. | Never added to the valuation total. | Excluded by contract; no double counting of internal interest, coupons, dividends, redemptions, fees, or taxes. |

## Deliberate implementation boundary

The baseline has no trusted top-level portfolio valuation row and no account
identity for cash. Therefore the smallest additive solution is a nullable
`cash_balances.account_id` link. Existing rows remain unclassified and keep
their current liquid-capital behavior; the new performance service fails
closed when such a row could affect the selected scope. No legacy cash row is
backfilled or inferred from `name`, `include_in_capital`, or account flags.

Valuation points are derived read-only DTOs. They report exact RUB totals only
for authoritative selected components, with component coverage, provenance,
quality, and stable reason codes. Availability of an interval and return
metric remains the explicit R08-01C/#146/#147 boundary.
