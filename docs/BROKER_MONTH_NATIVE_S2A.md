# Broker month S2a: source-native representation

Scope: [#772](https://github.com/LTstripes/hermes-finance/issues/772), under
[#768 accepted amendments](https://github.com/LTstripes/hermes-finance/issues/768#issuecomment-6106797516).
This is the persistence/consumer subcandidate. It does not assemble or import a
broker month, change existing receipts, or supply indicative/exact returns.

## Persisted contract

`PositionSnapshot.price_source=broker_statement_native`, `native_contract_version=1`
stores exact RUB `market_value_kopecks` independently of quantity. The internal
transaction-scoped helper leaves unproved per-unit price, average acquisition
cost, cost basis and unrealized result null. Accrued interest is independently
nullable; `bond_nkd_basis=unknown|included|excluded|not_applicable` describes the
native total's basis and never supplies a missing NKD amount. Stock requires
`not_applicable`; bond requires one of the other three values. Source asset kind
must match the instrument and is frozen in `historical_instrument_type`.

`InvestmentCashFlow.amount_basis=broker_statement_net_v1` stores actual posted
net RUB for stock/bond payouts. Gross, tax and commission are null. Redemption
remains principal repayment, outside passive income/result sums. No calendar
forecast becomes an actual payment. Legacy `gross_components` arithmetic and
manual position formulas remain unchanged.

Both modes reference an existing immutable `MyBrokerImport` plus a canonical
SHA256 fact key. The source date must be in that source interval; a position
must use the month snapshot date and a payout must lie in the actual month.
Source money is bounded nonnegative integer kopecks; source quantity is exact,
positive, at most six decimals, whole for stocks and within Numeric(18,6).
SQLite quantities that cannot round-trip exactly are refused; the caller must
roll back the entire staging transaction on any validation or flush error.
The account/fact-key unique constraint prevents a second cash projection,
including two concurrent attempts or the same fact seen in overlapping sources.

The helpers flush without committing. They are representation primitives, **not
source authority or Preview/Apply**: S2b must verify the original-bound facts,
effective mappings/dispositions/corrections, canonical cross-document identity,
economic ownership against existing events, stale dependencies and the global
month state inside one writer transaction. Referencing an import and key alone
does not prove those facts. No public manual create/update payload exposes these
modes. Manual, quote and legacy broker Apply cannot revise/delete native rows;
a later reviewed source revision lifecycle is required.

Migration 0056 preserves every existing column/value/reference. Added legacy
basis defaults are `gross_components` and `unknown`, with no guessed bond basis.
Guarded nullable CHECKs keep legacy fields mandatory. Downgrade preserves legacy
data and refuses any native row rather than discarding facts or filling nulls.
Only synthetic databases are used for migration verification in this slice.
The older 0045 downgrade explicitly removes its reflected historical-kind CHECK
before dropping the column, so the 0056 batch rebuild preserves full downgrade
compatibility as well as the source-fact refusal.

## Consumer inventory

| Consumer | Source-mode behavior |
| --- | --- |
| Position/payout GET DTOs, desktop types | Exact total/net and nullable components plus explicit mode/provenance |
| Dashboard account/class results | One missing cost/P&L makes its whole aggregate unavailable, including mixed manual/native rows |
| IIS result and summary | Known coupon/dividend cash stays visible; unknown unrealized result makes both total results null |
| JSON export 1.3 / Markdown report | Nullable raw and report components; no fabricated tax or P&L zero |
| AI bundle / financial review | Missing acquisition cost/P&L/NKD unavailable; statement provenance retained |
| Broker reconciliation / statement preparation | Nullable local evidence preserved; old component-based linking/apply checks unchanged |
| Quote preview/apply, position/payout manual CRUD | Native facts cannot be overwritten; quote preview excludes native totals |
| Month clone | Native EOD positions are not carried to a different source date; actual payouts were never cloned |
| Monthly Close | Existing global workflow and other-account/nonbroker blockers remain; no new source-only readiness exemption |
| Exact valuation / class eligibility / XIRR normal and historical fallback | Native totals do not establish exact economic basis or promote solver quality |

No new source completeness assertion or source Close orchestration is supplied.
Bookkeeping capital includes proven totals; amount-known is not cost-basis-known
or proof of complete source/account coverage. S2b still owns the audited source
readiness path. #771 integration must use its transaction-scoped identity helpers
without changing S1 accepted evidence or committing a separate import.
